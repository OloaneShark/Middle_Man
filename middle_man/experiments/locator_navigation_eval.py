"""Local, structural audit of source-free locator navigation on development tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable

from middle_man.experiments.source_selection_reference_eval import (
    DEVELOPMENT_IDS, _safe_path, load_dataset, validate_dataset,
)
from middle_man.gateway.codex_benchmark.offline_auto import decide_offline_locator
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator, build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery, RelevanceEngine
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


SOURCE_FINGERPRINT = "6f360e98d7d87339129d0fde8725b6e26a03fcdf0f16f9a24d8c7a3f6a3db340"
LINE = re.compile(r"^- ([^:\n]+):(.+)$")
RANGE = re.compile(r"^([1-9]\d*)-([1-9]\d*)(?: \(([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\))?$")


def parse_locator(text: str) -> list[dict[str, Any]]:
    """Parse the literal production hint format; never infer hidden excerpt metadata."""
    if text == "- No selected locations; use native repository search.":
        return []
    hints = []
    for line in text.splitlines():
        match = LINE.fullmatch(line)
        if match is None:
            raise ValueError("unexpected locator line")
        path = _safe_path(match[1])
        for label in match[2].split("; "):
            span = RANGE.fullmatch(label)
            if span is None or int(span[2]) < int(span[1]):
                raise ValueError("unexpected locator range")
            hints.append({"path": path, "range": [int(span[1]), int(span[2])],
                          "symbol": span[3]})
    return hints


def _symbol_match(hint: str | None, citation: str) -> bool:
    if hint is None:
        return False
    owner = ""
    for raw in citation.split(" / "):
        part = raw.strip()
        qualified = part if "." in part else f"{owner}.{part}" if owner else part
        if "." in qualified:
            owner = qualified.rsplit(".", 1)[0]
        if hint == qualified or not owner and hint.endswith("." + qualified):
            return True
    return False


def _fully_covered(start: int, end: int, ranges: Iterable[list[int]]) -> bool:
    cursor = start
    for left, right in sorted(ranges):
        if right < cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right + 1)
        if cursor > end:
            return True
    return False


def evaluate_navigation(task: dict[str, Any], locator_text: str, *,
                        file_lengths: dict[str, int],
                        candidate_status: dict[str, str] | None = None) -> dict[str, Any]:
    """Evaluate navigation proxies against one proposed development reference task."""
    hints = parse_locator(locator_text)
    by_path: dict[str, list[dict[str, Any]]] = {}
    for hint in hints:
        by_path.setdefault(hint["path"], []).append(hint)

    def evaluate_ref(ref: dict[str, Any]) -> dict[str, Any]:
        path = _safe_path(ref["path"])
        start, end = ref["lines"]
        path_hints = by_path.get(path, [])
        overlaps = [hint for hint in path_hints
                    if hint["range"][0] <= end and hint["range"][1] >= start]
        symbols = [hint for hint in path_hints if _symbol_match(hint["symbol"], ref["symbol"])]
        broad = [hint["range"] for hint in path_hints
                 if path in file_lengths and hint["range"][0] == 1
                 and hint["range"][1] >= file_lengths[path]]
        return {"path": path, "reference_lines": [start, end], "reference_symbol": ref["symbol"],
                "path_targeted": bool(path_hints), "range_intersects": bool(overlaps),
                "symbol_match": bool(symbols),
                "locator_range_fully_covers_citation": _fully_covered(
                    start, end, [hint["range"] for hint in path_hints]),
                "navigable": bool(path_hints) and bool(overlaps or symbols),
                "broad_whole_file_ranges": broad,
                "diagnosis": ("NAVIGABLE" if path_hints and (overlaps or symbols) else
                              "UNRELATED_RANGE_OR_SYMBOL" if path_hints else
                              (candidate_status or {}).get(path, "MISSING_PATH_UNKNOWN_CAUSE"))}

    areas = []
    for area in task["areas"]:
        options = []
        for option in area["options"]:
            refs = [evaluate_ref(ref) for ref in option]
            options.append({"navigable": all(ref["navigable"] for ref in refs),
                            "locator_ranges_fully_cover": all(
                                ref["locator_range_fully_covers_citation"] for ref in refs),
                            "references": refs})
        areas.append({"id": area["id"], "navigable": any(option["navigable"] for option in options),
                      "locator_ranges_fully_cover": any(
                          option["locator_ranges_fully_cover"] for option in options),
                      "options": options})
    for hint in hints:
        length = file_lengths.get(hint["path"])
        hint["specificity"] = ("BROAD_WHOLE_FILE" if length is not None
                               and hint["range"][0] == 1 and hint["range"][1] >= length
                               else "SPECIFIC_RANGE")
    refs = [ref for area in areas for option in area["options"] for ref in option["references"]]
    appendix = append_offline_locator("", locator_text)
    return {"task_id": task["task_id"], "locator_sha256": hashlib.sha256(locator_text.encode()).hexdigest(),
            "locator_characters": len(locator_text),
            "locator_estimated_tokens": HeuristicTokenEstimator().estimate(locator_text),
            "model_visible_appendix_characters": len(appendix),
            "model_visible_appendix_estimated_tokens": HeuristicTokenEstimator().estimate(appendix),
            "selected_paths": list(dict.fromkeys(hint["path"] for hint in hints)), "hints": hints,
            "areas": areas, "areas_navigable": sum(area["navigable"] for area in areas),
            "areas_locator_ranges_fully_cover": sum(area["locator_ranges_fully_cover"] for area in areas),
            "areas_total": len(areas), "referenced_paths_missing": sorted({ref["path"] for ref in refs
                                                                    if not ref["path_targeted"]}),
            "wrong_range_or_symbol": sorted({ref["path"] for ref in refs
                                               if ref["path_targeted"] and not ref["navigable"]}),
            "references_path_targeted": sum(ref["path_targeted"] for ref in refs),
            "references_range_intersects": sum(ref["range_intersects"] for ref in refs),
            "references_symbol_match": sum(ref["symbol_match"] for ref in refs),
            "targeted_references_without_symbol_match": sum(
                ref["path_targeted"] and not ref["symbol_match"] for ref in refs),
            "broad_hints": sum(hint["specificity"] == "BROAD_WHOLE_FILE" for hint in hints),
            "specific_hints": sum(hint["specificity"] == "SPECIFIC_RANGE" for hint in hints)}


def development_task(dataset: dict[str, Any], task_id: str) -> dict[str, Any]:
    if task_id not in DEVELOPMENT_IDS:
        raise ValueError("only development labels may be evaluated")
    return next(task for task in dataset["development_tasks"] if task["task_id"] == task_id)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


def run_audit(repository_root: Path, corpus_path: Path, dataset_path: Path) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    validate_dataset(dataset, corpus_path)
    source = dataset["source"]
    if selector_implementation_fingerprint() != source["selector_fingerprint"]:
        raise RuntimeError("production selector fingerprint changed")
    if tuple(task["task_id"] for task in dataset["development_tasks"]) != DEVELOPMENT_IDS:
        raise RuntimeError("development task order changed")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    frozen = {task["task_id"]: task for task in corpus["tasks"]}
    with TemporaryDirectory(prefix="middle-man-locator-navigation-") as temporary:
        snapshot = Path(temporary) / "source"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                        "--no-checkout", "-q", str(repository_root), str(snapshot)],
                       check=True, capture_output=True, text=True, timeout=120)
        _git(snapshot, "checkout", "--detach", "-q", source["commit"])
        if (_git(snapshot, "rev-parse", "HEAD") != source["commit"]
                or _git(snapshot, "rev-parse", "HEAD^{tree}") != source["tree"]
                or _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all")
                or source_fingerprint(snapshot) != SOURCE_FINGERPRINT):
            raise RuntimeError("pinned source snapshot differs")
        config = GatewayConfig(snapshot, cache_writes_enabled=False)
        builder = ContextBuilder(config)
        tasks = []
        for task_id in DEVELOPMENT_IDS:
            task = development_task(dataset, task_id)
            query = ContextQuery(frozen[task_id]["task"])
            pack = builder.build(query, mode="balanced", max_context_tokens=6000)
            locator = build_offline_locator(config, query)
            if pack.fingerprint != locator.pack_fingerprint:
                raise RuntimeError("pack and locator selection differ")
            decision = decide_offline_locator(pack, locator, read_only=True)
            ranked = {item.path for item in RelevanceEngine(builder.indexer.index(), config).find(
                pack.query, top_k=len(builder.indexer.index().files))}
            diagnostics = {item.candidate_path: item for item in pack.selection_diagnostics}
            candidate_paths = {item.path for item in pack.candidates}
            references = {ref["path"] for area in task["areas"] for option in area["options"] for ref in option}
            status = {}
            for path in references:
                diagnostic = diagnostics.get(path)
                if path not in candidate_paths:
                    status[path] = "BEYOND_CANDIDATE_CAP" if path in ranked else "NO_RANKED_CANDIDATE"
                elif diagnostic and diagnostic.omission_reason:
                    reason = diagnostic.omission_reason
                    status[path] = ("OUTSIDE_TASK_CLUSTER" if "outside_task_cluster" in reason else
                                    "ALLOCATION_OMISSION" if "context_budget" in reason else reason)
                else:
                    status[path] = "SELECTED" if path in locator.selected_paths else "CANDIDATE_NOT_SELECTED"
            lengths = {path: len((snapshot / path).read_text(encoding="utf-8").splitlines())
                       for path in references | {hint["path"] for hint in parse_locator(locator.text)}}
            row = evaluate_navigation(task, locator.text, file_lengths=lengths, candidate_status=status)
            row.update({"task_sha256": frozen[task_id]["sha256"], "auto_used": decision.use_locator,
                        "auto_reason": decision.reason, "pack_fingerprint": pack.fingerprint,
                        "internal_selected_source_tokens": pack.metrics.estimated_selected_tokens,
                        "internal_candidate_source_tokens": pack.metrics.estimated_raw_candidate_tokens,
                        "reference_path_diagnostics": [{"path": path, "status": status[path],
                                                        "candidate": path in candidate_paths,
                                                        "selected": path in locator.selected_paths}
                                                       for path in sorted(references)]})
            if row["locator_sha256"] != locator.sha256 or row["locator_estimated_tokens"] != locator.estimated_tokens:
                raise RuntimeError("parsed locator differs from production output")
            tasks.append(row)
        if _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("local audit mutated pinned source")
    return {"schema_version": 1, "scope": "DEVELOPMENT_ONLY", "model_calls": 0,
            "source_commit": source["commit"], "source_tree": source["tree"],
            "source_fingerprint": SOURCE_FINGERPRINT, "corpus_sha256": source["corpus_sha256"],
            "reference_dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "selector_fingerprint": source["selector_fingerprint"], "mode": "balanced",
            "context_budget": 6000, "structural_navigation_proxy_only": True, "tasks": tasks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-audit", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    report = run_audit(root, root / "tests/fixtures/locator_shadow_corpus.json",
                       root / "docs/source_selection_reference_dataset.json")
    if args.save_audit:
        target = root / "docs/source_free_locator_navigation_audit.json"
        if target.is_symlink() or not target.resolve().is_relative_to(root / "docs"):
            raise RuntimeError("unsafe audit target")
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"scope": report["scope"], "model_calls": 0,
                      "tasks": [{"task_id": row["task_id"], "areas_navigable": row["areas_navigable"],
                                 "areas_total": row["areas_total"]} for row in report["tasks"]]}))


if __name__ == "__main__":
    main()
