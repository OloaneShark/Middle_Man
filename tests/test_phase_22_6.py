from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from middle_man.gateway.codex_benchmark.overlap import measure_delivery
from middle_man.gateway.codex_benchmark.preemption_v3 import measure_required_source
from middle_man.gateway.codex_benchmark.runner import (
    _infrastructure_valid, _server_args, validate_initial_context_budgets,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity
from middle_man.mcp.gateway import MCPGateway
from middle_man.mcp.surface import measure_tool_surface
TASK = next(item for item in TASKS if item.id == "preemption-v3")
CORE_TOOLS = {"middleman_project_state", "middleman_session_handoff", "middleman_context",
              "middleman_expand_context", "middleman_compact_output"}
FIRST = (
    "Explain how KV preemption works in this Middle_Man repository. Identify concrete "
    "implementation symbols/components for victim selection, memory release/control, "
    "recomputation, output preservation, and the proving test file. Need concise verified "
    "explanation; read only."
)
SECOND = (
    "Read exact InferenceRequest.mark_preempted, apply_recompute or equivalent, output tracking, "
    "SimulationEngine.run victim requeue and _apply_execution, and scheduler recompute work. "
    "Only these relevant files, no broad imports."
)
PATHS = ["middle_man/lab/request.py", "middle_man/lab/engine.py", "middle_man/lab/scheduler.py"]
SYMBOLS = ["InferenceRequest.mark_preempted", "InferenceRequest.apply_recompute",
           "SimulationEngine.run", "SimulationEngine._apply_execution"]


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-6") / "pair", "guidance\n")
    return optimized


def _source_lines(pack: object) -> set[tuple[str, str, int]]:
    return {(item.path, item.content_hash, number)
            for item in pack.excerpts for number in range(item.start_line, item.end_line + 1)}


def _delivered_lines(entry: dict) -> set[tuple[str, str, int]]:
    return {(item["path"], item["content_hash"], number)
            for item in entry["delivery"] for number in range(item["start_line"], item["end_line"] + 1)}


def test_stdio_schema_and_two_context_delta_sequence(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    builder = ContextBuilder(config)
    first_pack = builder.build(FIRST, mode="balanced", max_context_tokens=6000)
    second_pack = builder.build(ContextQuery(SECOND, tuple(PATHS), tuple(SYMBOLS), ""),
                                mode="balanced", max_context_tokens=6000)
    selected_overlap = _source_lines(first_pack) & _source_lines(second_pack)
    assert first_pack.fingerprint != second_pack.fingerprint
    assert len(selected_overlap) == 176
    assert measure_required_source(first_pack).required_file_recall == 1.0
    assert measure_required_source(first_pack).required_symbol_recall == 1.0
    assert first_pack.metrics.estimated_selected_tokens == 5891
    assert any(item.path == "middle_man/lab/preemption.py" and item.complete_file
               for item in first_pack.excerpts)
    assert any(item.path == "middle_man/lab/preemption.py" for item in second_pack.excerpts)

    async def exercise() -> tuple[dict, dict, dict]:
        params = StdioServerParameters(command=sys.executable,
                                       args=_server_args(pinned, run_id="local-22-6", task_id=TASK.id,
                                                         mode="optimized"), cwd=pinned)
        async with Client(params, raise_exceptions=True, read_timeout_seconds=30) as client:
            listing = await client.list_tools()
            assert {tool.name for tool in listing.tools} == CORE_TOOLS
            tool = next(tool for tool in listing.tools if tool.name == "middleman_context")
            assert "force_replay" not in json.dumps(tool.model_dump(mode="json"))
            assert "force_replay" not in json.dumps(tool.input_schema)
            assert "force_replay" not in (tool.description or "")
            first = await client.call_tool("middleman_context", {"task": FIRST, "mode": "balanced",
                                                                  "max_context_tokens": 9000})
            second = await client.call_tool("middleman_context", {"task": SECOND, "mode": "balanced",
                                                                   "max_context_tokens": 11000,
                                                                   "paths": PATHS, "symbols": SYMBOLS})
            assert not first.is_error and not second.is_error
            first_data, second_data = first.structured_content, second.structured_content
            for target in ("middle_man/lab/engine.py", "middle_man/lab/request.py"):
                expanded = await client.call_tool("middleman_expand_context", {
                    "fingerprint": first_data["fingerprint"], "kind": "full_file", "target": target,
                    "max_context_tokens": 12000})
                assert not expanded.is_error and expanded.structured_content["delta_only"]
            return first_data, second_data, tool.model_dump(mode="json")

    first, second, _ = asyncio.run(exercise())
    assert first["fingerprint"] == first_pack.fingerprint
    assert second["fingerprint"] == second_pack.fingerprint
    assert [(item["requested_context_tokens"], item["effective_context_tokens"])
            for item in (first["budget"], second["budget"])] == [(9000, 6000), (11000, 6000)]
    assert not any(item["path"] == "middle_man/lab/preemption.py" for item in second["excerpts"])
    records = tuple(map(json.loads, (config.cache_dir / "mcp_usage.jsonl")
                        .read_text(encoding="utf-8").splitlines()))
    assert [item["tool"] for item in records] == ["middleman_context", "middleman_context",
                                                  "middleman_expand_context", "middleman_expand_context"]
    assert [item["call_sequence"] for item in records] == [1, 2, 3, 4]
    assert len({item["server_session_id"] for item in records}) == 1
    assert all(item["budget"]["force_replay"] is False for item in records[:2])
    assert [(item["budget"]["requested_context_tokens"], item["budget"]["effective_context_tokens"])
            for item in records[:2]] == [(9000, 6000), (11000, 6000)]
    assert not validate_initial_context_budgets(records, 6000)
    assert all(item["ledger_lines_after"] >= item["ledger_lines_before"] for item in records)
    assert all(records[index]["ledger_lines_after"] == records[index + 1]["ledger_lines_before"]
               for index in range(3))
    assert all(item["new_lines_delivered"] == item["ledger_lines_after"] - item["ledger_lines_before"]
               for item in records)
    assert _delivered_lines(records[0]) == _source_lines(first_pack)
    assert _delivered_lines(records[1]) == _source_lines(second_pack) - _source_lines(first_pack)
    assert any(path == "middle_man/lab/engine.py" for path, _, _ in _delivered_lines(records[1]))
    assert len(_delivered_lines(records[1]) & _delivered_lines(records[0])) == 0
    assert measure_delivery(records).repeated_source_bytes == 0
    assert measure_delivery(records).overlap_ratio == 0.0
    assert records[2]["new_lines_delivered"] > 0 and records[3]["new_lines_delivered"] > 0
    assert not any(_delivered_lines(records[index]) &
                   set().union(*(_delivered_lines(item) for item in records[:index]))
                   for index in (2, 3))
    receipts = tuple(map(json.loads, (config.cache_dir / "benchmark_receipts.jsonl")
                         .read_text(encoding="utf-8").splitlines()))
    assert [(item["query"]["requested_budget"], item["query"]["effective_budget"],
             item["query"]["benchmark_cap"]) for item in receipts] == [(9000, 6000, 6000),
                                                                          (11000, 6000, 6000)]
    usage = (config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8")
    assert FIRST not in usage and SECOND not in usage
    assert "def mark_preempted" not in usage
    surface = asyncio.run(measure_tool_surface(config, "codex-core"))
    assert surface.tool_count == 5 and surface.total_definition_tokens <= 851
    print("PHASE22_6_LOCAL", json.dumps({
        "tool_definition_tokens": surface.total_definition_tokens,
        "fingerprints": [first["fingerprint"], second["fingerprint"]],
        "selected_overlap_lines": len(selected_overlap),
        "delivered_overlap_bytes": measure_delivery(records).repeated_source_bytes,
        "selected_tokens": [first_pack.metrics.estimated_selected_tokens,
                            second_pack.metrics.estimated_selected_tokens],
        "delivered_ranges": [len(item["delivery"]) for item in records],
        "session_id": records[0]["server_session_id"],
        "ledger": [[item["ledger_lines_before"], item["ledger_lines_after"]] for item in records],
    }, sort_keys=True))


def test_internal_force_replay_remains_diagnostic_and_is_invalid_for_benchmark(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    identity = BenchmarkIdentity("local-replay-control", TASK.id, "optimized", "fixture")
    gateway = MCPGateway(GatewayConfig(tmp_path), benchmark_identity=identity)
    first = gateway.context("Find target in source.py", max_context_tokens=9000)
    repeated = gateway.context("Find target in source.py", max_context_tokens=9000,
                               force_replay=True)
    assert first["excerpts"] and repeated["excerpts"]
    records = tuple(map(json.loads, (gateway.config.cache_dir / "mcp_usage.jsonl")
                        .read_text(encoding="utf-8").splitlines()))
    assert records[1]["budget"]["force_replay"] is True
    assert measure_delivery(records).repeated_source_bytes > 0
    warnings = validate_initial_context_budgets(records, 6000)
    assert "optimized model-facing context replay violates benchmark policy" in warnings
    assert not _infrastructure_valid("optimized", records, warnings)


def test_normal_context_budget_unchanged(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("def target(): pass\n", encoding="utf-8")
    gateway = MCPGateway(GatewayConfig(tmp_path))
    gateway.context("Find target", max_context_tokens=12000)
    record = json.loads((gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8"))
    assert record["budget"]["effective_context_tokens"] == 12000
    assert record["budget"]["benchmark_context_cap"] is None
