from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from middle_man.experiments.source_selection_reference_eval import (
    evaluate_task, load_dataset, validate_dataset,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/locator_shadow_corpus.json"
DATASET = ROOT / "docs/source_selection_reference_dataset.json"


@pytest.fixture(scope="module")
def references() -> dict:
    return load_dataset(DATASET)


def test_pinned_provenance_and_all_source_citations(references: dict, tmp_path_factory) -> None:
    snapshot = tmp_path_factory.mktemp("reference-pin") / "source"
    subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks", "--no-checkout",
                    "-q", str(ROOT), str(snapshot)], check=True)
    subprocess.run(["git", "-C", str(snapshot), "checkout", "--detach", "-q",
                    references["source"]["commit"]], check=True)
    tree = subprocess.check_output(["git", "-C", str(snapshot), "rev-parse", "HEAD^{tree}"], text=True).strip()
    assert tree == references["source"]["tree"]
    validate_dataset(references, CORPUS, source_root=snapshot)
    assert {task["task_id"] for task in references["development_tasks"]} == {
        "N01", "M02", "C02", "T01", "G02", "E01"}
    assert {task["task_id"] for task in references["reserved_evaluation_tasks"]} == {
        "N04", "M04", "C04", "T03", "G04", "E04"}


def test_complete_alternative_is_accepted_without_exact_path_equality(references: dict) -> None:
    result = evaluate_task(references, "G02", ["middle_man/gateway/relevance.py",
                                               "middle_man/gateway/selection.py"], 420)
    assert result["core_coverage"] == 1.0
    assert result["alternative_options_satisfied"] == 2
    assert result["missed_core_areas"] == []
    assert result["selected_source_tokens"] == 420
    assert result["unresolved_cases"]


def test_partial_multifile_option_and_unreferenced_are_separate(references: dict) -> None:
    result = evaluate_task(references, "T01", ["tests/test_phase_8_prefix_cache.py",
                                               "middle_man/lab/memory.py", "notes/extra.py"], 1200)
    assert result["core_areas_covered"] == 2
    assert result["missed_core_areas"] == ["implementation"]
    assert result["partial_core_areas"] == ["implementation"]
    assert result["alternative_options_partial"] == 1
    assert result["test_coverage"] == 1.0
    assert result["unreferenced_selected_paths"] == ["notes/extra.py"]
    assert result["evidence_granularity"] == "PATH_ONLY_CITED_LINES_UNVERIFIED"


def test_reserved_split_requires_opt_in_and_tracks_tests(references: dict) -> None:
    with pytest.raises(ValueError, match="reserved"):
        evaluate_task(references, "T03", [], 0, split="reserved")
    result = evaluate_task(references, "T03", ["tests/test_codex_runner.py"], 150,
                           split="reserved", allow_reserved=True)
    assert result["test_coverage"] == 0.5
    assert "mutation_test" in result["missed_core_areas"]
    with pytest.raises(ValueError, match="not in the development"):
        evaluate_task(references, "T03", [], 0)


def test_explicit_path_and_symbol_anchor_retention(references: dict) -> None:
    missing = evaluate_task(references, "E01", ["middle_man/lab/memory.py"], 100)
    assert missing["explicit_anchors_missing"] == ["middle_man/lab/preemption.py"]
    retained = evaluate_task(references, "E04", ["middle_man/gateway/indexer.py"], 100,
                             split="reserved", allow_reserved=True)
    assert retained["explicit_anchors_retained"] == ["middle_man/gateway/indexer.py"]


def test_rejects_bad_provenance_and_unsafe_paths(references: dict) -> None:
    bad = copy.deepcopy(references)
    bad["development_tasks"][0]["task_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="reference task"):
        validate_dataset(bad, CORPUS)
    with pytest.raises(ValueError, match="invalid repository-relative"):
        evaluate_task(references, "N01", ["../outside.py"], 0)
    with pytest.raises(ValueError, match="nonnegative"):
        evaluate_task(references, "N01", [], -1)
