"""Pinned A/B/C comparison of within-file navigation precision, local only."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from middle_man.experiments.locator_navigation_eval import (
    SOURCE_FINGERPRINT, development_task, evaluate_navigation, parse_locator,
)
from middle_man.experiments.navigation_hint_precision import refine_navigation_hints
from middle_man.experiments.navigation_only_shadow import build_navigation_shadow
from middle_man.experiments.source_selection_reference_eval import DEVELOPMENT_IDS, load_dataset
from middle_man.gateway.codex_benchmark.offline_locator import build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.models import RepositoryIndex
from middle_man.gateway.relevance import ContextQuery
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint
from scripts.evaluate_navigation_only_shadow import _git, _metrics, _navigable_ids, _validate_development_pins


PRODUCTION_AUDIT_SHA256 = "22730f8892df9de09c757cc69cc02abcd715cf5afa46f1a3d66e0aad04e4f141"
REJECTED_SHADOW_SHA256 = "4e83f7a6df2b8f1c96a4c45261794187ad679240d25937ad895d5edcf9e86a4f"


def _broad_class_or_file(result: dict[str, Any], index: RepositoryIndex) -> int:
    count = 0
    for hint in result["hints"]:
        classes = {symbol.qualified_name for symbol in index.symbols_in_file(hint["path"])
                   if symbol.kind == "class"}
        count += hint["specificity"] == "BROAD_WHOLE_FILE" or hint["symbol"] in classes
    return count


def _summary(result: dict[str, Any], index: RepositoryIndex) -> dict[str, Any]:
    return {**_metrics(result), "broad_class_or_whole_file_hints": _broad_class_or_file(result, index),
            "selected_path_count": len(result["selected_paths"]),
            "incorrect_source_locations": result["wrong_range_or_symbol"]}


def _new_implementation_area(task: dict[str, Any], before: dict[str, Any],
                             after: dict[str, Any]) -> bool:
    old = set(_navigable_ids(before))
    for area, scored in zip(task["areas"], after["areas"]):
        if area["id"] not in old and scored["navigable"] and any(
                any(not ref["path"].startswith("tests/") for ref in option)
                for option in area["options"]):
            return True
    return False


def run_precision(root: Path, corpus_path: Path, dataset_path: Path,
                  production_path: Path, shadow_path: Path) -> dict[str, Any]:
    if (hashlib.sha256(production_path.read_bytes()).hexdigest() != PRODUCTION_AUDIT_SHA256
            or hashlib.sha256(shadow_path.read_bytes()).hexdigest() != REJECTED_SHADOW_SHA256):
        raise RuntimeError("frozen navigation audit input changed")
    dataset = load_dataset(dataset_path)
    frozen = _validate_development_pins(dataset, corpus_path)
    source = dataset["source"]
    if selector_implementation_fingerprint() != source["selector_fingerprint"]:
        raise RuntimeError("production selector fingerprint changed")
    production = json.loads(production_path.read_text(encoding="utf-8"))
    rejected = json.loads(shadow_path.read_text(encoding="utf-8"))
    if ([item["task_id"] for item in production["tasks"]] != list(DEVELOPMENT_IDS)
            or [item["task_id"] for item in rejected["tasks"]] != list(DEVELOPMENT_IDS)
            or production["source_commit"] != source["commit"]
            or rejected["source_commit"] != source["commit"]
            or production["source_tree"] != source["tree"]
            or rejected["source_tree"] != source["tree"]):
        raise RuntimeError("historical navigation scope or source differs")
    rows = []
    with TemporaryDirectory(prefix="middle-man-navigation-precision-") as temporary:
        snapshot = Path(temporary) / "source"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                        "--no-checkout", "-q", str(root), str(snapshot)],
                       check=True, capture_output=True, text=True, timeout=120)
        _git(snapshot, "checkout", "--detach", "-q", source["commit"])
        if (_git(snapshot, "rev-parse", "HEAD") != source["commit"]
                or _git(snapshot, "rev-parse", "HEAD^{tree}") != source["tree"]
                or _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all")
                or source_fingerprint(snapshot) != SOURCE_FINGERPRINT):
            raise RuntimeError("pinned source snapshot differs")
        config = GatewayConfig(snapshot, cache_writes_enabled=False)
        builder = ContextBuilder(config)
        for task_id, a_record, b_record in zip(DEVELOPMENT_IDS, production["tasks"], rejected["tasks"]):
            task = development_task(dataset, task_id)
            query = ContextQuery(frozen[task_id]["task"])
            pack = builder.build(query, mode="balanced", max_context_tokens=6000)
            a = build_offline_locator(config, query)
            if pack.fingerprint != a.pack_fingerprint:
                raise RuntimeError("production pack mismatch")
            index = builder.indexer.index()
            budget = a_record["model_visible_appendix_estimated_tokens"]
            b = build_navigation_shadow(config, index, pack.query, max_appendix_tokens=budget)
            if (a.sha256 != a_record["locator_sha256"]
                    or b.sha256 != b_record["candidate_locator_sha256"]
                    or b.selected_paths != tuple(b_record["candidate_selected_paths"])
                    or b.candidate_paths != tuple(b_record["candidate_pool_paths"])
                    or b.candidate_paths != tuple(item.path for item in pack.candidates)):
                raise RuntimeError(f"A/B frozen reproduction differs: {task_id}")
            c = refine_navigation_hints(config, index, pack.query, b, max_appendix_tokens=budget)
            if c.selected_paths != b.selected_paths:
                raise RuntimeError("precision candidate changed selected path order")
            lengths = {item.path: item.line_count for item in index.files
                       if item.line_count is not None and item.line_count > 0}
            scored = [evaluate_navigation(task, text, file_lengths=lengths)
                      for text in (a.text, b.text, c.text)]
            if ([item["areas_navigable"] for item in scored[:2]]
                    != [a_record["areas_navigable"], b_record["candidate"]["areas_navigable"]]
                    or scored[1]["model_visible_appendix_estimated_tokens"]
                    != b_record["candidate"]["model_visible_appendix_estimated_tokens"]):
                raise RuntimeError(f"A/B evaluation differs: {task_id}")
            anchors = set(task["explicit_anchors"])
            explicit_path_retained = anchors <= set(c.selected_paths)
            b_hints = parse_locator(b.text)
            c_hints = parse_locator(c.text)
            explicit_symbol_preserved = all(
                original == updated for original, updated in zip(b_hints, c_hints)
                if original["symbol"] and original["symbol"] in pack.query.task)
            rows.append({
                "task_id": task_id, "task_sha256": frozen[task_id]["sha256"],
                "A": _summary(scored[0], index), "B": _summary(scored[1], index),
                "C": _summary(scored[2], index),
                "A_navigable_areas": _navigable_ids(scored[0]),
                "B_navigable_areas": _navigable_ids(scored[1]),
                "C_navigable_areas": _navigable_ids(scored[2]),
                "A_locator_sha256": a.sha256, "B_locator_sha256": b.sha256,
                "C_locator_sha256": c.sha256,
                "B_C_identical_selected_paths": b.selected_paths == c.selected_paths,
                "selected_paths": list(c.selected_paths), "C_hints": c_hints,
                "C_substitutions": [{"path": path, "start_line": start, "end_line": end,
                                     "symbol": symbol, "support": evidence}
                                    for path, start, end, symbol, evidence in c.substitutions],
                "ambiguous_paths_retained": list(c.ambiguous_paths),
                "budget_blocked_paths_retained": list(c.budget_blocked_paths),
                "new_implementation_area": _new_implementation_area(task, scored[1], scored[2]),
                "new_supported_function_match": (
                    scored[2]["references_symbol_match"] > scored[1]["references_symbol_match"]
                    and bool(c.substitutions)),
                "explicit_path_anchors_retained": explicit_path_retained,
                "explicit_symbol_anchors_preserved": explicit_symbol_preserved,
            })
        if _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("precision study mutated pinned source")
    conditions = {
        "no_A_area_lost": all(set(row["A_navigable_areas"]) <= set(row["C_navigable_areas"])
                              for row in rows),
        "no_B_area_lost": all(set(row["B_navigable_areas"]) <= set(row["C_navigable_areas"])
                              for row in rows),
        "additional_supported_gain": any(row["new_implementation_area"]
                                         or row["new_supported_function_match"] for row in rows),
        "explicit_anchors_preserved": all(row["explicit_path_anchors_retained"]
                                          and row["explicit_symbol_anchors_preserved"] for row in rows),
        "appendix_within_A": all(row["C"]["model_visible_appendix_estimated_tokens"]
                                 <= row["A"]["model_visible_appendix_estimated_tokens"] for row in rows),
        "B_C_paths_identical": all(row["B_C_identical_selected_paths"] for row in rows),
        "safety_and_repository_integrity": True,
    }
    return {"schema_version": 1, "scope": "DEVELOPMENT_ONLY", "model_calls": 0,
            "source_commit": source["commit"], "source_tree": source["tree"],
            "selector_fingerprint": source["selector_fingerprint"],
            "corpus_sha256": source["corpus_sha256"],
            "reference_dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "production_audit_sha256": PRODUCTION_AUDIT_SHA256,
            "rejected_shadow_sha256": REJECTED_SHADOW_SHA256,
            "A_areas_navigable": sum(row["A"]["areas_navigable"] for row in rows),
            "B_areas_navigable": sum(row["B"]["areas_navigable"] for row in rows),
            "C_areas_navigable": sum(row["C"]["areas_navigable"] for row in rows),
            "decision_conditions": conditions,
            "decision": "ELIGIBLE_FOR_FURTHER_RESEARCH" if all(conditions.values()) else "REJECTED",
            "tasks": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-result", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = run_precision(root, root / "tests/fixtures/locator_shadow_corpus.json",
                           root / "docs/source_selection_reference_dataset.json",
                           root / "docs/source_free_locator_navigation_audit.json",
                           root / "docs/navigation_only_shadow_result.json")
    if args.save_result:
        target = root / "docs/navigation_hint_precision_result.json"
        if target.is_symlink() or not target.resolve().is_relative_to(root / "docs"):
            raise RuntimeError("unsafe result target")
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"scope": result["scope"], "A": result["A_areas_navigable"],
                      "B": result["B_areas_navigable"], "C": result["C_areas_navigable"],
                      "decision": result["decision"], "model_calls": 0}))


if __name__ == "__main__":
    main()
