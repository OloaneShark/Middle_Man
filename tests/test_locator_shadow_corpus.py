"""Unlabeled shadow-corpus locks and descriptive statistics."""

from __future__ import annotations

import ast
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from middle_man.gateway.locator_shadow import (
    ARCHETYPES, TASK_KEYS, anchor_positions, evaluate_locator_quality_shadow,
    feature_distributions,
    load_shadow_corpus, numeric_features, quantile,
)
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint
from scripts.measure_locator_shadow_corpus import (
    CORPUS_PATH, ROOT, SELECTOR_FINGERPRINT, SOURCE_COMMIT, SOURCE_TREE_SHA,
)
from tests.test_locator_diagnostics import _candidate, _diagnostic, _index, _pack
from middle_man.gateway.locator_diagnostics import diagnose_locator


def test_corpus_hashes_metadata_archetypes_and_unlabeled_tasks(tmp_path: Path) -> None:
    corpus = load_shadow_corpus(CORPUS_PATH)
    assert len(corpus["tasks"]) == 24
    assert Counter(task["archetype"] for task in corpus["tasks"]) == {
        name: 4 for name in ARCHETYPES
    }
    assert all(set(task) == TASK_KEYS for task in corpus["tasks"])
    assert all("label" not in task and "outcome" not in task for task in corpus["tasks"])
    assert sum(task["explicit_paths_supplied"] for task in corpus["tasks"]) == 3
    assert sum(task["explicit_symbols_supplied"] for task in corpus["tasks"]) == 3
    tampered = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    tampered["tasks"][0]["task"] += " extra"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_shadow_corpus(path)
    tampered["tasks"][0]["task"] = corpus["tasks"][0]["task"]
    tampered["tasks"][0]["outcome"] = "WIN"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="no outcome label"):
        load_shadow_corpus(path)


def test_pinned_source_tree_and_selector_are_available() -> None:
    corpus = load_shadow_corpus(CORPUS_PATH)
    assert corpus["source_commit"] == SOURCE_COMMIT
    assert corpus["source_tree_sha"] == SOURCE_TREE_SHA
    assert corpus["selector_fingerprint"] == SELECTOR_FINGERPRINT
    assert selector_implementation_fingerprint() == SELECTOR_FINGERPRINT
    tree = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", f"{SOURCE_COMMIT}^{{tree}}"],
        text=True, timeout=15).strip()
    assert tree == SOURCE_TREE_SHA


def test_shadow_features_and_quantiles_are_deterministic() -> None:
    paths = ("src/runner.py", "src/helper.py")
    candidates = (
        _candidate(paths[0], 100, "PRIMARY", (("filename_term", "runner"),)),
        _candidate(paths[1], 50, "RELATED", (("family_term", "helper"),)),
    )
    diagnostics = (_diagnostic(candidates[0], "REQUIRED", ("term:runner",)),
                   _diagnostic(candidates[1], "COVERAGE"))
    quality = diagnose_locator(_pack("runner helper", candidates, diagnostics, paths),
                              _index(paths), locator_tokens=20)
    features = numeric_features(quality)
    assert features == numeric_features(quality)
    assert features["largest_cluster_share"] == 0.5
    assert features["median_to_top_score_ratio"] == 0.75
    assert features["required_phase_path_ratio"] == 0.5
    assert features["novel_coverage_efficiency"] == 0.5
    assert features["test_selected_path_ratio"] == 0.0
    assert quantile([0, 10, 20, 30], 0.25) == 7.5
    assert quantile([0, 10, 20, 30], 0.5) == 15.0
    with pytest.raises(ValueError):
        quantile([], 0.5)
    rows = [{"x": 0, "y": 5}, {"x": 10, "y": 5},
            {"x": 20, "y": 5}, {"x": 30, "y": 5}]
    assert feature_distributions(rows)["x"] == {
        "min": 0.0, "p25": 7.5, "median": 15.0, "p75": 22.5, "max": 30.0,
    }
    assert anchor_positions(rows, {"x": 20, "y": 5})["x"] == {
        "value": 20, "shadow_below": 2, "shadow_equal": 1, "shadow_above": 1,
    }
    with pytest.raises(ValueError, match="schemas differ"):
        feature_distributions([{"x": 1}, {"y": 1}])
    with pytest.raises(ValueError, match="schemas differ"):
        anchor_positions(rows, {"x": 1})


def test_shadow_runner_is_git_only_and_not_in_production_auto() -> None:
    script = (ROOT / "scripts" / "measure_locator_shadow_corpus.py").read_text(encoding="utf-8")
    tree = ast.parse(script)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
             isinstance(node.func, ast.Attribute) and
             isinstance(node.func.value, ast.Name) and
             node.func.value.id == "subprocess"]
    assert calls
    assert all(node.func.attr == "run" and isinstance(node.args[0], ast.List) and
               isinstance(node.args[0].elts[0], ast.Constant) and
               node.args[0].elts[0].value == "git" for node in calls)
    assert "locator_shadow" not in (
        ROOT / "middle_man" / "gateway" / "codex_benchmark" / "offline_auto.py"
    ).read_text(encoding="utf-8")
    assert "locator_shadow" not in (
        ROOT / "middle_man" / "gateway" / "codex_runner" / "runner.py"
    ).read_text(encoding="utf-8")


def test_shadow_decision_remains_descriptive_and_exposes_uncertainty() -> None:
    features = {
        "selected_path_count": 10, "largest_cluster_share": 1.0,
        "ambiguous_exact_symbol_pressure": 0.0,
    }
    assert evaluate_locator_quality_shadow(features) == ("PASS", ())
    assert evaluate_locator_quality_shadow({**features, "largest_cluster_share": 0.8}) == (
        "UNCERTAIN", ("DISCONNECTED_SELECTION",))
    assert evaluate_locator_quality_shadow({
        **features, "ambiguous_exact_symbol_pressure": 0.2,
    }) == ("UNCERTAIN", ("AMBIGUOUS_EXACT_SYMBOL",))
    assert evaluate_locator_quality_shadow({
        **features, "largest_cluster_share": 0.8,
        "ambiguous_exact_symbol_pressure": 0.2,
    }) == ("BYPASS", ("DISCONNECTED_SELECTION", "AMBIGUOUS_EXACT_SYMBOL"))
    assert evaluate_locator_quality_shadow({**features, "selected_path_count": 0}) == (
        "BYPASS", ("NO_SELECTED_PATHS",))


def test_saved_shadow_receipt_matches_locked_tasks_and_derived_statistics() -> None:
    corpus = load_shadow_corpus(CORPUS_PATH)
    raw = (ROOT / "docs" / "locator_quality_shadow_results.json").read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["source_commit"] == SOURCE_COMMIT
    assert receipt["source_tree_sha"] == SOURCE_TREE_SHA
    assert receipt["selector_fingerprint"] == SELECTOR_FINGERPRINT
    assert str(ROOT) not in raw
    assert [(task["task_id"], task["task_sha256"]) for task in receipt["shadow_tasks"]] == [
        (task["task_id"], task["sha256"]) for task in corpus["tasks"]
    ]
    rows = []
    for task in receipt["shadow_tasks"]:
        assert "outcome" not in task and "label" not in task
        assert numeric_features(task["quality"]) == task["features"]
        rows.append(task["features"])
    assert feature_distributions(rows) == receipt["distributions"]
    for anchor in receipt["anchors"].values():
        assert anchor_positions(rows, anchor["features"]) == anchor["positions"]
    decisions = receipt["shadow_policy"]["decisions"]
    assert [(item["task_id"], item["decision"], tuple(item["reason_codes"]))
            for item in decisions] == [
        (task["task_id"], *evaluate_locator_quality_shadow(task["features"]))
        for task in receipt["shadow_tasks"]
    ]
