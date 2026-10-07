"""Deterministic pre-run locator quality signals, with no Codex process."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

from middle_man.gateway.locator_diagnostics import diagnose_locator
from middle_man.gateway.models import (
    IndexStats, IndexedFile, Relationship, RepositoryIdentity, RepositoryIndex, Symbol,
)
from middle_man.gateway.relevance import ContextQuery, MatchSignal, RelevanceCandidate, WEIGHTS
from middle_man.gateway.selection import SelectedRangePhase, SelectionDiagnostic


def _index(paths: tuple[str, ...], relationships: tuple[Relationship, ...] = (),
           symbols: dict[str, tuple[str, ...]] | None = None) -> RepositoryIndex:
    files = tuple(IndexedFile(
        path=path, filename=PurePosixPath(path).name, extension=".py", language="Python",
        size_bytes=30, sha256=None, mtime_ns=0, line_count=3, is_text=True,
        is_test=PurePosixPath(path).name.startswith("test_"), parse_status="parsed",
        symbols=tuple(Symbol(path, name, name, "function", 1)
                      for name in (symbols or {}).get(path, ())),
    ) for path in paths)
    identity = RepositoryIdentity("/synthetic", "synthetic", False, None, None, "fixed")
    return RepositoryIndex(identity, files, relationships, IndexStats())


def _candidate(path: str, score: float, role: str,
               signals: tuple[tuple[str, str], ...]) -> RelevanceCandidate:
    values = tuple(MatchSignal(kind, f"term:{term}" if term else f"{kind}:{path}",
                               WEIGHTS[kind], kind, term) for kind, term in signals)
    return RelevanceCandidate(path, score, role, (), tuple(value.reason for value in values),
                              tuple(sorted({value.term for value in values if value.term})), values)


def _diagnostic(candidate: RelevanceCandidate, phase: str,
                covered: tuple[str, ...] = ()) -> SelectionDiagnostic:
    return SelectionDiagnostic(
        candidate.path, candidate.score, candidate.role, candidate.matched_terms,
        candidate.matched_symbols, candidate.reasons, ((1, 3, "symbol"),), 20, True,
        None, 0, covered, selected_range_phases=(SelectedRangePhase(1, 3, phase, 20),),
    )


def _pack(query: str, candidates: tuple[RelevanceCandidate, ...],
          diagnostics: tuple[SelectionDiagnostic, ...], paths: tuple[str, ...]):
    return SimpleNamespace(
        query=ContextQuery(query), candidates=candidates, selection_diagnostics=diagnostics,
        selected_files=paths,
        metrics=SimpleNamespace(estimated_raw_candidate_tokens=1000,
                                estimated_selected_tokens=100),
    )


def test_mixed_direct_weak_graph_test_and_phase_metrics_are_deterministic() -> None:
    paths = ("src/runner.py", "src/controller.py", "src/routing.py",
             "tests/test_controller.py", "src/helper.py")
    candidates = (
        _candidate(paths[0], 130, "PRIMARY", (("explicit_path", ""), ("filename_term", "runner"))),
        _candidate(paths[1], 110, "PRIMARY", (("exact_symbol", ""), ("symbol_term", "controller"))),
        _candidate(paths[2], 8, "PRIMARY", (("family_term", "routing"),)),
        _candidate(paths[3], 12, "RELATED", (("related_test", ""),)),
        _candidate(paths[4], 13, "RELATED", (("import_neighbor", ""),)),
    )
    phases = ("COVERAGE", "REQUIRED", "DEPTH", "REPAIR", "DEPTH")
    covered = (("fileterm:runner:source",), ("term:controller",), (), (), ())
    diagnostics = tuple(_diagnostic(candidate, phase, keys)
                        for candidate, phase, keys in zip(candidates, phases, covered))
    graph = (Relationship(paths[4], paths[0], "IMPORTS"),
             Relationship(paths[3], paths[1], "TESTS"))
    pack = _pack("runner controller routing", candidates, diagnostics, paths)
    index = _index(paths, graph)

    report = diagnose_locator(pack, index, locator_tokens=20)
    assert report == diagnose_locator(pack, index, locator_tokens=20)
    assert json.dumps(report, sort_keys=True) == json.dumps(
        diagnose_locator(pack, index, locator_tokens=20), sort_keys=True)
    assert report["direct_evidence_paths"] == 2
    assert report["direct_evidence_ratio"] == 0.4
    assert report["weak_only_paths"] == 3
    assert report["graph_expanded_related_paths"] == 2
    assert report["primary_selected_path_count"] == 3
    assert report["related_selected_path_count"] == 2
    assert report["test_selected_path_count"] == 1
    assert report["selected_range_phase_counts"] == {
        "REQUIRED": 1, "COVERAGE": 1, "DEPTH": 2, "REPAIR": 1,
    }
    assert report["selected_paths_without_novel_query_terms"] == 3
    assert report["selected_matched_query_terms"] == ("controller", "routing", "runner")
    assert report["direct_supported_query_terms"] == ("controller", "runner")
    assert report["weak_only_supported_query_terms"] == ("routing",)
    assert report["selected_induced_graph_cluster_sizes"] == (2, 2, 1)
    assert report["selected_directory_count"] == 2
    assert report["selected_to_candidate_source_ratio"] == 0.1
    assert report["locator_to_selected_source_ratio"] == 0.2
    rows = report["selected_paths"]
    assert rows[0]["direct_signals"] == ("explicit_path", "filename_term")
    assert rows[1]["direct_signals"] == ("exact_symbol", "symbol_term")
    assert rows[2]["weak_signals"] == ("family_term",)
    assert rows[3]["is_test"] and rows[3]["graph_signals"] == ("related_test",)
    assert rows[4]["role"] == "RELATED" and rows[4]["graph_signals"] == ("import_neighbor",)


def test_dispersed_paths_are_separate_without_import_or_test_edges() -> None:
    paths = ("alpha/one.py", "beta/two.py", "gamma/three.py")
    candidates = tuple(_candidate(path, 40, "PRIMARY", (("filename_term", term),))
                       for path, term in zip(paths, ("one", "two", "three")))
    diagnostics = tuple(_diagnostic(candidate, "COVERAGE", (f"term:{term}",))
                        for candidate, term in zip(candidates, ("one", "two", "three")))
    report = diagnose_locator(_pack("one two three", candidates, diagnostics, paths),
                              _index(paths), locator_tokens=10)
    assert report["selected_directory_count"] == 3
    assert report["directory_dispersion"] == 1.0
    assert report["selected_induced_graph_cluster_sizes"] == (1, 1, 1)
    assert report["selected_score_within_top_fraction"] == {
        "50_percent": 1.0, "75_percent": 1.0, "90_percent": 1.0,
    }


def test_empty_selection_has_zero_ratios_and_no_paths() -> None:
    report = diagnose_locator(_pack("no matches", (), (), ()), _index(()), locator_tokens=0)
    assert report["selected_path_count"] == 0
    assert report["candidate_path_count"] == 0
    assert report["direct_evidence_ratio"] == 0.0
    assert report["useful_query_term_coverage_ratio"] == 0.0
    assert report["selected_induced_graph_cluster_count"] == 0
    assert report["selected_paths"] == ()
    with pytest.raises(ValueError, match="nonnegative"):
        diagnose_locator(_pack("no matches", (), (), ()), _index(()), locator_tokens=-1)


def test_repeated_exact_symbols_are_distinguished_from_unique_evidence() -> None:
    paths = ("src/owner.py", "tests/test_one.py", "tests/test_two.py")
    index = _index(paths, symbols={
        paths[0]: ("SpecificPolicy",), paths[1]: ("TASK",), paths[2]: ("TASK",),
    })
    candidates = tuple(RelevanceCandidate(
        path, 95, "PRIMARY", (), (f"exact symbol: {name}",), (),
        (MatchSignal("exact_symbol", f"symbol:{name}", 95, "exact symbol", None),),
    ) for path, name in zip(paths, ("SpecificPolicy", "TASK", "TASK")))
    diagnostics = tuple(_diagnostic(candidate, "REQUIRED") for candidate in candidates)
    report = diagnose_locator(_pack("SpecificPolicy TASK", candidates, diagnostics, paths),
                              index, locator_tokens=12)
    assert report["direct_evidence_ratio"] == 1.0
    assert report["unique_exact_symbol_paths"] == 1
    assert report["ambiguous_only_exact_symbol_paths"] == 2
    assert report["exact_symbol_path_frequency"] == {"SpecificPolicy": 1, "TASK": 2}
    assert report["selected_paths"][0]["unique_exact_symbols"] == ("SpecificPolicy",)
    assert report["selected_paths"][1]["ambiguous_exact_symbols"] == ("TASK",)
