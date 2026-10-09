"""Run the frozen, development-only navigation shadow without model calls."""

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
from middle_man.experiments.navigation_only_shadow import build_navigation_shadow
from middle_man.experiments.source_selection_reference_eval import (
    DEVELOPMENT_IDS, load_dataset,
)
from middle_man.gateway.codex_benchmark.offline_locator import build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


BASELINE_COVERAGE = {"N01": 3, "M02": 1, "C02": 1, "T01": 0, "G02": 0, "E01": 1}


def _validate_development_pins(dataset: dict[str, Any], corpus_path: Path) -> dict[str, Any]:
    """Validate frozen provenance without opening reserved reference labels."""
    corpus_bytes = corpus_path.read_bytes()
    corpus = json.loads(corpus_bytes)
    source = dataset["source"]
    if (dataset["schema_version"] != 1
            or dataset["judgment_status"] != "PROPOSED_SOURCE_GROUNDED_NOT_HUMAN_VALIDATED"
            or len(corpus["tasks"]) != 24
            or hashlib.sha256(corpus_bytes).hexdigest() != source["corpus_sha256"]
            or source["commit"] != corpus["source_commit"]
            or source["tree"] != corpus["source_tree_sha"]
            or source["selector_fingerprint"] != corpus["selector_fingerprint"]
            or any(hashlib.sha256(item["task"].encode()).hexdigest() != item["sha256"]
                   for item in corpus["tasks"])):
        raise RuntimeError("frozen corpus provenance differs")
    frozen = {item["task_id"]: item for item in corpus["tasks"]}
    if tuple(task["task_id"] for task in dataset["development_tasks"]) != DEVELOPMENT_IDS:
        raise RuntimeError("development task order differs")
    for task in dataset["development_tasks"]:
        original = frozen[task["task_id"]]
        if (task["task_sha256"] != original["sha256"]
                or task["archetype"] != original["archetype"]):
            raise RuntimeError("development reference pin differs")
    return frozen


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=60).stdout.strip()


def _test_refs(result: dict[str, Any]) -> tuple[int, int]:
    refs = [ref for area in result["areas"] for option in area["options"]
            for ref in option["references"] if ref["path"].startswith("tests/")]
    return sum(ref["path_targeted"] for ref in refs), sum(ref["navigable"] for ref in refs)


def _navigable_ids(result: dict[str, Any]) -> list[str]:
    return [area["id"] for area in result["areas"] if area["navigable"]]


def _metrics(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in (
        "areas_navigable", "areas_total", "references_path_targeted",
        "references_range_intersects", "references_symbol_match", "broad_hints",
        "specific_hints", "locator_characters", "locator_estimated_tokens",
        "model_visible_appendix_estimated_tokens")}


def run_shadow(root: Path, corpus_path: Path, dataset_path: Path,
               baseline_path: Path) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    frozen = _validate_development_pins(dataset, corpus_path)
    source = dataset["source"]
    if selector_implementation_fingerprint() != source["selector_fingerprint"]:
        raise RuntimeError("production selector fingerprint changed")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if (baseline["scope"] != "DEVELOPMENT_ONLY"
            or baseline["source_commit"] != source["commit"]
            or baseline["source_tree"] != source["tree"]
            or baseline["selector_fingerprint"] != source["selector_fingerprint"]
            or baseline["reference_dataset_sha256"] != hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            or baseline["corpus_sha256"] != source["corpus_sha256"]
            or [task["task_id"] for task in baseline["tasks"]] != list(DEVELOPMENT_IDS)):
        raise RuntimeError("baseline navigation audit differs from frozen inputs")
    rows = []
    with TemporaryDirectory(prefix="middle-man-navigation-shadow-") as temporary:
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
        for task_id, recorded in zip(DEVELOPMENT_IDS, baseline["tasks"]):
            task = development_task(dataset, task_id)
            query = ContextQuery(frozen[task_id]["task"])
            pack = builder.build(query, mode="balanced", max_context_tokens=6000)
            locator = build_offline_locator(config, query)
            if pack.fingerprint != locator.pack_fingerprint:
                raise RuntimeError("production baseline packs disagree")
            index = builder.indexer.index()
            lengths = {item.path: item.line_count for item in index.files
                       if item.line_count is not None and item.line_count > 0}
            before = evaluate_navigation(task, locator.text, file_lengths=lengths)
            if (before["locator_sha256"] != recorded["locator_sha256"]
                    or before["areas_navigable"] != BASELINE_COVERAGE[task_id]
                    or before["model_visible_appendix_estimated_tokens"]
                    != recorded["model_visible_appendix_estimated_tokens"]):
                raise RuntimeError(f"baseline reproduction differs: {task_id}")
            shadow = build_navigation_shadow(
                config, index, pack.query,
                max_appendix_tokens=recorded["model_visible_appendix_estimated_tokens"])
            if shadow.candidate_paths != tuple(item.path for item in pack.candidates):
                raise RuntimeError(f"top-50 candidate pool differs: {task_id}")
            after = evaluate_navigation(task, shadow.text, file_lengths=lengths)
            if (after["model_visible_appendix_estimated_tokens"] != shadow.appendix_estimated_tokens
                    or after["locator_sha256"] != shadow.sha256):
                raise RuntimeError("shadow locator measurement differs")
            refs = {ref["path"] for area in task["areas"] for option in area["options"] for ref in option}
            refs.update(ref["path"] for ref in task["supporting"])
            anchors = set(task["explicit_anchors"])
            selected = set(after["selected_paths"])
            rows.append({"task_id": task_id, "task_sha256": frozen[task_id]["sha256"],
                         "baseline_locator_sha256": before["locator_sha256"],
                         "candidate_locator_sha256": shadow.sha256,
                         "candidate_pool_identical": True, "candidate_pool_paths": list(shadow.candidate_paths),
                         "baseline": _metrics(before), "candidate": _metrics(after),
                         "baseline_navigable_areas": _navigable_ids(before),
                         "candidate_navigable_areas": _navigable_ids(after),
                         "baseline_test_refs": list(_test_refs(before)),
                         "candidate_test_refs": list(_test_refs(after)),
                         "baseline_explicit_anchors_retained": sorted(anchors & set(before["selected_paths"])),
                         "candidate_explicit_anchors_retained": sorted(anchors & selected),
                         "candidate_hints": parse_locator(shadow.text),
                         "candidate_selected_paths": list(shadow.selected_paths),
                         "candidate_symbol_hints": shadow.symbol_hints,
                         "candidate_file_fallback_hints": shadow.file_fallback_hints,
                         "candidate_budget_prevented_paths": list(shadow.budget_prevented_paths),
                         "candidate_missing_reference_paths": after["referenced_paths_missing"],
                         "candidate_out_of_cap_reference_paths": sorted(refs - set(shadow.candidate_paths)),
                         "candidate_unreferenced_selected_paths_UNKNOWN": sorted(selected - refs)})
        if _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("shadow audit mutated pinned source")
    baseline_total = sum(row["baseline"]["areas_navigable"] for row in rows)
    candidate_total = sum(row["candidate"]["areas_navigable"] for row in rows)
    conditions = {
        "strict_area_gain": candidate_total > baseline_total,
        "no_previously_navigable_area_lost": all(
            set(row["baseline_navigable_areas"]) <= set(row["candidate_navigable_areas"]) for row in rows),
        "N01_retains_3_of_3": rows[0]["candidate"]["areas_navigable"] == 3,
        "E01_retains_1_of_1_and_anchor": (rows[-1]["candidate"]["areas_navigable"] == 1
                                          and rows[-1]["candidate_explicit_anchors_retained"]
                                          == rows[-1]["baseline_explicit_anchors_retained"]),
        "test_focused_evidence_not_weakened": all(
            row["candidate_test_refs"][0] >= row["baseline_test_refs"][0]
            and row["candidate_test_refs"][1] >= row["baseline_test_refs"][1]
            for row in rows if development_task(dataset, row["task_id"])["archetype"] == "TEST_FOCUSED"),
        "appendix_within_each_baseline": all(
            row["candidate"]["model_visible_appendix_estimated_tokens"]
            <= row["baseline"]["model_visible_appendix_estimated_tokens"] for row in rows),
        "safety_and_repository_integrity": True,
    }
    return {"schema_version": 1, "scope": "DEVELOPMENT_ONLY",
            "analysis": "PREREGISTERED_SHADOW", "model_calls": 0,
            "source_commit": source["commit"], "source_tree": source["tree"],
            "source_fingerprint": SOURCE_FINGERPRINT,
            "corpus_sha256": source["corpus_sha256"],
            "reference_dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "baseline_audit_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            "selector_fingerprint": source["selector_fingerprint"],
            "baseline_areas_navigable": baseline_total, "candidate_areas_navigable": candidate_total,
            "areas_total": sum(row["candidate"]["areas_total"] for row in rows),
            "decision_conditions": conditions,
            "decision": "ELIGIBLE_FOR_FURTHER_INVESTIGATION" if all(conditions.values()) else "REJECTED",
            "tasks": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-result", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = run_shadow(root, root / "tests/fixtures/locator_shadow_corpus.json",
                        root / "docs/source_selection_reference_dataset.json",
                        root / "docs/source_free_locator_navigation_audit.json")
    if args.save_result:
        target = root / "docs/navigation_only_shadow_result.json"
        if target.is_symlink() or not target.resolve().is_relative_to(root / "docs"):
            raise RuntimeError("unsafe shadow result target")
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"scope": result["scope"], "baseline": result["baseline_areas_navigable"],
                      "candidate": result["candidate_areas_navigable"],
                      "decision": result["decision"], "model_calls": 0}))


if __name__ == "__main__":
    main()
