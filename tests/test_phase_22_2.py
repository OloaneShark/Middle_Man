from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark.preemption_v3 import (
    EXPECTED, TASK_A_V3_UNITS, evaluate_preemption_v3, measure_required_source,
)
from middle_man.gateway.codex_benchmark.runner import (
    _evaluate, aggregate_report, evaluate_preemption_v2, run_suite,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.quality import run_context_benchmarks
from middle_man.gateway.relevance import RelevanceEngine, lexical_family
from middle_man.mcp.gateway import MCPGateway
from middle_man.mcp.surface import measure_tool_surface


def _answer(**overrides: str) -> str:
    return json.dumps({**EXPECTED, "explanation": "The state and output remain intact.", **overrides})


def test_historical_versions_remain_exact_and_separate(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {task.id: task.schema_version for task in TASKS}
    assert versions["preemption"] == 1
    assert versions["preemption-v2"] == 2
    assert versions["preemption-v3"] == 3
    assert not evaluate_preemption_v2(_answer(victim_selection_symbol="module.LargestPrivateOwnerPolicy")) == ()
    assert "LargestPrivateOwnerPolicy" not in next(task.prompt for task in TASKS if task.id == "preemption-v3")
    with pytest.raises(ValueError, match="different versions"):
        aggregate_report([{"task_id": "preemption-v2", "task_version": 2, "valid": False},
                          {"task_id": "preemption-v3", "task_version": 3, "valid": False}])
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner._codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    with pytest.raises(ValueError, match="different Task A versions"):
        run_suite(("preemption-v2", "preemption-v3"), repository_root=tmp_path, artifact_base=tmp_path)


def test_v3_qualified_identifiers_and_test_paths(tmp_path: Path) -> None:
    answer = _answer(
        victim_selection_symbol="middle_man.lab.preemption.LargestPrivateOwnerPolicy",
        memory_control_symbol="MemoryController.ensure_capacity; KVBlockManager.release_request",
        recomputation_symbol="WorkKind.RECOMPUTE",
        output_preservation_symbol="InferenceRequest.output_generated",
        test_file=r"tests\test_phase_7_preemption.py::test_preemption_preserves_output",
    )
    assert evaluate_preemption_v3(answer) == ()
    task = next(task for task in TASKS if task.id == "preemption-v3")
    passed, notes, _, _ = _evaluate(task, tmp_path, answer, (), (), (), 0, 0)
    assert passed and not notes
    assert not _evaluate(task, tmp_path, answer, (), (), (" M file.py",), 0, 1)[0]


@pytest.mark.parametrize(("field", "wrong"), [
    ("victim_selection_symbol", "NotLargestPrivateOwnerPolicy"),
    ("memory_control_symbol", "SomeOtherController"),
    ("recomputation_symbol", "RECOMPUTED_VALUE"),
    ("output_preservation_symbol", "generated_output"),
    ("victim_selection_symbol", "the LargestPrivateOwnerPolicy class"),
    ("test_file", "tests/test_unrelated_preemption.py"),
    ("test_file", "../tests/test_phase_7_preemption.py"),
])
def test_v3_rejects_false_substrings_and_prose(field: str, wrong: str) -> None:
    assert f"incorrect structured field: {field}" in evaluate_preemption_v3(_answer(**{field: wrong}))


def test_generic_lexical_family_is_bounded_and_exact_evidence_wins(tmp_path: Path) -> None:
    assert lexical_family("recomputation", "recompute")
    assert lexical_family("preemption", "preempt")
    assert lexical_family("preservation", "preserve")
    assert not lexical_family("state", "status")
    assert not lexical_family("recomputation", "recommendation")
    (tmp_path / "recompute.py").write_text("def recompute():\n    return True\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("class Recomputation:\n    pass\n", encoding="utf-8")
    config = GatewayConfig(tmp_path)
    ranked = RelevanceEngine(RepositoryIndexer(config).index(), config).find("Recomputation", top_k=10)
    assert ranked[0].path == "other.py"
    assert any("lexical family" in reason for candidate in ranked for reason in candidate.reasons)
    assert any("recomputation" in candidate.matched_terms for candidate in ranked)


def test_task_a_v3_local_recall_and_diagnostics() -> None:
    root = Path(__file__).resolve().parents[1]
    task = next(task for task in TASKS if task.id == "preemption-v3")
    pack = ContextBuilder(GatewayConfig(root)).build(task.prompt, mode="balanced", max_context_tokens=6000)
    recall = measure_required_source(pack)
    assert len(TASK_A_V3_UNITS) == 7
    assert recall.required_file_recall == recall.required_symbol_recall == 1.0
    assert recall.selected_source_tokens <= 6000
    assert recall.selected_required_source_tokens + recall.selected_non_required_source_tokens == recall.selected_source_tokens
    assert all(unit.path in pack.selected_files for unit in TASK_A_V3_UNITS)
    assert any(not item.selected and item.omission_reason for item in pack.selection_diagnostics)
    assert all(item.estimated_source_cost >= 0 and item.budget_before >= 0 for item in pack.selection_diagnostics)
    assert any(item.covered_signals for item in pack.selection_diagnostics if item.selected)


def test_three_unrelated_coverage_fixtures_preserve_unique_support() -> None:
    results = run_context_benchmarks(mode="balanced", max_context_tokens=900, cases=coverage_cases())
    assert {item.name for item in results} == {"auth-callback", "queue-cancellation", "upload-validation"}
    assert all(item.success and item.required_file_recall == item.required_symbol_recall == 1.0
               and item.irrelevant_files_included == 0 and item.selected_estimated_tokens <= 900
               for item in results)


def test_phase_15_quality_recall_not_reduced() -> None:
    results = run_context_benchmarks()
    assert all(item.success and item.required_file_recall == item.required_symbol_recall == 1.0
               for item in results)


def test_core_payload_omits_diagnostics_and_keeps_five_tools(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def validate_state():\n    return True\n", encoding="utf-8")
    config = GatewayConfig(tmp_path)
    pack = ContextBuilder(config).build("validate_state", mode="balanced", max_context_tokens=600)
    assert pack.selection_diagnostics
    full = MCPGateway(config).context_pack("validate_state", max_context_tokens=600)
    assert full["selection_diagnostics"]
    core = MCPGateway(config).context("validate_state", max_context_tokens=600)
    assert "selection_diagnostics" not in json.dumps(core)
    surface = asyncio.run(measure_tool_surface(config, "codex-core"))
    assert surface.tool_count == 5 and surface.total_definition_tokens <= 900
    guidance = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    assert "middleman_context" in guidance and "middleman_find_context" not in guidance

def test_direct_test_and_one_hop_graph_are_bounded(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "core.py").write_text(
        "from app.helper import assist\nclass RootController:\n    def run(self): return assist()\n",
        encoding="utf-8")
    (tmp_path / "app" / "helper.py").write_text(
        "from app.deep import deep\ndef assist(): return deep()\n", encoding="utf-8")
    (tmp_path / "app" / "deep.py").write_text("def deep(): return True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import RootController\ndef test_root_controller(): assert RootController().run()\n",
        encoding="utf-8")
    config = GatewayConfig(tmp_path)
    query = "Prove RootController behavior with tests"
    ranked = RelevanceEngine(RepositoryIndexer(config).index(), config).find(query, top_k=20)
    paths = {item.path for item in ranked}
    assert "app/core.py" in paths and "app/helper.py" in paths and "tests/test_core.py" in paths
    assert "app/deep.py" not in paths
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=500)
    assert "tests/test_core.py" in pack.selected_files
    assert "app/helper.py" in pack.selected_files


def test_v3_invocation_schema_is_versioned_without_running_codex(tmp_path: Path) -> None:
    from middle_man.gateway.codex_benchmark.runner import build_invocation

    task = next(task for task in TASKS if task.id == "preemption-v3")
    baseline = build_invocation("codex", task, "baseline", tmp_path, model="gpt-6-sol", effort="high")
    optimized = build_invocation("codex", task, "optimized", tmp_path, model="gpt-6-sol", effort="high")
    assert baseline[baseline.index("--output-schema") + 1] == optimized[optimized.index("--output-schema") + 1]
    assert "--ignore-user-config" in baseline and "--ignore-user-config" in optimized
