from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark.events import parse_codex_events
from middle_man.gateway.codex_benchmark.native_reads import explicit_read_paths
from middle_man.gateway.codex_benchmark.overlap import measure_delivery
from middle_man.gateway.codex_benchmark.runner import (
    _evaluate, _server_args, aggregate_report, build_invocation, evaluate_preemption_v2, run_suite,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.gateway import MCPGateway
from middle_man.mcp.surface import measure_tool_surface
from middle_man.mcp.usage import MCP_USAGE_SCHEMA_VERSION, server_implementation_identity

mcp = pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters


def test_task_a_versions_and_structured_gate(tmp_path: Path) -> None:
    v1 = next(task for task in TASKS if task.id == "preemption")
    v2 = next(task for task in TASKS if task.id == "preemption-v2")
    assert v1.schema_version == 1
    assert v1.required_facts == ("LargestPrivateOwnerPolicy", "MemoryController", "RECOMPUTE",
                                 "output_generated", "test_phase_7_preemption")
    assert v2.schema_version == 2 and not v2.required_facts
    assert "LargestPrivateOwnerPolicy" not in v2.prompt
    good = {"victim_selection_symbol": "LargestPrivateOwnerPolicy",
            "memory_control_symbol": "MemoryController", "recomputation_symbol": "RECOMPUTE",
            "output_preservation_symbol": "output_generated",
            "test_file": "tests/test_phase_7_preemption.py", "explanation": "Retains generated output."}
    assert evaluate_preemption_v2(json.dumps(good)) == ()
    passed, notes, _, _ = _evaluate(v2, tmp_path, json.dumps(good), (), (), (), 0, 0)
    assert passed and not notes
    assert not _evaluate(v2, tmp_path, json.dumps({**good, "recomputation_symbol": "wrong"}),
                         (), (), (), 0, 0)[0]
    assert not _evaluate(v2, tmp_path, "not JSON", (), (), (), 0, 0)[0]
    assert not _evaluate(v2, tmp_path, json.dumps(good), ("changed.py",), (), (" M changed.py",), 0, 1)[0]
    a = build_invocation("codex", v2, "baseline", tmp_path, model="gpt-6-sol", effort="high")
    b = build_invocation("codex", v2, "optimized", tmp_path, model="gpt-6-sol", effort="high")
    assert a[a.index("--output-schema") + 1] == b[b.index("--output-schema") + 1]
    assert Path(a[a.index("--output-schema") + 1]).is_file()
    with pytest.raises(ValueError, match="different versions"):
        aggregate_report([{"task_id": "preemption", "task_version": 1, "valid": False},
                          {"task_id": "preemption-v2", "task_version": 2, "valid": False}])


def test_observed_windows_commands_and_explicit_read_only(tmp_path: Path) -> None:
    for relative in ("middle_man/lab/preemption.py", "middle_man/lab/work.py",
                     "tests/test_phase_7_preemption.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    fixture = (Path(__file__).parent / "fixtures" / "codex_task_a_windows_events.jsonl").read_text(encoding="utf-8")
    result = parse_codex_events(fixture.splitlines(), tmp_path)
    assert result.native.file_reads == 3
    assert result.native.unique_files == ("middle_man/lab/preemption.py", "middle_man/lab/work.py",
                                          "tests/test_phase_7_preemption.py")
    assert result.native.search_calls == 1
    assert all("Dennis" not in line for line in fixture.splitlines())

    spaced = tmp_path / "folder with space" / "O'Loane.py"
    spaced.parent.mkdir()
    spaced.write_text("pass\n", encoding="utf-8")
    commands = [f'Get-Content -LiteralPath "{spaced}"',
                f'type "{spaced}"', f'cat "{spaced}"',
                f'Path(r"{spaced}").read_text()',
                f'Path(r"{spaced}").read_bytes()',
                f'open(r"{spaced}", "rb").read()',
                f'open(r"{spaced}").read()']
    for command in commands:
        assert explicit_read_paths(command, tmp_path) == ("folder with space/O'Loane.py",), command
    assert explicit_read_paths(f'rg "{spaced}" .', tmp_path) == ()
    outside = tmp_path.parent / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    assert explicit_read_paths(f'Get-Content -LiteralPath "{outside}"', tmp_path) == ()


def test_core_full_surface_and_direct_context(tmp_path: Path) -> None:
    (tmp_path / "preemption.py").write_text(
        "class LargestPrivateOwnerPolicy:\n    pass\nclass MemoryController:\n    pass\n"
        "RECOMPUTE = 1\noutput_generated = 2\n", encoding="utf-8")
    config = GatewayConfig(tmp_path)
    full = asyncio.run(measure_tool_surface(config, "full"))
    core = asyncio.run(measure_tool_surface(config, "codex-core"))
    assert full.tool_count == 10 and core.tool_count == 5
    assert core.total_definition_tokens < full.total_definition_tokens
    assert all(item.description_tokens and item.input_schema_tokens and item.definition_tokens for item in full.tools)
    gateway = MCPGateway(config)
    full_pack = gateway.context_pack("KV preemption LargestPrivateOwnerPolicy", mode="balanced", max_context_tokens=6000)
    core_gateway = MCPGateway(config)
    core_pack = core_gateway.context("KV preemption LargestPrivateOwnerPolicy", mode="balanced", max_context_tokens=6000)
    assert full_pack["fingerprint"] == core_pack["fingerprint"]
    assert full_pack["warnings"] == core_pack["warnings"]
    assert full_pack["metrics"]["estimated_selected_tokens"] == core_pack["metrics"]["selected_tokens"]
    assert [(item["path"], item["start_line"], item["end_line"], item["text"]) for item in full_pack["excerpts"]] == [
        (item["path"], item["start_line"], item["end_line"], item["text"]) for item in core_pack["excerpts"]]
    assert "candidates" not in core_pack and "selected_paths" not in core_pack
    estimate = HeuristicTokenEstimator()
    assert estimate.estimate(json.dumps(core_pack)) < estimate.estimate(json.dumps(full_pack))
    replay = core_gateway.context("KV preemption LargestPrivateOwnerPolicy", mode="balanced", max_context_tokens=6000)
    assert replay["unchanged"] and replay["already_delivered"] and replay["excerpts"] == []
    assert core_gateway.context("KV preemption LargestPrivateOwnerPolicy", mode="balanced",
                           max_context_tokens=6000, force_replay=True)["excerpts"]
    records = [json.loads(line) for line in (config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[1]["delivery"] and records[2]["delivery"] == []
    assert measure_delivery(records).overlap_available
    assert all(entry["server_implementation"] == server_implementation_identity() for entry in records)
    assert all(entry["schema_version"] == MCP_USAGE_SCHEMA_VERSION for entry in records)
    assert "class LargestPrivateOwnerPolicy" not in json.dumps(records)
    assert "class LargestPrivateOwnerPolicy" not in repr(core_gateway.delivery_ledger.__dict__)


def test_core_expansion_is_delta(tmp_path: Path) -> None:
    (tmp_path / "engine.py").write_text(
        "def preemption():\n    return 1\n\n" +
        "".join(f"def helper_{i}():\n    return {i}\n\n" for i in range(90)),
        encoding="utf-8")
    gateway = MCPGateway(GatewayConfig(tmp_path))
    initial = gateway.context("preemption", mode="aggressive", max_context_tokens=300)
    expanded = gateway.expand_context(initial["fingerprint"], "full_file", target="engine.py",
                                      max_context_tokens=3000, core=True)
    assert expanded["parent_fingerprint"] == initial["fingerprint"]
    assert expanded["delta_only"] and expanded["generation"] == 1
    old_lines = {(item["path"], line) for item in initial["excerpts"]
                 for line in range(item["start_line"], item["end_line"] + 1)}
    new_lines = {(item["path"], line) for item in expanded["excerpts"]
                 for line in range(item["start_line"], item["end_line"] + 1)}
    assert new_lines and not old_lines.intersection(new_lines)
    assert measure_delivery(json.loads(line) for line in
                            (gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8").splitlines()).overlap_available


def test_snapshot_package_cannot_shadow_current_mcp_server(tmp_path: Path) -> None:
    shadow = tmp_path / "middle_man" / "mcp"
    shadow.mkdir(parents=True)
    (shadow.parent / "__init__.py").write_text("raise RuntimeError('shadow imported')\n", encoding="utf-8")
    (shadow / "usage.py").write_text("MCP_USAGE_SCHEMA_VERSION = 999\n", encoding="utf-8")
    (tmp_path / "target.py").write_text("def target():\n    return 1\n", encoding="utf-8")

    async def exercise() -> None:
        params = StdioServerParameters(command=sys.executable, args=_server_args(tmp_path), cwd=tmp_path)
        async with Client(params, raise_exceptions=True, read_timeout_seconds=20) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "middleman_context", "middleman_expand_context", "middleman_session_handoff",
                "middleman_compact_output", "middleman_project_state"}
            result = await client.call_tool("middleman_context", {"task": "target", "max_context_tokens": 500})
            assert not result.is_error and result.structured_content["excerpts"]

    asyncio.run(exercise())
    entries = [json.loads(line) for line in (tmp_path / ".middle_man_cache" / "mcp_usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert entries[0]["server_implementation"] == server_implementation_identity()
    assert entries[0]["schema_version"] == MCP_USAGE_SCHEMA_VERSION != 999
    assert entries[0]["delivery"] and measure_delivery(entries).overlap_available


def test_core_multiline_secret_redaction_never_blocks_source(tmp_path: Path) -> None:
    (tmp_path / "fixture.txt").write_text(
        "target\n-----BEGIN PRIVATE KEY-----\nabc123\ndef456\n-----END PRIVATE KEY-----\nend\n",
        encoding="utf-8",
    )
    gateway = MCPGateway(GatewayConfig(tmp_path))
    result = gateway.context("target", paths=["fixture.txt"], max_context_tokens=1000)
    assert result["excerpts"]
    text = json.dumps(result)
    assert "abc123" not in text and "def456" not in text
    assert "MIDDLE_MAN_REDACTED_SECRET" in text
    assert gateway.context("target", paths=["fixture.txt"], max_context_tokens=1000)["excerpts"] == []


def test_agents_routes_fresh_work_directly() -> None:
    guidance = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    assert "fresh scoped" in guidance and "middleman_context" in guidance
    assert "middleman_find_context" not in guidance
    assert HeuristicTokenEstimator().estimate(guidance) <= 213

def test_mixed_task_a_versions_stop_before_codex_lookup(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner._codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("Codex lookup must not run")))
    with pytest.raises(ValueError, match="cannot run and aggregate"):
        run_suite(("preemption", "preemption-v2"), repository_root=tmp_path, artifact_base=tmp_path)


def test_powershell_single_quoted_apostrophe_path(tmp_path: Path) -> None:
    path = tmp_path / "O'Loane.py"
    path.write_text("pass\n", encoding="utf-8")
    assert explicit_read_paths("Get-Content -LiteralPath 'O''Loane.py'", tmp_path) == ("O'Loane.py",)