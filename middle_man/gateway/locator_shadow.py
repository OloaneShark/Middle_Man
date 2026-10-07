"""Locked, unlabeled locator corpus and descriptive shadow statistics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


ARCHETYPES = frozenset({
    "NARROW_COMPONENT", "MULTI_COMPONENT_ARCHITECTURE", "CROSS_CUTTING_FEATURE",
    "TEST_FOCUSED", "GENERIC_BROAD", "EXPLICIT_ANCHOR",
})
TASK_KEYS = frozenset({
    "task_id", "task", "sha256", "archetype",
    "explicit_paths_supplied", "explicit_symbols_supplied",
})
TOP_LEVEL_FEATURES = (
    "candidate_source_tokens", "selected_source_tokens", "locator_tokens",
    "candidate_path_count", "selected_path_count", "primary_selected_path_count",
    "related_selected_path_count", "test_selected_path_count", "non_test_selected_path_count",
    "unique_exact_symbol_paths", "ambiguous_exact_symbol_paths",
    "ambiguous_only_exact_symbol_paths", "ambiguous_exact_symbol_pressure",
    "ambiguous_only_exact_symbol_ratio", "useful_query_term_coverage_ratio",
    "direct_query_term_coverage_ratio", "selected_paths_without_novel_query_terms",
    "distinct_newly_covered_useful_query_terms", "novel_coverage_efficiency",
    "novel_coverage_path_ratio", "direct_evidence_paths", "direct_evidence_ratio",
    "weak_only_paths", "weak_only_ratio", "graph_expanded_related_paths",
    "graph_expanded_related_ratio", "top_candidate_score",
    "median_selected_candidate_score", "minimum_selected_candidate_score",
    "median_to_top_score_ratio", "selected_to_candidate_source_ratio",
    "locator_to_selected_source_ratio", "selected_directory_count", "directory_dispersion",
    "selected_induced_graph_cluster_count", "largest_cluster_share",
    "required_phase_path_ratio",
)
NESTED_FEATURES = (
    "selected_range_phase_counts", "selected_path_phase_counts",
    "selected_score_within_top_fraction", "evidence_specificity_path_counts",
    "evidence_specificity_path_ratios", "signal_counts",
)
COUNTED_SEQUENCES = (
    "query_terms", "useful_query_terms", "rare_query_terms",
    "selected_matched_query_terms", "selected_matched_symbols",
    "direct_supported_query_terms", "weak_only_supported_query_terms",
)


def load_shadow_corpus(path: Path) -> dict[str, Any]:
    """Reject changed task text, labels, duplicate IDs, and unpinned metadata."""
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if set(corpus) != {
        "schema_version", "source_commit", "source_tree_sha",
        "selector_fingerprint", "mode", "max_context_tokens", "tasks",
    } or corpus["schema_version"] != 1 or corpus["mode"] != "balanced" or (
            corpus["max_context_tokens"] != 6000):
        raise ValueError("unsupported shadow corpus header")
    if not isinstance(corpus["tasks"], list) or not 20 <= len(corpus["tasks"]) <= 30:
        raise ValueError("shadow corpus must contain 20-30 tasks")
    for key, length in (("source_commit", 40), ("source_tree_sha", 40),
                        ("selector_fingerprint", 64)):
        value = corpus[key]
        if not isinstance(value, str) or len(value) != length or any(
                char not in "0123456789abcdef" for char in value):
            raise ValueError(f"invalid {key}")
    seen: set[str] = set()
    archetypes = Counter()
    for entry in corpus["tasks"]:
        if not isinstance(entry, dict) or set(entry) != TASK_KEYS:
            raise ValueError("shadow task fields must contain no outcome label")
        task_id, task = entry["task_id"], entry["task"]
        if not isinstance(task_id, str) or not task_id.isascii() or not task_id.isalnum():
            raise ValueError("invalid shadow task ID")
        if task_id in seen or not isinstance(task, str) or not task.strip():
            raise ValueError("duplicate task ID or empty task")
        seen.add(task_id)
        if hashlib.sha256(task.encode("utf-8")).hexdigest() != entry["sha256"]:
            raise ValueError(f"shadow task hash mismatch: {task_id}")
        if entry["archetype"] not in ARCHETYPES or any(
                type(entry[key]) is not bool for key in (
                    "explicit_paths_supplied", "explicit_symbols_supplied")):
            raise ValueError(f"invalid shadow task metadata: {task_id}")
        archetypes[entry["archetype"]] += 1
    if set(archetypes) != ARCHETYPES:
        raise ValueError("shadow corpus is missing an archetype")
    return corpus


def numeric_features(quality: Mapping[str, Any]) -> dict[str, int | float]:
    """Flatten only fixed numeric diagnostics, never per-path source metadata."""
    features = {key: quality[key] for key in TOP_LEVEL_FEATURES}
    for group in NESTED_FEATURES:
        features.update({f"{group}.{key}": value for key, value in quality[group].items()})
    features.update({f"{key}_count": len(quality[key]) for key in COUNTED_SEQUENCES})
    count = quality["selected_path_count"]
    features["test_selected_path_ratio"] = round(
        quality["test_selected_path_count"] / count, 4) if count else 0.0
    features["unique_exact_symbol_path_ratio"] = round(
        quality["unique_exact_symbol_paths"] / count, 4) if count else 0.0
    if any(type(value) not in (int, float) for value in features.values()):
        raise ValueError("non-numeric locator feature")
    return dict(sorted(features.items()))


def quantile(values: list[int | float], fraction: float) -> float:
    """Type-7 linear interpolation at (n - 1) * fraction, rounded to 4 decimals."""
    if not values or not 0 <= fraction <= 1:
        raise ValueError("nonempty values and fraction in [0, 1] required")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 4)


def feature_distributions(rows: list[Mapping[str, int | float]]) -> dict[str, dict[str, float]]:
    if not rows:
        raise ValueError("shadow feature rows cannot be empty")
    keys = set(rows[0])
    if any(set(row) != keys for row in rows):
        raise ValueError("shadow feature schemas differ")
    return {
        key: {label: quantile([row[key] for row in rows], fraction)
              for label, fraction in (("min", 0), ("p25", 0.25), ("median", 0.5),
                                      ("p75", 0.75), ("max", 1))}
        for key in sorted(keys)
    }


def anchor_positions(rows: list[Mapping[str, int | float]],
                     anchor: Mapping[str, int | float]) -> dict[str, dict[str, int | float]]:
    if not rows or set(anchor) != set(rows[0]) or any(set(row) != set(anchor) for row in rows):
        raise ValueError("anchor and shadow feature schemas differ")
    return {
        key: {
            "value": anchor[key],
            "shadow_below": sum(row[key] < anchor[key] for row in rows),
            "shadow_equal": sum(row[key] == anchor[key] for row in rows),
            "shadow_above": sum(row[key] > anchor[key] for row in rows),
        }
        for key in sorted(anchor)
    }


def evaluate_locator_quality_shadow(
        features: Mapping[str, int | float]) -> tuple[str, tuple[str, ...]]:
    """One diagnostic-only rule; callers must not wire it into production AUTO."""
    if features["selected_path_count"] == 0:
        return "BYPASS", ("NO_SELECTED_PATHS",)
    reasons = tuple(code for condition, code in (
        (features["largest_cluster_share"] < 1, "DISCONNECTED_SELECTION"),
        (features["ambiguous_exact_symbol_pressure"] > 0, "AMBIGUOUS_EXACT_SYMBOL"),
    ) if condition)
    if len(reasons) == 2:
        return "BYPASS", reasons
    if reasons:
        return "UNCERTAIN", reasons
    return "PASS", ()
