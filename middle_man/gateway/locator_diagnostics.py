"""Pre-run, source-free diagnostics for an already selected locator pack."""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
from statistics import median

from middle_man.gateway.context_models import ContextPack
from middle_man.gateway.models import RepositoryIndex
from middle_man.gateway.relevance import WEIGHTS, terms


DIRECT_SIGNALS = frozenset({
    "explicit_path", "trace_path", "exact_symbol", "filename_term", "symbol_term",
})
GRAPH_SIGNALS = frozenset({
    "import_neighbor", "reverse_import_neighbor", "related_test", "tested_source",
})
SIGNAL_KINDS = tuple(WEIGHTS)
SELECTION_PHASES = ("REQUIRED", "COVERAGE", "DEPTH", "REPAIR")


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _novel_terms(keys: tuple[str, ...], useful: set[str]) -> tuple[str, ...]:
    found = set()
    for key in keys:
        if key.startswith("term:"):
            term = key.removeprefix("term:")
        elif key.startswith("fileterm:"):
            term = key.split(":", 2)[1]
        else:
            continue
        if term in useful:
            found.add(term)
    return tuple(sorted(found))


def _selected_clusters(paths: tuple[str, ...], index: RepositoryIndex) -> tuple[int, ...]:
    selected = set(paths)
    adjacent = {path: set() for path in paths}
    for relation in index.relationships:
        if (relation.kind in {"IMPORTS", "TESTS"} and
                relation.source in selected and relation.target in selected):
            adjacent[relation.source].add(relation.target)
            adjacent[relation.target].add(relation.source)
    remaining = set(paths)
    sizes = []
    while remaining:
        frontier = {min(remaining)}
        component = set()
        while frontier:
            node = frontier.pop()
            if node in component:
                continue
            component.add(node)
            frontier.update(adjacent[node] - component)
        remaining.difference_update(component)
        sizes.append(len(component))
    return tuple(sorted(sizes, reverse=True))


def diagnose_locator(pack: ContextPack, index: RepositoryIndex, *,
                     locator_tokens: int) -> dict[str, object]:
    """Describe evidence quality without reading source or changing selection."""
    if locator_tokens < 0:
        raise ValueError("locator_tokens must be nonnegative")
    candidate_by_path = {candidate.path: candidate for candidate in pack.candidates}
    diagnostic_by_path = {item.candidate_path: item for item in pack.selection_diagnostics}
    selected_paths = pack.selected_files

    query_terms = terms(pack.query.task) | terms(pack.query.error_text)
    frequency = Counter(term for item in index.files
                        for term in terms(item.path) |
                        frozenset(term for symbol in item.symbols for term in terms(symbol.name)))
    useful = {term for term in query_terms
              if frequency[term] <= max(3, int(len(index.files) * 0.3))}

    path_rows: list[dict[str, object]] = []
    signal_counts = Counter()
    range_phases = Counter()
    path_phases = Counter()
    supported_terms: set[str] = set()
    direct_terms: set[str] = set()
    symbols: set[str] = set()
    direct_count = graph_expanded = weak_only = no_novel = 0
    unique_symbol_paths = ambiguous_only_symbol_paths = 0
    exact_symbol_names: set[str] = set()
    scores = []
    directories = Counter()
    for path in selected_paths:
        candidate = candidate_by_path.get(path)
        diagnostic = diagnostic_by_path.get(path)
        signals = candidate.signals if candidate else ()
        direct = tuple(sorted({signal.kind for signal in signals if signal.kind in DIRECT_SIGNALS}))
        graph = tuple(sorted({signal.kind for signal in signals if signal.kind in GRAPH_SIGNALS}))
        weak = tuple(sorted({signal.kind for signal in signals
                             if signal.kind not in DIRECT_SIGNALS | GRAPH_SIGNALS}))
        supported = {signal.term for signal in signals if signal.term and signal.term in useful}
        directly_supported = {signal.term for signal in signals
                              if signal.kind in DIRECT_SIGNALS and signal.term in useful}
        covered = diagnostic.covered_signals if diagnostic else ()
        novel = _novel_terms(covered, useful)
        phases = tuple(dict.fromkeys(item.phase for item in
                                     (diagnostic.selected_range_phases if diagnostic else ())))
        for phase in phases:
            path_phases[phase] += 1
        for item in diagnostic.selected_range_phases if diagnostic else ():
            range_phases[item.phase] += 1
        signal_counts.update(signal.kind for signal in signals)
        supported_terms.update(supported)
        direct_terms.update(directly_supported)
        if candidate:
            symbols.update(candidate.matched_symbols)
        if direct:
            direct_count += 1
        else:
            weak_only += 1
        if not novel:
            no_novel += 1
        role = candidate.role if candidate else diagnostic.role if diagnostic else "EXPANSION"
        if role == "RELATED" and graph and not direct:
            graph_expanded += 1
        score = candidate.score if candidate else diagnostic.candidate_score if diagnostic else 0.0
        scores.append(score)
        record = index.get_file(path)
        exact_names = tuple(sorted({signal.key.removeprefix("symbol:") for signal in signals
                                    if signal.kind == "exact_symbol" and
                                    signal.key.startswith("symbol:")}))
        symbol_frequencies = {name: len({symbol.path for symbol in index.find_symbol(name)})
                              for name in exact_names}
        unique_names = tuple(name for name in exact_names if symbol_frequencies[name] == 1)
        ambiguous_names = tuple(name for name in exact_names if symbol_frequencies[name] > 1)
        exact_symbol_names.update(exact_names)
        if unique_names:
            unique_symbol_paths += 1
        elif ambiguous_names:
            ambiguous_only_symbol_paths += 1
        directory = str(PurePosixPath(path).parent)
        directories[directory] += 1
        path_rows.append({
            "path": path,
            "role": role,
            "is_test": record.is_test if record else False,
            "candidate_score": score,
            "selection_phases": phases,
            "matched_terms": candidate.matched_terms if candidate else (),
            "matched_symbols": candidate.matched_symbols if candidate else (),
            "exact_symbol_path_frequency": symbol_frequencies,
            "unique_exact_symbols": unique_names,
            "ambiguous_exact_symbols": ambiguous_names,
            "direct_signals": direct,
            "weak_signals": weak,
            "graph_signals": graph,
            "candidate_reasons": candidate.reasons if candidate else (),
            "covered_signals": covered,
            "novel_query_terms": novel,
            "contributed_novel_query_term": bool(novel),
            "repair_reason": diagnostic.repair_reason if diagnostic else None,
            "omission_reason": diagnostic.omission_reason if diagnostic else None,
        })

    count = len(selected_paths)
    top_score = max((candidate.score for candidate in pack.candidates), default=0.0)
    candidate_tokens = pack.metrics.estimated_raw_candidate_tokens
    selected_tokens = pack.metrics.estimated_selected_tokens
    clusters = _selected_clusters(selected_paths, index)
    role_counts = Counter(row["role"] for row in path_rows)
    test_count = sum(bool(row["is_test"]) for row in path_rows)
    return {
        "candidate_source_tokens": candidate_tokens,
        "selected_source_tokens": selected_tokens,
        "locator_tokens": locator_tokens,
        "candidate_path_count": len(pack.candidates),
        "selected_path_count": count,
        "primary_selected_path_count": role_counts["PRIMARY"],
        "related_selected_path_count": role_counts["RELATED"],
        "test_selected_path_count": test_count,
        "non_test_selected_path_count": count - test_count,
        "selected_range_phase_counts": {name: range_phases[name] for name in SELECTION_PHASES},
        "selected_path_phase_counts": {name: path_phases[name] for name in SELECTION_PHASES},
        "query_terms": tuple(sorted(query_terms)),
        "useful_query_terms": tuple(sorted(useful)),
        "rare_query_terms": tuple(sorted(term for term in useful if 0 < frequency[term] <= 2)),
        "selected_matched_query_terms": tuple(sorted(supported_terms)),
        "selected_matched_symbols": tuple(sorted(symbols)),
        "unique_exact_symbol_paths": unique_symbol_paths,
        "ambiguous_only_exact_symbol_paths": ambiguous_only_symbol_paths,
        "exact_symbol_path_frequency": {
            name: len({symbol.path for symbol in index.find_symbol(name)})
            for name in sorted(exact_symbol_names)
        },
        "direct_supported_query_terms": tuple(sorted(direct_terms)),
        "weak_only_supported_query_terms": tuple(sorted(supported_terms - direct_terms)),
        "useful_query_term_coverage_ratio": _ratio(len(supported_terms), len(useful)),
        "direct_query_term_coverage_ratio": _ratio(len(direct_terms), len(useful)),
        "selected_paths_without_novel_query_terms": no_novel,
        "signal_counts": {name: signal_counts[name] for name in SIGNAL_KINDS},
        "direct_evidence_paths": direct_count,
        "direct_evidence_ratio": _ratio(direct_count, count),
        "weak_only_paths": weak_only,
        "weak_only_ratio": _ratio(weak_only, count),
        "graph_expanded_related_paths": graph_expanded,
        "graph_expanded_related_ratio": _ratio(graph_expanded, count),
        "top_candidate_score": top_score,
        "median_selected_candidate_score": median(scores) if scores else 0.0,
        "minimum_selected_candidate_score": min(scores, default=0.0),
        "selected_score_within_top_fraction": {
            "50_percent": _ratio(sum(score >= top_score * 0.5 for score in scores), count),
            "75_percent": _ratio(sum(score >= top_score * 0.75 for score in scores), count),
            "90_percent": _ratio(sum(score >= top_score * 0.9 for score in scores), count),
        },
        "selected_to_candidate_source_ratio": _ratio(selected_tokens, candidate_tokens),
        "locator_to_selected_source_ratio": _ratio(locator_tokens, selected_tokens),
        "selected_directory_count": len(directories),
        "directory_dispersion": _ratio(len(directories), count),
        "selected_directory_counts": dict(sorted(directories.items())),
        "selected_induced_graph_cluster_count": len(clusters),
        "selected_induced_graph_cluster_sizes": clusters,
        "selected_paths": tuple(path_rows),
    }
