"""Offline candidate-only experiment; production selection is not modified."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from middle_man.experiments.source_selection import (
    _code_identifiers, code_anchor_candidates,
)
from middle_man.gateway.locator_shadow import ARCHETYPES, load_shadow_corpus
from middle_man.gateway.relevance import ContextQuery, MatchSignal, RelevanceCandidate
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint
from scripts.evaluate_source_selection_shadow import EXPERIMENT_PATH, RESULT_PATH, evaluate
from scripts.measure_locator_shadow_corpus import CORPUS_PATH, SELECTOR_FINGERPRINT


ROOT = Path(__file__).resolve().parents[1]


class FixedEngine:
    def __init__(self, candidates: tuple[RelevanceCandidate, ...]) -> None:
        self.candidates = candidates

    def find(self, _query: ContextQuery, *, top_k: int) -> tuple[RelevanceCandidate, ...]:
        return self.candidates[:top_k]


def _candidate(path: str, *signals: MatchSignal) -> RelevanceCandidate:
    return RelevanceCandidate(path, sum(signal.weight for signal in signals), "PRIMARY", (),
                              tuple(signal.reason for signal in signals),
                              tuple(sorted(signal.term for signal in signals if signal.term)),
                              signals)


def test_plain_prose_symbol_does_not_displace_source_candidate() -> None:
    prose = _candidate(
        "tests/test_cli.py",
        MatchSignal("exact_symbol", "symbol:CLI", 95, "exact symbol: CLI"),
        MatchSignal("filename_term", "term:cli", 28, "filename term: cli", "cli"))
    source = _candidate("src/runner.py", MatchSignal(
        "filename_term", "term:runner", 60, "filename term: runner", "runner"))
    index = SimpleNamespace(files=(object(), object()))
    query = ContextQuery("Trace CLI runner behavior")
    selected = code_anchor_candidates(index, FixedEngine((prose, source)), query, 2)
    assert _code_identifiers(query) == set()
    assert [item.path for item in selected] == ["src/runner.py", "tests/test_cli.py"]
    assert selected[1].score == 28
    assert not any(signal.kind == "exact_symbol" for signal in selected[1].signals)


def test_explicit_symbol_path_and_code_shaped_identifiers_keep_exact_match() -> None:
    exact = MatchSignal("exact_symbol", "symbol:CLI", 95, "exact symbol: CLI")
    path = MatchSignal("explicit_path", "path:tests/test_cli.py", 120,
                       "explicit path: tests/test_cli.py")
    code = MatchSignal("exact_symbol", "symbol:build_offline_locator", 95,
                       "exact symbol: build_offline_locator")
    index = SimpleNamespace(files=(object(),))
    engine = FixedEngine((_candidate("tests/test_cli.py", exact),))
    assert code_anchor_candidates(index, engine, ContextQuery("CLI", symbols=("CLI",)), 1)[0].score == 95
    assert code_anchor_candidates(index, FixedEngine((_candidate("tests/test_cli.py", exact, path),)),
                                  ContextQuery("CLI", paths=("tests/test_cli.py",)), 1)[0].score == 215
    assert code_anchor_candidates(index, FixedEngine((_candidate("src/locator.py", code),)),
                                  ContextQuery("Trace build_offline_locator"), 1)[0].score == 95
    assert "RepositoryIndexer.index" in _code_identifiers(ContextQuery("Trace RepositoryIndexer.index"))


def test_report_covers_all_frozen_tasks_without_ground_truth_invention() -> None:
    report = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    corpus = load_shadow_corpus(CORPUS_PATH)
    assert report["status"] == "OFFLINE_SHADOW_COMPARISON_NOT_PRODUCTION_POLICY"
    assert report["source_commit"] == corpus["source_commit"]
    assert report["source_tree"] == corpus["source_tree_sha"]
    assert report["budget"] == corpus["max_context_tokens"] == 6000
    assert report["production_selector_fingerprint"] == selector_implementation_fingerprint() == SELECTOR_FINGERPRINT
    assert report["experiment_implementation_sha256"] == hashlib.sha256(EXPERIMENT_PATH.read_bytes()).hexdigest()
    assert report["task_count"] == len(report["tasks"]) == len(corpus["tasks"]) == 24
    assert set(report["archetypes"]) == ARCHETYPES
    assert all(report["archetypes"][name]["tasks"] == 4 for name in ARCHETYPES)
    assert [(row["task_id"], row["task_sha256"], row["archetype"])
            for row in report["tasks"]] == [
                (task["task_id"], task["sha256"], task["archetype"])
                for task in corpus["tasks"]]
    assert "ground-truth" in report["interpretation_limit"]
    for row in report["tasks"]:
        left, right = row["current"], row["candidate"]
        for side in (left, right):
            assert len(side["top_candidate_paths"]) == min(10, side["candidate_path_count"])
            assert side["candidate_path_count"] <= 50
            assert len(set(side["top_candidate_paths"])) == len(side["top_candidate_paths"])
            assert side["selected_source_tokens_estimate"] <= 6000
            assert side["test_selected_path_count"] + side["non_test_selected_path_count"] == len(side["selected_paths"])
            assert sum(side["selected_induced_graph_cluster_sizes"]) == len(side["selected_paths"])
        assert row["added_paths"] == sorted(set(right["selected_paths"]) - set(left["selected_paths"]))
        assert row["removed_paths"] == sorted(set(left["selected_paths"]) - set(right["selected_paths"]))


def test_m01_reproduction_and_negative_cross_archetype_checks() -> None:
    report = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    case = report["archived_m01_case"]
    receipt = json.loads((ROOT / "docs/codex_variance_calibration_v2_receipts/call-2.json")
                         .read_text(encoding="ascii"))
    assert case["archived_selected_paths_reproduced"] is True
    assert case["archived_locator_hash"] == receipt["locator"]["locator_hash"]
    assert case["comparison"]["current"]["selected_paths"] == receipt["locator"]["selected_paths"]
    assert len(case["current_reference_paths_selected"]) == 2
    assert len(case["candidate_reference_paths_selected"]) == 4
    current = {row["path"]: row for row in case["path_diagnostics"] if row["selector"] == "current"}
    ambiguous_tests = [row for row in current.values() if row["is_test"] and row["selected"]
                       and any(count > 1 for count in row["exact_symbol_path_frequency"].values())]
    assert ambiguous_tests and all(row["covered_signals"] for row in ambiguous_tests)
    omitted_refs = [current[path] for path in case["source_grounded_reference_paths"]
                    if path in current and not current[path]["selected"]]
    budget_omitted = [row for row in omitted_refs if row["omission_reason"] == "context_budget"]
    assert len(budget_omitted) >= 2
    assert all(row["within_candidate_cap"] and row["budget_before"] == 5999
               and row["proposed_source_cost"] > 1 and row["proposed_source_ranges"]
               for row in budget_omitted)
    assert any(not row["within_candidate_cap"] for row in omitted_refs)
    tasks = {row["task_id"]: row for row in report["tasks"]}
    for task_id in ("N01", "N02", "N03", "E01", "E02", "E03"):
        assert tasks[task_id]["current"]["selected_paths"] == tasks[task_id]["candidate"]["selected_paths"]
    for task_id in ("T01", "T03"):
        row = tasks[task_id]
        assert row["candidate"]["test_selected_path_count"] < row["current"]["test_selected_path_count"]
        assert len(row["candidate"]["direct_supported_query_terms"]) < len(
            row["current"]["direct_supported_query_terms"])


def test_full_shadow_result_recomputes_from_pinned_sources() -> None:
    assert evaluate() == json.loads(RESULT_PATH.read_text(encoding="utf-8"))
