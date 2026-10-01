from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark.preemption_v3 import TASK_A_V3_UNITS, measure_required_source
from middle_man.gateway.codex_benchmark.runner import aggregate_report, format_report, pair_input_diagnostics
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.selection import allocate
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.gateway import MCPGateway


TASK = next(task for task in TASKS if task.id == "preemption-v4")
REAL_QUERY = (
    "Explain KV preemption in this repository: identify victim selection policy implementation class, "
    "controller coordinating KV allocation and release, scheduler WorkKind for preempted requests, "
    "InferenceRequest generated-output field preserved, and proving test file; trace interactions and "
    "KV block release. Read only, no changes."
)
LIMITS = (None, 0, 250, 500, 750, 1000, 1500, 2000)


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-8") / "pair", "guidance\n")
    return optimized


def _phase_tokens(pack: object) -> Counter[str]:
    return Counter({phase: sum(item.estimated_source_tokens
                               for diagnostic in pack.selection_diagnostics
                               for item in diagnostic.selected_range_phases if item.phase == phase)
                    for phase in ("REQUIRED", "COVERAGE", "DEPTH", "REPAIR")})


def _concepts(pack: object) -> tuple[bool, ...]:
    text_by_path: dict[str, str] = {}
    for item in pack.excerpts:
        text_by_path[item.path] = text_by_path.get(item.path, "") + item.text
    return (
        "LargestPrivateOwnerPolicy" in text_by_path.get("middle_man/lab/preemption.py", ""),
        "class MemoryController" in text_by_path.get("middle_man/lab/memory_control.py", ""),
        "RECOMPUTE =" in text_by_path.get("middle_man/lab/work.py", ""),
        "output_generated:" in text_by_path.get("middle_man/lab/request.py", ""),
        "def test_pressure_preempts_rebuilds_and_preserves_output" in text_by_path.get(
            "tests/test_phase_7_preemption.py", ""),
    )


def _release_evidence(pack: object) -> bool:
    return any((item.path == "middle_man/lab/memory.py" and "def release_request" in item.text) or
               (item.path == "middle_man/lab/memory_control.py" and
                "self.memory.release_request(victim.request_id)" in item.text)
               for item in pack.excerpts)


@pytest.mark.parametrize(("query", "expected_tokens", "expected_recall", "expected_phases"), [
    (TASK.prompt, 5983, 7, {"REQUIRED": 1693, "COVERAGE": 4222, "DEPTH": 23, "REPAIR": 45}),
    (REAL_QUERY, 5949, 6, {"REQUIRED": 1693, "COVERAGE": 3705, "DEPTH": 261, "REPAIR": 290}),
])
def test_default_balanced_phase_attribution_and_fingerprint_stability(
        pinned: Path, query: str, expected_tokens: int, expected_recall: int,
        expected_phases: dict[str, int]) -> None:
    builder = ContextBuilder(GatewayConfig(pinned))
    control = builder.build(query, mode="balanced", max_context_tokens=6000)
    explicit_none = builder.build(query, mode="balanced", max_context_tokens=6000,
                                  depth_token_limit=None)
    assert control.fingerprint == explicit_none.fingerprint
    assert control.excerpts == explicit_none.excerpts
    assert control.metrics.estimated_selected_tokens == expected_tokens
    assert dict(_phase_tokens(control)) == expected_phases
    assert sum(_phase_tokens(control).values()) == expected_tokens
    recall = measure_required_source(control, TASK_A_V3_UNITS)
    assert round(recall.required_file_recall * 7) == expected_recall
    assert round(recall.required_symbol_recall * 7) == expected_recall
    assert all(_concepts(control)) and _release_evidence(control)


@pytest.mark.parametrize(("query", "expected_tokens", "expected_recall"), [
    (TASK.prompt, (5983, 5921, 5983, 5983, 5983, 5983, 5983, 5983), 7),
    (REAL_QUERY, (5949, 5404, 5916, 5888, 5949, 5949, 5949, 5949), 6),
])
def test_local_depth_sweep_keeps_explicit_v4_concepts_and_release(
        pinned: Path, query: str, expected_tokens: tuple[int, ...], expected_recall: int) -> None:
    builder = ContextBuilder(GatewayConfig(pinned))
    for limit, selected_tokens in zip(LIMITS, expected_tokens, strict=True):
        pack = builder.build(query, mode="balanced", max_context_tokens=6000, depth_token_limit=limit)
        recall = measure_required_source(pack, TASK_A_V3_UNITS)
        assert pack.metrics.estimated_selected_tokens == selected_tokens
        assert round(recall.required_file_recall * 7) == expected_recall
        assert round(recall.required_symbol_recall * 7) == expected_recall
        assert all(_concepts(pack)) and _release_evidence(pack)
        assert sum(_phase_tokens(pack).values()) == selected_tokens
    zero = builder.build(query, mode="balanced", max_context_tokens=6000, depth_token_limit=0)
    assert _phase_tokens(zero)["DEPTH"] == 0
    assert any(item.repair_candidate for item in zero.selection_diagnostics)


def test_shadow_depth_limit_is_local_and_core_payload_has_no_phase_metadata(pinned: Path) -> None:
    builder = ContextBuilder(GatewayConfig(pinned))
    pack = builder.build(REAL_QUERY, mode="balanced", max_context_tokens=6000, depth_token_limit=0)
    gateway = MCPGateway(GatewayConfig(pinned))
    core = gateway._core_payload(pack).data
    full = gateway._pack_payload(pack).data
    assert "selection_diagnostics" not in core
    assert "selected_range_phases" not in json.dumps(core)
    assert "selected_range_phases" not in json.dumps(full)
    assert "depth_token_limit" not in json.dumps(core)
    assert any(item.selected_range_phases for item in pack.selection_diagnostics)
    with pytest.raises(ValueError, match="nonnegative"):
        allocate((), 100, depth_token_limit=-1)
    assert "preemption_v4" not in (Path(__file__).resolve().parents[1] /
                                   "middle_man/gateway/selection.py").read_text(encoding="utf-8")


def test_zero_depth_is_not_robust_enough_for_a_named_lean_mode(pinned: Path) -> None:
    builder = ContextBuilder(GatewayConfig(pinned))
    styles = {
        "behavior": "Need context for victim selection, KV release, recomputation, and output preservation",
        "reordered": "For KV preemption, identify the proving preemption test and output preservation; "
                     "then explain recomputation scheduling, memory release and control, and victim selection",
        "agent": "Locate source and tests for KV preemption victim choice, memory release, the RECOMPUTE "
                 "work kind and scheduling path, and output_generated preservation",
        "short": "Find the KV preemption implementation and tests",
        "generic": "inspect the Middle_Man architecture",
    }
    results = {}
    for name, query in styles.items():
        control = builder.build(query, mode="balanced", max_context_tokens=6000)
        zero = builder.build(query, mode="balanced", max_context_tokens=6000, depth_token_limit=0)
        results[name] = (measure_required_source(control), measure_required_source(zero))
        assert zero.metrics.estimated_selected_tokens <= control.metrics.estimated_selected_tokens
    for name in ("behavior", "reordered", "agent"):
        assert results[name][0].required_file_recall == 1.0
        assert results[name][1].required_file_recall < 1.0
    assert results["short"][1].required_file_recall <= results["short"][0].required_file_recall < 1.0
    assert results["generic"][0].required_file_recall == results["generic"][1].required_file_recall == 0.0


@pytest.mark.parametrize("case", coverage_cases(), ids=lambda case: case.name)
def test_unrelated_depth_robustness_and_zero_limit_regression(tmp_path: Path, case: object) -> None:
    for path, source in case.files:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    config = GatewayConfig(tmp_path)
    builder = ContextBuilder(config)
    index = RepositoryIndexer(config).index()
    results = {}
    for limit in (None, 0, 250, 500, 750, 1000, 1500, 2000):
        pack = builder.build(case.query, mode="balanced", max_context_tokens=900,
                             top_k=10, depth_token_limit=limit)
        paths = {item.path for item in pack.excerpts}
        files = sum(path in paths for path in case.required_files)
        symbols = sum(any(item.path == symbol.path and item.start_line <= symbol.start_line and
                          item.end_line >= (symbol.end_line or symbol.start_line)
                          for symbol in index.find_symbol(name) for item in pack.excerpts)
                      for name in case.required_symbols)
        results[limit] = (files, symbols, pack.metrics.estimated_selected_tokens)
    assert results[None][:2] == (4, 4)
    assert all(results[limit][:2] == (4, 4) for limit in (250, 500, 750, 1000, 1500, 2000))
    assert results[0][:2] == ((3, 3) if case.name == "upload-validation" else (4, 4))


def test_result_size_uses_existing_core_serializer(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    builder = ContextBuilder(config)
    gateway = MCPGateway(config)
    estimator = HeuristicTokenEstimator()
    budget = {"requested_context_tokens": 6000, "effective_context_tokens": 6000,
              "benchmark_context_cap": 6000, "budget_capped": False, "force_replay": False}
    expected = ((TASK.prompt, (6913, 6764)), (REAL_QUERY, (7184, 6263)))
    for query, result_tokens in expected:
        for limit, expected_tokens in zip((None, 0), result_tokens, strict=True):
            pack = builder.build(query, mode="balanced", max_context_tokens=6000,
                                 depth_token_limit=limit)
            payload = {**gateway._core_payload(pack).data, "budget": budget}
            assert estimator.estimate(json.dumps(payload, ensure_ascii=False)) == expected_tokens


def test_correct_pair_input_diagnostics_are_descriptive_and_missing_safe() -> None:
    pair = {
        "valid": True,
        "baseline": {"correctness": True, "codex_reported_usage": {
            "input_tokens": 86143, "cached_input_tokens": 58368}},
        "optimized": {"correctness": True, "codex_reported_usage": {
            "input_tokens": 156138, "cached_input_tokens": 120320},
            "context": {"all_mcp_result_tokens": 7184, "selected_tokens": 5949}},
    }
    diagnostics = pair_input_diagnostics(pair)
    assert diagnostics == {
        "baseline_uncached_input_diagnostic": 27775,
        "optimized_uncached_input_diagnostic": 35818,
        "input_delta_diagnostic": 69995,
        "cached_input_delta_diagnostic": 61952,
        "uncached_input_delta_diagnostic": 8043,
        "optimized_mcp_result_tokens_estimate": 7184,
        "optimized_selected_source_tokens_estimate": 5949,
    }
    assert "billing" not in repr(diagnostics).lower() and "quota" not in repr(diagnostics).lower()
    assert pair_input_diagnostics({**pair, "valid": False}) is None
    assert pair_input_diagnostics({**pair, "optimized": {**pair["optimized"], "correctness": False}}) is None
    missing = pair_input_diagnostics({**pair, "baseline": {"correctness": True},
                                      "optimized": {"correctness": True, "context": {}}})
    assert missing is not None and all(value is None for value in missing.values())


def test_report_separates_native_reads_calls_mcp_and_observed_interactions() -> None:
    def run(mode: str) -> dict:
        baseline = mode == "baseline"
        return {
            "correctness": True, "correctness_notes": [], "test_exit_code": None,
            "native": {"tool_calls": 8 if baseline else 9, "file_reads": 7 if baseline else 3,
                       "rereads": 0, "unique_files": ["a.py"] * (7 if baseline else 3),
                       "search_calls": 1 if baseline else 3, "listing_calls": 0},
            "codex_reported_usage": {"input_tokens": 86143 if baseline else 156138,
                                     "cached_input_tokens": 58368 if baseline else 120320,
                                     "output_tokens": 634 if baseline else 1383,
                                     "reasoning_output_tokens": 116 if baseline else 459,
                                     "total_tokens": None},
            "mcp_calls_by_tool": [] if baseline else [["middleman_context", 1]],
            "context": {"overlap_available": True, "unique_source_bytes": 0 if baseline else 23770,
                        "repeated_source_bytes": 0, "pack_fingerprints": [] if baseline else ["pack"],
                        "selected_paths": [] if baseline else ["a.py"],
                        "candidate_tokens": 0 if baseline else 33552,
                        "selected_tokens": 0 if baseline else 5949,
                        "all_mcp_result_tokens": 0 if baseline else 7184,
                        "unique_source_tokens_estimate": 0 if baseline else 5943,
                        "repeated_source_tokens_estimate": 0,
                        "non_source_pack_overhead_estimate": 0 if baseline else 1241,
                        "overlap_ratio": None if baseline else 0.0},
            "mcp_session_trace": [], "native_read_mcp_coverage": [],
            "elapsed_seconds": 40.263 if baseline else 82.496, "modified_files": [],
        }

    pair = {"task_id": "preemption-v4", "title": "Task A", "task_version": 4,
            "quality_gate": "CORRECT_WITH_LESS_NATIVE_EXPLORATION", "valid": True,
            "baseline": run("baseline"), "optimized": run("optimized")}
    aggregate = aggregate_report([pair])
    assert (aggregate["baseline_native_tool_calls"], aggregate["optimized_native_tool_calls"]) == (8, 9)
    assert (aggregate["baseline_mcp_calls"], aggregate["optimized_mcp_calls"]) == (0, 1)
    assert (aggregate["baseline_observed_tool_interactions"],
            aggregate["optimized_observed_tool_interactions"]) == (8, 10)
    assert aggregate["correct_pair_input_diagnostics"][0]["input_delta_diagnostic"] == 69995
    report = format_report({"run_id": "local", "codex_version": "test", "model": "test",
                            "effort": "high", "pairs": [pair], "aggregate": aggregate})
    assert "Native tool calls: 8 -> 9" in report
    assert "Native reads: 7 -> 3" in report
    assert "Total observed tool interactions (native + MCP): 8 -> 10" in report
    assert "Codex input diagnostics (not billing or quota): input delta=69995" in report
