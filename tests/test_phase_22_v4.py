from __future__ import annotations

import asyncio
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark.preemption_v3 import (
    TASK_A_V3_UNITS, evaluate_preemption_v3, measure_required_source,
)
from middle_man.gateway.codex_benchmark.preemption_v4 import EXPECTED, evaluate_preemption_v4
from middle_man.gateway.codex_benchmark.runner import _evaluate, _server_args, aggregate_report, build_invocation, run_suite
from middle_man.gateway.codex_benchmark.tasks import TASKS, TASK_A_SOURCE_COMMIT, prepare_pair, source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity
from middle_man.mcp.gateway import MCPGateway


TASK = next(task for task in TASKS if task.id == "preemption-v4")
ROOT = Path(__file__).resolve().parents[1]


def _answer(**changes: object) -> str:
    return json.dumps({**EXPECTED, "explanation": "The policy chooses a victim; its KV state is rebuilt without losing generated output.",
                       **changes})


def test_v3_historical_values_remain_rejected_without_rescoring() -> None:
    original = {
        "victim_selection_symbol": "LargestPrivateOwnerPolicy.choose_victim",
        "memory_control_symbol": "MemoryController.prepare; KVBlockManager.release_request",
        "recomputation_symbol": "InferenceRequest.mark_preempted and apply_recompute; scheduler._prefill_candidates",
        "output_preservation_symbol": "InferenceRequest.output_generated and output_token_times_ms",
        "test_file": "tests/test_phase_7_preemption.py",
        "explanation": "The scheduler rebuilds context and preserves output.",
    }
    for fields in (original, {**original,
                            "recomputation_symbol": "InferenceRequest.mark_preempted and apply_recompute",
                            "test_file": "tests/test_phase_7_preemption.py::test_pressure_preempts_rebuilds_and_preserves_output"}):
        assert evaluate_preemption_v3(json.dumps(fields)) == (
            "incorrect structured field: recomputation_symbol",
            "incorrect structured field: output_preservation_symbol",
        )


def test_v4_task_schema_and_invocation_are_versioned(tmp_path: Path) -> None:
    assert TASK.schema_version == 4 and TASK.source_ref == TASK_A_SOURCE_COMMIT and TASK.read_only
    schema_path = ROOT / "middle_man/gateway/codex_benchmark/preemption_v4.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert set(schema["properties"]) == set(schema["required"]) == set(EXPECTED) | {"explanation"}
    assert schema["additionalProperties"] is False
    assert all(item["type"] == "string" and item["description"] for item in schema["properties"].values())
    assert not any(answer in TASK.prompt or answer in schema_path.read_text(encoding="utf-8")
                   for answer in EXPECTED.values())
    for mode in ("baseline", "optimized"):
        command = build_invocation("codex", TASK, mode, tmp_path, model="gpt-6-sol", effort="high")
        assert Path(command[command.index("--output-schema") + 1]) == schema_path
        assert "read-only" in command and "--ignore-user-config" in command


def test_run_all_dry_run_starts_with_v4_without_external_call(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner.run_suite",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    main(["codex", "benchmark", "run-all", "--repo", str(tmp_path), "--dry-run"])
    tasks = [line.split()[1] for line in capsys.readouterr().out.splitlines() if line.startswith("Task: ")]
    assert tasks == ["preemption-v4", "oauth-bug", "upload-feature"]


def test_v4_qualified_identifiers_and_explanation(tmp_path: Path) -> None:
    answer = _answer(victim_selection_policy="middle_man.lab.preemption.LargestPrivateOwnerPolicy",
                     memory_control_component="module.MemoryController",
                     recomputation_work_kind="WorkKind.RECOMPUTE",
                     output_progress_field="InferenceRequest.output_generated",
                     proving_test_file=r"tests\test_phase_7_preemption.py::test_pressure_preempts_rebuilds_and_preserves_output")
    assert evaluate_preemption_v4(answer) == ()
    assert _evaluate(TASK, tmp_path, answer, (), (), (), 0, 0)[0]
    assert not _evaluate(TASK, tmp_path, answer, (), (), (" M file.py",), 0, 1)[0]


@pytest.mark.parametrize(("field", "wrong"), [
    ("recomputation_work_kind", "InferenceRequest.apply_recompute"),
    ("recomputation_work_kind", "SimulationEngine._execute"),
    ("recomputation_work_kind", "scheduler.py"),
    ("recomputation_work_kind", "recomputation"),
    ("recomputation_work_kind", "WorkKind.RECOMPUTE_extra"),
    ("recomputation_work_kind", "WorkKind.RECOMPUTE; apply_recompute"),
    ("output_progress_field", "InferenceRequest.mark_preempted"),
    ("output_progress_field", "InferenceRequest.apply_decode"),
    ("output_progress_field", "test_pressure_preempts_rebuilds_and_preserves_output"),
    ("output_progress_field", "output preservation"),
    ("output_progress_field", "InferenceRequest.output_generated and output_token_times_ms"),
    ("victim_selection_policy", "MemoryController"),
    ("victim_selection_policy", "choose_victim"),
    ("memory_control_component", "KVBlockManager.release_request"),
    ("proving_test_file", "../tests/test_phase_7_preemption.py"),
    ("proving_test_file", "tests/test_unrelated_preemption.py"),
])
def test_v4_wrong_layer_and_malformed_values_fail(field: str, wrong: str) -> None:
    assert f"incorrect structured field: {field}" in evaluate_preemption_v4(_answer(**{field: wrong}))
    assert f"incorrect structured field: {field}" in evaluate_preemption_v4(_answer(
        **{field: wrong, "explanation": "RECOMPUTE and output_generated are correct identifiers."}))


@pytest.mark.parametrize("message", ["not json", "[]", "{}", _answer(explanation=" "),
                                     _answer(recomputation_work_kind=None), _answer(extra="unexpected")])
def test_v4_requires_well_formed_fields_and_explanation(message: str) -> None:
    assert evaluate_preemption_v4(message)


def test_v4_version_mixing_rejected_before_external_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="different versions"):
        aggregate_report([{"task_id": "preemption-v3", "task_version": 3, "valid": False},
                          {"task_id": "preemption-v4", "task_version": 4, "valid": False}])
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner._codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    with pytest.raises(ValueError, match="different Task A versions"):
        run_suite(("preemption-v3", "preemption-v4"), repository_root=tmp_path, artifact_base=tmp_path)


@pytest.fixture(scope="module")
def pinned_pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    return prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-v4") / "pair",
                        "Use middleman_context with the concrete engineering request.\n")


def test_pinned_v4_source_contract(pinned_pair: tuple[Path, Path, str]) -> None:
    baseline, optimized, fingerprint = pinned_pair
    assert source_fingerprint(baseline) == source_fingerprint(optimized) == fingerprint
    assert not (baseline / "AGENTS.md").exists() and (optimized / "AGENTS.md").exists()
    for root in (baseline, optimized):
        assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                                  check=True, capture_output=True, text=True).stdout
    def source(path: str) -> str:
        return (baseline / path).read_text(encoding="utf-8")
    policy = ast.parse(source("middle_man/lab/preemption.py"))
    assert any(isinstance(node, ast.ClassDef) and node.name == EXPECTED["victim_selection_policy"]
               and any(isinstance(child, ast.FunctionDef) and child.name == "choose_victim" for child in node.body)
               for node in policy.body)
    controller = ast.parse(source("middle_man/lab/memory_control.py"))
    assert any(isinstance(node, ast.ClassDef) and node.name == EXPECTED["memory_control_component"]
               and any(isinstance(child, ast.FunctionDef) and child.name == "prepare" for child in node.body)
               for node in controller.body)
    assert "self.memory.release_request(victim.request_id)" in source("middle_man/lab/memory_control.py")
    scheduler = source("middle_man/lab/scheduler.py")
    assert "request.state == RequestState.PREEMPTED and request.recompute_pending_tokens" in scheduler
    assert "candidates.append((request, WorkKind.RECOMPUTE, request.recompute_pending_tokens))" in scheduler
    assert "RECOMPUTE =" in source("middle_man/lab/work.py")
    request = ast.parse(source("middle_man/lab/request.py"))
    req = next(node for node in request.body if isinstance(node, ast.ClassDef) and node.name == "InferenceRequest")
    assert any(isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
               and node.target.id == EXPECTED["output_progress_field"] for node in req.body)
    mark = next(node for node in req.body if isinstance(node, ast.FunctionDef) and node.name == "mark_preempted")
    assert "output_generated" not in ast.get_source_segment(source("middle_man/lab/request.py"), mark)
    assert "self.output_generated += tokens" in source("middle_man/lab/request.py")
    proving = source(EXPECTED["proving_test_file"])
    assert "def test_pressure_preempts_rebuilds_and_preserves_output" in proving
    assert "victim.recomputed_tokens > 0" in proving
    assert "victim.output_generated == victim.max_output_tokens" in proving


def _delivered(data: dict) -> tuple[tuple[str, int, int, str], ...]:
    return tuple((item["path"], item["start_line"], item["end_line"], item["text"])
                 for item in data["excerpts"])


async def _stdio(root: Path) -> dict:
    params = StdioServerParameters(command=sys.executable,
                                   args=_server_args(root, run_id="local-v4-parity", task_id=TASK.id,
                                                     mode="optimized"))
    async with Client(params, raise_exceptions=True, read_timeout_seconds=30) as client:
        result = await client.call_tool("middleman_context", {
            "task": TASK.prompt, "mode": "balanced", "max_context_tokens": 6000})
        assert not result.is_error
        return result.structured_content


def test_v4_local_recall_and_direct_gateway_stdio_parity(pinned_pair: tuple[Path, Path, str]) -> None:
    _, root, _ = pinned_pair
    config = GatewayConfig(root)
    pack = ContextBuilder(config).build(TASK.prompt, mode="balanced", max_context_tokens=6000)
    recall = measure_required_source(pack, TASK_A_V3_UNITS)
    assert recall.required_file_recall == recall.required_symbol_recall == 1.0
    assert pack.metrics.estimated_selected_tokens <= 6000
    gateway = MCPGateway(config, benchmark_identity=BenchmarkIdentity(
        "local-v4-parity", TASK.id, "optimized", TASK_A_SOURCE_COMMIT)).context(
            TASK.prompt, mode="balanced", max_context_tokens=6000)
    stdio = asyncio.run(_stdio(root))
    expected = tuple((item.path, item.start_line, item.end_line, item.text) for item in pack.excerpts)
    for result in (gateway, stdio):
        assert result["fingerprint"] == pack.fingerprint
        assert _delivered(result) == expected
        assert result["metrics"]["selected_tokens"] == pack.metrics.estimated_selected_tokens
        assert result["warnings"] == list(pack.warnings)
    print("V4_LOCAL", json.dumps({"files": recall.required_file_recall, "identifiers": recall.required_symbol_recall,
                                  "selected_tokens": pack.metrics.estimated_selected_tokens,
                                  "pack_fingerprint": pack.fingerprint}))


def test_v4_expected_metadata_does_not_enter_production_selector() -> None:
    for relative in ("middle_man/gateway/relevance.py", "middle_man/gateway/selection.py",
                     "middle_man/gateway/context_builder.py", "middle_man/mcp/gateway.py",
                     "middle_man/mcp/server.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "preemption_v4" not in text and "TASK_A_V3_UNITS" not in text
