"""Offline, path-level comparison against proposed pinned-source references."""

from __future__ import annotations

import ast
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
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


def inspect_development_citations(dataset: dict[str, Any], source_root: Path) -> list[dict[str, Any]]:
    """Check symbol AST spans against cited intervals; semantic adequacy still needs review."""
    issues = []
    parsed: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for task in dataset["development_tasks"]:
        for ref in _references(task):
            path = _safe_path(ref["path"])
            file = (source_root / path).resolve()
            if not file.is_relative_to(source_root.resolve()) or not file.is_file():
                issues.append({"task_id": task["task_id"], "path": path, "issue": "MISSING_OR_UNSAFE_FILE"})
                continue
            if path not in parsed:
                tree = ast.parse(file.read_text(encoding="utf-8"), filename=path)
                symbols: dict[str, list[tuple[int, int]]] = {}

                def visit(nodes: list[ast.stmt], parent: str = "") -> None:
                    for node in nodes:
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            name = f"{parent}.{node.name}" if parent else node.name
                            symbols.setdefault(name, []).append((node.lineno, node.end_lineno or node.lineno))
                            visit(node.body, name)

                visit(tree.body)
                parsed[path] = symbols
            prefix = ""
            for part in ref["symbol"].split(" / "):
                if "." in part:
                    name = part
                    prefix = part.rsplit(".", 1)[0]
                else:
                    name = f"{prefix}.{part}" if prefix else part
                spans = parsed[path].get(name, ())
                if not spans and "." not in name:
                    spans = tuple(span for qualified, found in parsed[path].items()
                                  if qualified.endswith("." + name) for span in found)
                start, end = ref["lines"]
                if not spans or not any(left <= end and right >= start for left, right in spans):
                    issues.append({"task_id": task["task_id"], "path": path,
                                   "symbol": name, "reference_lines": [start, end],
                                   "issue": "SYMBOL_SPAN_NOT_IN_REFERENCE_RANGE"})
    return issues


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


DEVELOPMENT_IDS = ("N01", "M02", "C02", "T01", "G02", "E01")
RANGE_FULL = "RANGE_FULL"
RANGE_PARTIAL = "RANGE_PARTIAL"
RANGE_MISSING = "RANGE_MISSING"
FILE_MISSING = "FILE_MISSING"


def _missing_intervals(start: int, end: int, intervals: Iterable[tuple[int, int]]) -> list[list[int]]:
    missing: list[list[int]] = []
    cursor = start
    for left, right in sorted(intervals):
        if right < cursor or left > end:
            continue
        if left > cursor:
            missing.append([cursor, min(left - 1, end)])
        cursor = max(cursor, right + 1)
        if cursor > end:
            break
    if cursor <= end:
        missing.append([cursor, end])
    return missing


def _reference_delivery(ref: dict[str, Any], excerpts: tuple[Any, ...]) -> dict[str, Any]:
    path = _safe_path(ref["path"])
    start, end = ref["lines"]
    if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int)
            or isinstance(end, bool) or start < 1 or end < start):
        raise ValueError("unsafe reference interval")
    matching = [item for item in excerpts if item.path == path]
    ranges = []
    usable = []
    malformed = []
    for item in matching:
        if (not isinstance(item.start_line, int) or not isinstance(item.end_line, int)
                or item.start_line < 1 or item.end_line < item.start_line):
            raise ValueError("invalid selected excerpt interval")
        ranges.append([item.start_line, item.end_line])
        if len(item.text.splitlines()) == item.end_line - item.start_line + 1:
            usable.append((item.start_line, item.end_line))
        else:
            malformed.append([item.start_line, item.end_line])
    missing = _missing_intervals(start, end, usable)
    covered = end - start + 1 - sum(right - left + 1 for left, right in missing)
    status = (FILE_MISSING if not matching else RANGE_FULL if not missing else
              RANGE_PARTIAL if covered else RANGE_MISSING)
    return {
        "path": path, "symbol": ref["symbol"], "reference_lines": [start, end],
        "path_covered": bool(matching), "status": status,
        "covered_lines": covered, "required_lines": end - start + 1,
        "missing_lines": missing, "delivered_ranges": ranges,
        "complete_file_excerpt": any(item.complete_file for item in matching),
        "truncated_excerpt": any(item.truncated for item in matching),
        "content_line_mismatch_ranges": malformed,
    }


def _option_status(refs: list[dict[str, Any]]) -> str:
    if all(ref["status"] == RANGE_FULL for ref in refs):
        return RANGE_FULL
    if any(ref["covered_lines"] for ref in refs):
        return RANGE_PARTIAL
    if any(ref["path_covered"] for ref in refs):
        return RANGE_MISSING
    return FILE_MISSING


def evaluate_delivery(dataset: dict[str, Any], task_id: str, pack: Any, *,
                      split: str = "development", allow_reserved: bool = False,
                      all_ranked_paths: Iterable[str] | None = None) -> dict[str, Any]:
    """Audit structural line delivery, without storing or judging excerpt text."""
    if split not in SPLITS or split == "reserved" and not allow_reserved:
        raise ValueError("reserved references require explicit opt-in")
    task = next((item for item in dataset[SPLITS[split]] if item["task_id"] == task_id), None)
    if task is None:
        raise ValueError(f"task {task_id} is not in the {split} split")
    from middle_man.gateway.tokens import HeuristicTokenEstimator

    excerpts = tuple(pack.excerpts)
    estimator = HeuristicTokenEstimator()
    selected = {_safe_path(item.path) for item in excerpts}
    path_result = evaluate_task(dataset, task_id, selected, pack.metrics.estimated_selected_tokens,
                                split=split, allow_reserved=allow_reserved)
    areas = []
    for area in task["areas"]:
        options = []
        for option in area["options"]:
            refs = [_reference_delivery(ref, excerpts) for ref in option]
            options.append({"status": _option_status(refs), "references": refs})
        statuses = [item["status"] for item in options]
        status = (RANGE_FULL if RANGE_FULL in statuses else RANGE_PARTIAL if RANGE_PARTIAL in statuses else
                  RANGE_MISSING if RANGE_MISSING in statuses else FILE_MISSING)
        areas.append({"id": area["id"], "status": status, "options": options})
    supporting = [_reference_delivery(ref, excerpts) for ref in task["supporting"]]
    test_refs = [ref for ref in _references(task) if ref["path"].startswith("tests/")]
    tests = [_reference_delivery(ref, excerpts) for ref in test_refs]
    candidate_paths = {candidate.path for candidate in pack.candidates}
    ranked = {_safe_path(path) for path in all_ranked_paths} if all_ranked_paths is not None else None
    diagnostic_by_path = {item.candidate_path: item for item in pack.selection_diagnostics}
    reference_paths = {ref["path"] for ref in _references(task)}
    diagnostics = []
    for path in sorted(reference_paths):
        diagnostic = diagnostic_by_path.get(path)
        candidate_status = ("IN_PACK" if path in candidate_paths else
                            "BEYOND_CANDIDATE_CAP" if ranked is not None and path in ranked else
                            "NO_RANKED_CANDIDATE" if ranked is not None else "UNKNOWN")
        diagnostics.append({
            "path": path, "candidate_status": candidate_status,
            "selected": path in selected,
            "proposed_ranges": [list(item) for item in diagnostic.proposed_source_ranges] if diagnostic else [],
            "omission_reason": diagnostic.omission_reason if diagnostic else None,
            "estimated_source_cost": diagnostic.estimated_source_cost if diagnostic else None,
        })
    return {
        "task_id": task_id, "split": split, "task_sha256": task["task_sha256"],
        "pack_fingerprint": pack.fingerprint, "mode": pack.mode.value,
        "context_budget": pack.max_context_tokens,
        "selected_source_tokens": pack.metrics.estimated_selected_tokens,
        "candidate_count": len(pack.candidates),
        "selected_excerpts": [{"path": item.path, "start_line": item.start_line,
                               "end_line": item.end_line, "complete_file": item.complete_file,
                               "truncated": item.truncated,
                               "estimated_source_tokens": estimator.estimate(item.text)} for item in excerpts],
        "redaction_categories": sorted(set(pack.redaction_categories)),
        "warnings": list(pack.warnings),
        "path_core_areas_covered": path_result["core_areas_covered"],
        "range_core_areas_full": sum(item["status"] == RANGE_FULL for item in areas),
        "range_core_areas_partial": sum(item["status"] == RANGE_PARTIAL for item in areas),
        "core_areas_total": len(areas), "areas": areas,
        "supporting": supporting, "test_evidence": tests,
        "explicit_anchors_retained": path_result["explicit_anchors_retained"],
        "explicit_anchors_missing": path_result["explicit_anchors_missing"],
        "unresolved_cases": task["unresolved"],
        "unreferenced_selected_paths": path_result["unreferenced_selected_paths"],
        "candidate_cap_omissions": [item["path"] for item in diagnostics
                                    if item["candidate_status"] == "BEYOND_CANDIDATE_CAP"],
        "context_budget_omissions": [item["path"] for item in diagnostics
                                     if "context_budget" in (item["omission_reason"] or "")],
        "reference_diagnostics": diagnostics,
        "structural_only": True,
    }


def run_development_baseline(repository_root: Path, corpus_path: Path,
                             dataset_path: Path) -> dict[str, Any]:
    """Clone the frozen source and run only the unchanged local context selector."""
    from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
    from middle_man.gateway.config import GatewayConfig
    from middle_man.gateway.context_builder import ContextBuilder
    from middle_man.gateway.relevance import RelevanceEngine
    from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint

    dataset = load_dataset(dataset_path)
    validate_dataset(dataset, corpus_path)
    source = dataset["source"]
    if selector_implementation_fingerprint() != source["selector_fingerprint"]:
        raise RuntimeError("production selector fingerprint changed")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    frozen_tasks = {item["task_id"]: item for item in corpus["tasks"]}
    if tuple(item["task_id"] for item in dataset["development_tasks"]) != DEVELOPMENT_IDS:
        raise RuntimeError("development task order differs from frozen plan")

    def git(root: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True, timeout=60).stdout.strip()

    with TemporaryDirectory(prefix="middle-man-evidence-delivery-") as temporary:
        snapshot = Path(temporary).resolve() / "source"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                        "--no-checkout", "-q", str(repository_root), str(snapshot)],
                       check=True, capture_output=True, text=True, timeout=120)
        git(snapshot, "checkout", "--detach", "-q", source["commit"])
        if (git(snapshot, "rev-parse", "HEAD") != source["commit"]
                or git(snapshot, "rev-parse", "HEAD^{tree}") != source["tree"]
                or git(snapshot, "status", "--porcelain=v1", "--untracked-files=all")
                or source_fingerprint(snapshot) != "6f360e98d7d87339129d0fde8725b6e26a03fcdf0f16f9a24d8c7a3f6a3db340"):
            raise RuntimeError("pinned source snapshot differs")
        config = GatewayConfig(snapshot, cache_writes_enabled=False)
        builder = ContextBuilder(config)
        citation_issues = inspect_development_citations(dataset, snapshot)
        tasks = []
        for task_id in DEVELOPMENT_IDS:
            pack = builder.build(frozen_tasks[task_id]["task"], mode="balanced", max_context_tokens=6000)
            index = builder.indexer.index()
            all_ranked = RelevanceEngine(index, config).find(pack.query, top_k=len(index.files))
            tasks.append(evaluate_delivery(dataset, task_id, pack,
                                           all_ranked_paths=(item.path for item in all_ranked)))
        if git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("local audit mutated the pinned source")
        return {"schema_version": 1, "scope": "DEVELOPMENT_ONLY", "model_calls": 0,
                "source_commit": source["commit"], "source_tree": source["tree"],
                "corpus_sha256": source["corpus_sha256"],
                "reference_dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                "selector_fingerprint": source["selector_fingerprint"],
                "mode": "balanced", "context_budget": 6000,
                "citation_span_issues": citation_issues,
                "tasks": tasks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-baseline", action="store_true",
                        help="save metadata-only development result under docs")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    report = run_development_baseline(
        root, root / "tests/fixtures/locator_shadow_corpus.json",
        root / "docs/source_selection_reference_dataset.json")
    if args.save_baseline:
        target = root / "docs/source_evidence_delivery_baseline.json"
        if target.is_symlink() or not target.resolve().is_relative_to(root / "docs"):
            raise RuntimeError("unsafe baseline report target")
        target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scope": report["scope"], "model_calls": report["model_calls"],
                      "citation_span_issues": report["citation_span_issues"],
                      "tasks": [{"task_id": task["task_id"],
                                 "path_core_areas_covered": task["path_core_areas_covered"],
                                 "range_core_areas_full": task["range_core_areas_full"],
                                 "range_core_areas_partial": task["range_core_areas_partial"],
                                 "core_areas_total": task["core_areas_total"],
                                 "selected_source_tokens": task["selected_source_tokens"]}
                                for task in report["tasks"]]}, sort_keys=True))


if __name__ == "__main__":
    main()
