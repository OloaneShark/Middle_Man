"""Build blinded, unfilled review packets from the frozen A-plus task corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/a_plus_prospective_corpus.json"
OUTPUTS = {
    "packet": ROOT / "docs/a_plus_blinded_review_packet.json",
    "reviewer_1": ROOT / "docs/a_plus_reviewer_1_submission.template.json",
    "reviewer_2": ROOT / "docs/a_plus_reviewer_2_submission.template.json",
}
SOURCE_COMMIT = "8a6dca9e3cfadd144f14e860d182ec44ac0faedc"
SOURCE_TREE = "467f280dfc781897099d726085974223cf9d6754"
CORPUS_SHA256 = "4580134b1ed60c4b75c3c951cda89e65e863ec32dbc70f39e192efaac69770af"
TASK_IDS = tuple(f"AP-{group}{number:02d}" for group in "NMTG" for number in range(1, 5))

INSTRUCTIONS = [
    "Inspect the pinned source commit independently. Do not use another reviewer's work or candidate outputs.",
    "For each task, record required implementation areas, source-relative paths, qualified function or method symbols, inclusive line intervals, supporting tests or integrations, and source-grounded reasoning.",
    "Record each complete alternative evidence option as a sufficient whole. Do not combine partial alternatives to imply completeness.",
    "Document unresolved interpretations or ambiguity from your own reading of the task and source. Leave uncertain judgments unresolved rather than guessing.",
    "Keep completed submissions private until both independent reviews are complete; do not commit identities or responses to this repository.",
]


def _blank_evidence() -> dict[str, object]:
    return {
        "status": "PENDING",
        "required_implementation_areas": [],
        "source_paths": [],
        "relevant_function_method_symbols": [],
        "source_line_intervals": [],
        "complete_alternative_evidence_options": [],
        "supporting_tests_or_integrations": [],
        "unresolved_interpretation_issues": [],
        "source_grounded_reasoning": None,
    }


def load_frozen_corpus(path: Path = CORPUS) -> dict[str, object]:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    tasks = corpus["tasks"]
    if corpus["schema"] != "middle_man.a_plus_prospective_corpus.v1":
        raise ValueError("unexpected corpus schema")
    if corpus["source"]["commit"] != SOURCE_COMMIT or corpus["source"]["tree"] != SOURCE_TREE:
        raise ValueError("source pin changed")
    if [task["task_id"] for task in tasks] != list(TASK_IDS):
        raise ValueError("frozen task identities changed")
    payload = json.dumps(tasks, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    if corpus["corpus_sha256"] != CORPUS_SHA256 or hashlib.sha256(payload).hexdigest() != CORPUS_SHA256:
        raise ValueError("frozen corpus checksum changed")
    for task in tasks:
        if task["source_commit"] != SOURCE_COMMIT or task["source_tree"] != SOURCE_TREE:
            raise ValueError("task source pin changed")
        if hashlib.sha256(task["task"].encode("utf-8")).hexdigest() != task["sha256"]:
            raise ValueError("task wording or hash changed")
    tree = subprocess.check_output(
        ["git", "rev-parse", f"{SOURCE_COMMIT}^{{tree}}"], cwd=ROOT, text=True,
        encoding="utf-8", timeout=15,
    ).strip()
    if tree != SOURCE_TREE:
        raise ValueError("pinned source tree unavailable or changed")
    return corpus


def build_packet(corpus: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "middle_man.a_plus_blinded_review_packet.v1",
        "source": {"commit": SOURCE_COMMIT, "tree": SOURCE_TREE},
        "instructions": list(INSTRUCTIONS),
        "tasks": [
            {
                "task_id": task["task_id"],
                "task": task["task"],
                "sha256": task["sha256"],
                "evidence": _blank_evidence(),
            }
            for task in corpus["tasks"]
        ],
    }


def build_submission(packet: dict[str, object], slot: str) -> dict[str, object]:
    if slot not in {"reviewer_1", "reviewer_2"}:
        raise ValueError("unknown reviewer slot")
    return {
        "schema": "middle_man.a_plus_blinded_submission_template.v1",
        "reviewer_slot": slot,
        "review_status": "PENDING",
        "packet": deepcopy(packet),
    }


def rendered_outputs(corpus: dict[str, object]) -> dict[str, str]:
    packet = build_packet(corpus)
    documents = {
        "packet": packet,
        "reviewer_1": build_submission(packet, "reviewer_1"),
        "reviewer_2": build_submission(packet, "reviewer_2"),
    }
    return {name: json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            for name, document in documents.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify committed outputs without writing")
    args = parser.parse_args()
    for name, content in rendered_outputs(load_frozen_corpus()).items():
        path = OUTPUTS[name]
        if args.check:
            if path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"stale review packet: {path.relative_to(ROOT)}")
        else:
            path.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
