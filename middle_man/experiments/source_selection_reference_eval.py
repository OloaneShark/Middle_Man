"""Offline, path-level comparison against proposed pinned-source references."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SPLITS = {"development": "development_tasks", "reserved": "reserved_evaluation_tasks"}


def load_dataset(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError(f"invalid repository-relative path: {value!r}")
    return value


def _references(task: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for area in task["areas"]:
        for option in area["options"]:
            yield from option
    yield from task["supporting"]


def validate_dataset(dataset: dict[str, Any], corpus_path: Path, *,
                     source_root: Path | None = None) -> None:
    """Check frozen task provenance and, optionally, every cited source range."""
    if dataset["schema_version"] != 1 or dataset["judgment_status"] != "PROPOSED_SOURCE_GROUNDED_NOT_HUMAN_VALIDATED":
        raise ValueError("unsupported or overstated reference dataset")
    raw = corpus_path.read_bytes()
    source = dataset["source"]
    if hashlib.sha256(raw).hexdigest() != source["corpus_sha256"]:
        raise ValueError("corpus checksum differs from reference pin")
    corpus = json.loads(raw)
    if (len(corpus["tasks"]) != 24 or source["commit"] != corpus["source_commit"]
            or source["tree"] != corpus["source_tree_sha"]
            or source["selector_fingerprint"] != corpus["selector_fingerprint"]):
        raise ValueError("frozen corpus provenance differs")
    frozen = {task["task_id"]: task for task in corpus["tasks"]}
    if any(hashlib.sha256(task["task"].encode("utf-8")).hexdigest() != task["sha256"]
           for task in corpus["tasks"]):
        raise ValueError("frozen task hash differs")
    seen: set[str] = set()
    for split, key in SPLITS.items():
        tasks = dataset[key]
        if len(tasks) != 6:
            raise ValueError(f"{split} split must contain six tasks")
        for task in tasks:
            task_id = task["task_id"]
            if task_id in seen or task_id not in frozen:
                raise ValueError("duplicate or unknown reference task")
            seen.add(task_id)
            original = frozen[task_id]
            if task["task_sha256"] != original["sha256"] or task["archetype"] != original["archetype"]:
                raise ValueError("reference task differs from frozen corpus")
            for anchor in task["explicit_anchors"]:
                _safe_path(anchor)
            if bool(task["explicit_anchors"]) != (original["explicit_paths_supplied"]
                                                    or original["explicit_symbols_supplied"]):
                raise ValueError("explicit anchor mismatch")
            if not task["areas"] or len({area["id"] for area in task["areas"]}) != len(task["areas"]):
                raise ValueError("core areas missing or duplicated")
            for area in task["areas"]:
                if not area["options"] or any(not option for option in area["options"]):
                    raise ValueError("empty core evidence option")
                expected = "alternative" if len(area["options"]) > 1 else "unique"
                for option in area["options"]:
                    for ref in option:
                        if ref["requirement"] != expected:
                            raise ValueError("incorrect core alternative label")
            for ref in task["supporting"]:
                if ref["requirement"] != "optional":
                    raise ValueError("supporting evidence must be optional")
            for ref in _references(task):
                path = _safe_path(ref["path"])
                start, end = ref["lines"]
                if not ref["symbol"] or not ref["behavior"] or not ref["reason"] or start < 1 or end < start:
                    raise ValueError("incomplete evidence reference")
                if source_root is not None:
                    file = (source_root / path).resolve()
                    if not file.is_relative_to(source_root.resolve()) or not file.is_file():
                        raise ValueError(f"missing or unsafe pinned source: {path}")
                    lines = file.read_text(encoding="utf-8").splitlines()
                    if end > len(lines):
                        raise ValueError(f"out-of-range evidence: {path}:{start}-{end}")
                    source_text = "\n".join(lines)
                    for symbol in ref["symbol"].split(" / "):
                        name = symbol.rsplit(".", 1)[-1]
                        if not re.search(r"\b" + re.escape(name) + r"\b", source_text):
                            raise ValueError(f"symbol absent from cited file: {path}: {symbol}")


def evaluate_task(dataset: dict[str, Any], task_id: str, selected_paths: Iterable[str],
                  selected_source_tokens: int, *, split: str = "development",
                  allow_reserved: bool = False) -> dict[str, Any]:
    """Compare selected paths only; a selected path does not prove its cited lines were delivered."""
    if split not in SPLITS or split == "reserved" and not allow_reserved:
        raise ValueError("reserved references require explicit opt-in")
    if isinstance(selected_source_tokens, bool) or not isinstance(selected_source_tokens, int) or selected_source_tokens < 0:
        raise ValueError("selected_source_tokens must be a nonnegative integer")
    task = next((item for item in dataset[SPLITS[split]] if item["task_id"] == task_id), None)
    if task is None:
        raise ValueError(f"task {task_id} is not in the {split} split")
    selected = {_safe_path(path) for path in selected_paths}
    all_refs = tuple(_references(task))
    referenced = {ref["path"] for ref in all_refs}
    areas = []
    for area in task["areas"]:
        options = []
        for option in area["options"]:
            paths = {ref["path"] for ref in option}
            options.append({"required_paths": sorted(paths), "matched_paths": sorted(paths & selected),
                            "satisfied": paths <= selected, "partial": bool(paths & selected) and not paths <= selected})
        areas.append({"id": area["id"], "satisfied": any(item["satisfied"] for item in options),
                      "partial": not any(item["satisfied"] for item in options) and any(item["partial"] for item in options),
                      "options": options})
    support = {ref["path"] for ref in task["supporting"]}
    tests = {ref["path"] for ref in all_refs if ref["path"].startswith("tests/")}
    anchors = set(task["explicit_anchors"])
    covered = sum(item["satisfied"] for item in areas)
    return {
        "task_id": task_id, "split": split, "judgment_status": dataset["judgment_status"],
        "evidence_granularity": "PATH_ONLY_CITED_LINES_UNVERIFIED",
        "core_areas_covered": covered, "core_areas_total": len(areas),
        "core_coverage": covered / len(areas),
        "missed_core_areas": [item["id"] for item in areas if not item["satisfied"]],
        "partial_core_areas": [item["id"] for item in areas if item["partial"]],
        "alternative_options_satisfied": sum(option["satisfied"] for item in areas for option in item["options"]),
        "alternative_options_partial": sum(option["partial"] for item in areas for option in item["options"]),
        "areas": areas,
        "supporting_paths_covered": sorted(support & selected),
        "supporting_paths_total": len(support),
        "supporting_coverage": len(support & selected) / len(support) if support else None,
        "test_paths_covered": sorted(tests & selected) if task["archetype"] == "TEST_FOCUSED" else None,
        "test_paths_total": len(tests) if task["archetype"] == "TEST_FOCUSED" else None,
        "test_coverage": len(tests & selected) / len(tests) if tests and task["archetype"] == "TEST_FOCUSED" else None,
        "explicit_anchors_retained": sorted(anchors & selected),
        "explicit_anchors_missing": sorted(anchors - selected),
        "unreferenced_selected_paths": sorted(selected - referenced),
        "unresolved_cases": task["unresolved"],
        "selected_source_tokens": selected_source_tokens,
    }
