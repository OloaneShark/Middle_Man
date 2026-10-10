"""Offline integrity checks for the unscored prospective A-plus task corpus."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/a_plus_prospective_corpus.json"
TEMPLATE = ROOT / "docs/a_plus_review_template.json"
HISTORICAL = ROOT / "tests/fixtures/locator_shadow_corpus.json"
PINNED_COMMIT = "8a6dca9e3cfadd144f14e860d182ec44ac0faedc"
PINNED_TREE = "467f280dfc781897099d726085974223cf9d6754"
PINNED_FINGERPRINT = "bf192a20ad175d0714ddaeee4927c034f452fed5fb93c396acb0a94d515e3c9c"
FROZEN_CORPUS_SHA256 = "4580134b1ed60c4b75c3c951cda89e65e863ec32dbc70f39e192efaac69770af"
ARCHETYPES = {
    "narrow_explicit_anchor": "N",
    "multi_file_architecture": "M",
    "test_focused": "T",
    "broad_ambiguous": "G",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
        encoding="utf-8",
    ).stdout.strip()


def test_task_count_distribution_ids_and_source_pin() -> None:
    corpus = _load(CORPUS)
    tasks = corpus["tasks"]
    assert corpus["schema"] == "middle_man.a_plus_prospective_corpus.v1"
    assert corpus["status"] == "TASKS_FROZEN_HUMAN_REVIEW_PENDING"
    assert len(tasks) == 16
    assert Counter(task["archetype"] for task in tasks) == {key: 4 for key in ARCHETYPES}
    assert len({task["task_id"] for task in tasks}) == 16
    assert [task["task_id"] for task in tasks] == [
        f"AP-{letter}{number:02d}"
        for letter in ARCHETYPES.values() for number in range(1, 5)
    ]
    assert corpus["source"] == {
        "commit": PINNED_COMMIT,
        "tree": PINNED_TREE,
        "fingerprint": PINNED_FINGERPRINT,
        "fingerprint_method": "middle_man.gateway.codex_benchmark.tasks.source_fingerprint",
    }
    assert _git("rev-parse", f"{PINNED_COMMIT}^{{tree}}") == PINNED_TREE
    for task in tasks:
        assert task["source_commit"] == PINNED_COMMIT
        assert task["source_tree"] == PINNED_TREE


def test_exact_utf8_task_hashes_and_frozen_corpus_checksum() -> None:
    corpus = _load(CORPUS)
    tasks = corpus["tasks"]
    assert corpus["task_hash_method"] == "sha256(exact task UTF-8 bytes; no appended newline)"
    assert corpus["corpus_hash_method"] == (
        "sha256(canonical JSON of tasks array; sort_keys=True, ensure_ascii=False, "
        "separators=(',', ':'); UTF-8)"
    )
    for task in tasks:
        assert task["task"] and task["task"] == task["task"].strip()
        assert task["sha256"] == hashlib.sha256(task["task"].encode("utf-8")).hexdigest()
    canonical = json.dumps(tasks, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
    assert corpus["corpus_sha256"] == FROZEN_CORPUS_SHA256
    assert hashlib.sha256(canonical).hexdigest() == FROZEN_CORPUS_SHA256


def test_historical_prompts_differ_and_provenance_exists_at_source_pin() -> None:
    tasks = _load(CORPUS)["tasks"]
    historical = {item["task"].strip().casefold() for item in _load(HISTORICAL)["tasks"]}
    assert len(historical) == 24
    tracked = set(_git("ls-tree", "-r", "--name-only", PINNED_COMMIT).splitlines())
    for task in tasks:
        assert task["task"].strip().casefold() not in historical
        assert task["authoring_provenance"]["method"] == "read-only pinned-source inspection"
        paths = task["authoring_provenance"]["source_paths_checked"]
        assert paths and set(paths) <= tracked
        assert set(task["explicit_paths_supplied"]) <= set(paths)
        assert all(path in task["task"] for path in task["explicit_paths_supplied"])
        assert all(symbol in task["task"] for symbol in task["explicit_symbols_supplied"])
        assert task["ambiguity_notes"]
        assert not any(key in task for key in (
            "reference_areas", "reference_labels", "candidate_output", "navigation_score",
            "human_validated", "selector_result",
        ))


def test_human_review_template_is_blank_and_pending() -> None:
    corpus = _load(CORPUS)
    review = _load(TEMPLATE)
    assert review["schema"] == "middle_man.a_plus_human_review_template.v1"
    assert review["status"] == "PENDING"
    assert review["corpus_sha256"] == corpus["corpus_sha256"]
    assert review["source_commit"] == PINNED_COMMIT
    assert review["source_tree"] == PINNED_TREE
    assert [slot["slot"] for slot in review["reviewers"]] == ["reviewer_1", "reviewer_2"]
    for slot in review["reviewers"]:
        assert slot["status"] == "PENDING"
        assert slot["human_reviewer_id"] is None
        assert slot["submitted_at"] is None
        assert slot["task_reviews"] == []
    entry = review["task_review_entry_template"]
    assert entry["task_id"] is None and entry["status"] == "PENDING"
    for field in (
        "required_implementation_areas", "source_paths",
        "relevant_function_method_symbols", "source_line_intervals",
        "complete_alternative_evidence_options", "supporting_tests_or_integrations",
        "unresolved_interpretation_issues",
    ):
        assert entry[field] == []
    assert entry["source_grounded_reasoning"] is None
    adjudication = review["adjudication"]
    assert adjudication["status"] == "PENDING"
    assert adjudication["human_adjudicator_id"] is None
    assert adjudication["completed_at"] is None
    assert adjudication["disagreements_and_decisions"] == []
    assert adjudication["unresolved_issues"] == []
    assert review["ai_reference_suggestions"] == {
        "status": "NOT_PREPARED", "can_substitute_for_human_review": False,
    }
