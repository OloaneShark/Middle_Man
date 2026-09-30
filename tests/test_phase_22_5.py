from __future__ import annotations

import json
from pathlib import Path

import pytest

from middle_man.cli.main import build_parser
from middle_man.cli.mcp import run_mcp
from middle_man.gateway.codex_benchmark.overlap import measure_delivery
from middle_man.gateway.codex_benchmark.preemption_v3 import measure_required_source
from middle_man.gateway.codex_benchmark.runner import (
    _server_args, classify_native_read_coverage, validate_initial_context_budgets,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity, BenchmarkPolicy
from middle_man.mcp.gateway import MCPGateway


TASK = next(item for item in TASKS if item.id == "preemption-v3")
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
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-5") / "pair", "guidance\n")
    return optimized


def _entries(gateway: MCPGateway) -> tuple[dict, ...]:
    path = gateway.config.cache_dir / "mcp_usage.jsonl"
    return tuple(item for item in map(json.loads, path.read_text(encoding="utf-8").splitlines())
                 if item.get("server_session_id") == gateway.server_session_id)


def _sequence(root: Path, *, benchmark: bool, replay: bool) -> tuple[MCPGateway, tuple[dict, ...]]:
    identity = BenchmarkIdentity("local-phase-22-5", TASK.id, "optimized", "fixture") if benchmark else None
    gateway = MCPGateway(GatewayConfig(root), benchmark_identity=identity)
    first = gateway.context(FIRST, mode="balanced", max_context_tokens=9000)
    second = gateway.context(SECOND, mode="balanced", max_context_tokens=11000,
                             paths=PATHS, symbols=SYMBOLS, force_replay=replay)
    assert first["fingerprint"] != second["fingerprint"]
    for target in ("middle_man/lab/engine.py", "middle_man/lab/request.py"):
        expanded = gateway.expand_context(first["fingerprint"], "full_file", target=target, core=True,
                                          max_context_tokens=12000)
        assert expanded["delta_only"]
    return gateway, _entries(gateway)


def test_benchmark_policy_and_cli_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_parser()
    args = parser.parse_args(["mcp", "serve", "--repo", str(tmp_path), "--benchmark-run-id", "local",
                              "--benchmark-task-id", TASK.id, "--benchmark-mode", "optimized",
                              "--benchmark-source-commit", "fixture", "--benchmark-context-budget", "6000",
                              "--benchmark-expansion-budget", "12000"])
    assert args.benchmark_context_budget == 6000
    assert args.benchmark_expansion_budget == 12000
    captured = []
    monkeypatch.setattr("middle_man.mcp.server.serve", lambda config, **kwargs: captured.append(kwargs))
    run_mcp(args)
    assert captured[0]["benchmark_identity"].policy == BenchmarkPolicy(6000, 12000)
    server_args = _server_args(tmp_path, run_id="local", task_id=TASK.id, mode="optimized")
    assert server_args[server_args.index("--benchmark-context-budget") + 1] == "6000"
    assert server_args[server_args.index("--benchmark-expansion-budget") + 1] == "12000"
    for initial, expansion in ((0, 12000), (6001, 6000), (6000, 12001)):
        with pytest.raises(ValueError, match="benchmark budgets"):
            BenchmarkPolicy(initial, expansion)
    without_identity = parser.parse_args(["mcp", "serve", "--repo", str(tmp_path),
                                          "--benchmark-context-budget", "6000"])
    with pytest.raises(SystemExit, match="benchmark budgets require"):
        run_mcp(without_identity)


def test_normal_budget_and_metadata_privacy(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def target(): return 1\n", encoding="utf-8")
    gateway = MCPGateway(GatewayConfig(tmp_path))
    query = "Find target in app.py"
    result = gateway.context(query, max_context_tokens=12000)
    assert "budget" not in result
    entry = _entries(gateway)[0]
    assert entry["budget"]["effective_context_tokens"] == 12000
    assert entry["budget"]["benchmark_context_cap"] is None
    assert query not in (gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="max_context_tokens"):
        gateway.context(query, max_context_tokens=12001)


def test_cap_receipt_and_expansion_are_separate(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def target(): return 1\n", encoding="utf-8")
    identity = BenchmarkIdentity("local-cap", TASK.id, "optimized", "fixture",
                                 BenchmarkPolicy(6000, 8000))
    gateway = MCPGateway(GatewayConfig(tmp_path), benchmark_identity=identity)
    first = gateway.context("Find target in app.py", max_context_tokens=9000)
    second = gateway.context("Find target again in app.py", max_context_tokens=11000)
    gateway.expand_context(first["fingerprint"], "full_file", target="app.py", core=True,
                           max_context_tokens=10000)
    entries = _entries(gateway)
    for requested, response, entry in ((9000, first, entries[0]), (11000, second, entries[1])):
        assert response["budget"]["requested_context_tokens"] == requested
        assert response["budget"]["effective_context_tokens"] == 6000
        assert response["budget"]["budget_capped"] is True
        assert entry["budget"]["benchmark_context_cap"] == 6000
    receipts = tuple(map(json.loads, (gateway.config.cache_dir / "benchmark_receipts.jsonl")
                         .read_text(encoding="utf-8").splitlines()))
    assert [(r["query"]["requested_budget"], r["query"]["effective_budget"],
             r["query"]["benchmark_cap"]) for r in receipts] == [(9000, 6000, 6000), (11000, 6000, 6000)]
    assert entries[2]["budget"]["requested_expansion_budget"] == 10000
    assert entries[2]["budget"]["effective_expansion_budget"] == 8000
    assert not validate_initial_context_budgets(entries, 6000)
    assert validate_initial_context_budgets(({**entries[0], "budget": {
        **entries[0]["budget"], "effective_context_tokens": 9000}},), 6000)
    assert validate_initial_context_budgets(({**entries[0], "budget": {}},), 6000)


def test_exact_recorded_sequence_and_replay_diagnosis(pinned: Path) -> None:
    historical, old = _sequence(pinned, benchmark=False, replay=True)
    capped, entries = _sequence(pinned, benchmark=True, replay=True)
    nonreplay, clean = _sequence(pinned, benchmark=True, replay=False)
    repeat, repeated_session = _sequence(pinned, benchmark=True, replay=True)
    assert len({historical.server_session_id, capped.server_session_id,
                nonreplay.server_session_id, repeat.server_session_id}) == 4
    for records in (old, entries, clean, repeated_session):
        assert [item["call_sequence"] for item in records] == [1, 2, 3, 4]
        assert all(item["server_session_id"] == records[0]["server_session_id"] for item in records)
        assert all(item["ledger_lines_after"] >= item["ledger_lines_before"] for item in records)
        assert all(records[i]["ledger_lines_after"] == records[i + 1]["ledger_lines_before"]
                   for i in range(3))
        assert all(item["new_lines_delivered"] ==
                   item["ledger_lines_after"] - item["ledger_lines_before"] for item in records)
    assert [item["budget"]["effective_context_tokens"] for item in old[:2]] == [9000, 11000]
    assert [item["budget"]["effective_context_tokens"] for item in entries[:2]] == [6000, 6000]
    assert [item["budget"]["requested_context_tokens"] for item in entries[:2]] == [9000, 11000]
    assert entries[1]["budget"]["force_replay"] is True
    first_pack = capped._packs[entries[0]["pack_fingerprint"]]
    recall = measure_required_source(first_pack)
    assert recall.required_file_recall == recall.required_symbol_recall == 1.0
    assert first_pack.metrics.estimated_selected_tokens == 5891
    assert not any(item.repair_candidate for item in first_pack.selection_diagnostics)
    assert entries[1]["metrics"]["selected_tokens"] <= 6000
    assert entries[1]["delivery"]
    assert measure_delivery(entries).repeated_source_bytes > 0
    assert measure_delivery(entries[:2]).repeated_source_bytes == measure_delivery(entries).repeated_source_bytes
    assert measure_delivery(clean).repeated_source_bytes == 0
    assert clean[1]["metrics"]["selected_tokens"] > 0
    assert clean[1]["delivery"] != entries[1]["delivery"]
    assert all(item["new_lines_delivered"] >= 0 for item in entries[2:])
    assert "text" not in repr(capped.delivery_ledger.__dict__)
    assert not any(isinstance(item, str) and "def " in item for item in capped.delivery_ledger.__dict__.values())
    print("PHASE22_5_LOCAL", json.dumps({
        "historical_overlap": measure_delivery(old).overlap_ratio,
        "capped_overlap_with_force_replay": measure_delivery(entries).overlap_ratio,
        "capped_overlap_without_force_replay": measure_delivery(clean).overlap_ratio,
        "first_selected": entries[0]["metrics"]["selected_tokens"],
        "second_selected": entries[1]["metrics"]["selected_tokens"],
        "second_delivered_bytes": sum(sum(r["line_bytes"]) for r in entries[1]["delivery"]),
        "second_delta_bytes_without_replay": sum(sum(r["line_bytes"]) for r in clean[1]["delivery"]),
        "ranges": [len(item["delivery"]) for item in entries],
        "session_id": capped.server_session_id,
        "ledger": [[item["ledger_lines_before"], item["ledger_lines_after"]] for item in entries],
    }, sort_keys=True))


def test_native_read_coverage_classification(tmp_path: Path) -> None:
    for name in ("absent.py", "partial.py", "complete.py"):
        (tmp_path / name).write_text("first\nsecond\n", encoding="utf-8")
    entries = ({"success": True, "delivery": [
        {"path": "partial.py", "start_line": 1, "end_line": 1},
        {"path": "complete.py", "start_line": 1, "end_line": 2},
    ]},)
    assert classify_native_read_coverage(tmp_path, ("absent.py", "partial.py", "complete.py"), entries) == (
        ("absent.py", "ABSENT_FROM_MCP"), ("partial.py", "PARTIAL_IN_MCP"),
        ("complete.py", "COMPLETE_IN_MCP"))
