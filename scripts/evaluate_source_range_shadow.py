"""Reproduce the frozen six-task source-range shadow comparison without inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from middle_man.experiments.source_range_shadow import SymbolRangeShadowBuilder
from middle_man.experiments.source_selection_reference_eval import (
    DEVELOPMENT_IDS, evaluate_delivery, load_dataset, validate_dataset,
)
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import RelevanceEngine
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FINGERPRINT = "6f360e98d7d87339129d0fde8725b6e26a03fcdf0f16f9a24d8c7a3f6a3db340"
DISPUTED_AREAS = frozenset({("N01", "ownership"), ("G02", "range_selection")})
STATUS_RANK = {"FILE_MISSING": 0, "RANGE_MISSING": 1, "RANGE_PARTIAL": 2, "RANGE_FULL": 3}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


def _stable_audit(audit: dict) -> dict:
    return {key: value for key, value in audit.items() if key != "pack_fingerprint"}


def _coordinates(audit: dict) -> set[tuple[str, int, int]]:
    return {(item["path"], item["start_line"], item["end_line"])
            for item in audit["selected_excerpts"]}


def _sensitivity(tasks: list[dict], *, candidate: bool) -> dict[str, int]:
    full = total = 0
    side = "candidate" if candidate else "current"
    for task in tasks:
        for area in task[side]["areas"]:
            if (task["task_id"], area["id"]) in DISPUTED_AREAS:
                continue
            total += 1
            full += area["status"] == "RANGE_FULL"
    return {"full": full, "total": total}


def run_shadow() -> dict:
    corpus_path = ROOT / "tests/fixtures/locator_shadow_corpus.json"
    dataset_path = ROOT / "docs/source_selection_reference_dataset.json"
    baseline_path = ROOT / "docs/source_evidence_delivery_baseline.json"
    rule_path = ROOT / "docs/SOURCE_RANGE_SHADOW_RULE.md"
    implementation_path = ROOT / "middle_man/experiments/source_range_shadow.py"
    dataset = load_dataset(dataset_path)
    validate_dataset(dataset, corpus_path)
    source = dataset["source"]
    if selector_implementation_fingerprint() != source["selector_fingerprint"]:
        raise RuntimeError("production selector fingerprint differs from frozen input")
    frozen_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if (frozen_baseline["scope"] != "DEVELOPMENT_ONLY" or frozen_baseline["model_calls"] != 0
            or frozen_baseline["source_commit"] != source["commit"]
            or frozen_baseline["source_tree"] != source["tree"]
            or frozen_baseline["reference_dataset_sha256"] != hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            or [task["task_id"] for task in frozen_baseline["tasks"]] != list(DEVELOPMENT_IDS)
            or [task["range_core_areas_full"] for task in frozen_baseline["tasks"]] != [3, 1, 1, 0, 0, 1]):
        raise RuntimeError("historical development baseline or pin differs")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    tasks_by_id = {task["task_id"]: task for task in corpus["tasks"]}
    before_primary = _git(ROOT, "status", "--porcelain=v1", "--untracked-files=all")
    with TemporaryDirectory(prefix="middle-man-source-range-shadow-") as temporary:
        snapshot = Path(temporary).resolve() / "source"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                        "--no-checkout", "-q", str(ROOT), str(snapshot)], check=True,
                       capture_output=True, text=True, timeout=120)
        _git(snapshot, "checkout", "--detach", "-q", source["commit"])
        if (_git(snapshot, "rev-parse", "HEAD") != source["commit"]
                or _git(snapshot, "rev-parse", "HEAD^{tree}") != source["tree"]
                or source_fingerprint(snapshot) != SOURCE_FINGERPRINT
                or _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all")):
            raise RuntimeError("source snapshot differs from frozen pin")

        config = GatewayConfig(snapshot, cache_writes_enabled=False)
        rows = []
        for task_id in DEVELOPMENT_IDS:
            task = tasks_by_id[task_id]["task"]
            current_builder = ContextBuilder(config)
            shadow_builder = SymbolRangeShadowBuilder(config)
            current_pack = current_builder.build(task, mode="balanced", max_context_tokens=6000)
            candidate_pack = shadow_builder.build(task, mode="balanced", max_context_tokens=6000)
            if (current_pack.candidates != candidate_pack.candidates
                    or current_pack.query != candidate_pack.query
                    or current_pack.mode != candidate_pack.mode
                    or current_pack.max_context_tokens != candidate_pack.max_context_tokens):
                raise RuntimeError(f"candidate parity failure: {task_id}")
            index = current_builder.indexer.index()
            all_ranked = tuple(item.path for item in RelevanceEngine(index, config).find(
                current_pack.query, top_k=len(index.files)))
            current = _stable_audit(evaluate_delivery(dataset, task_id, current_pack,
                                                      all_ranked_paths=all_ranked))
            candidate = _stable_audit(evaluate_delivery(dataset, task_id, candidate_pack,
                                                        all_ranked_paths=all_ranked))
            historical = _stable_audit(frozen_baseline["tasks"][len(rows)])
            if current != historical:
                raise RuntimeError(f"production baseline failed to reproduce: {task_id}")
            old_ranges = _coordinates(current)
            new_ranges = _coordinates(candidate)
            rows.append({
                "task_id": task_id, "current": current, "candidate": candidate,
                "proposal_changes": shadow_builder.proposal_changes,
                "added_delivered_ranges": [list(item) for item in sorted(new_ranges - old_ranges)],
                "removed_delivered_ranges": [list(item) for item in sorted(old_ranges - new_ranges)],
                "candidate_parity": True,
            })
        if _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("shadow experiment modified source snapshot")
    if _git(ROOT, "status", "--porcelain=v1", "--untracked-files=all") != before_primary:
        raise RuntimeError("shadow experiment modified primary repository before artifact write")

    baseline_full = sum(row["current"]["range_core_areas_full"] for row in rows)
    candidate_full = sum(row["candidate"]["range_core_areas_full"] for row in rows)
    core_regressions = [(row["task_id"], before["id"]) for row in rows
                        for before, after in zip(row["current"]["areas"], row["candidate"]["areas"])
                        if before["status"] == "RANGE_FULL" and after["status"] != "RANGE_FULL"]
    test_regressions = [(row["task_id"], before["path"], before["reference_lines"])
                        for row in rows for before, after in zip(
                            row["current"]["test_evidence"], row["candidate"]["test_evidence"])
                        if STATUS_RANK[after["status"]] < STATUS_RANK[before["status"]]]
    n01 = next(row for row in rows if row["task_id"] == "N01")
    e01 = next(row for row in rows if row["task_id"] == "E01")
    safe = all(row["candidate"]["selected_source_tokens"] <= 6000 and
               not any("UNSAFE_OR_UNREADABLE_SOURCE" in warning for warning in row["candidate"]["warnings"])
               for row in rows)
    accepted = (candidate_full > baseline_full and not core_regressions and not test_regressions
                and n01["candidate"]["range_core_areas_full"] == 3
                and e01["candidate"]["range_core_areas_full"] == 1
                and not e01["candidate"]["explicit_anchors_missing"] and safe)
    return {
        "schema_version": 1, "scope": "DEVELOPMENT_ONLY", "model_calls": 0,
        "source_commit": source["commit"], "source_tree": source["tree"],
        "source_fingerprint": SOURCE_FINGERPRINT,
        "selector_fingerprint": source["selector_fingerprint"],
        "corpus_sha256": source["corpus_sha256"],
        "reference_dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "baseline_artifact_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "rule_sha256": hashlib.sha256(rule_path.read_bytes()).hexdigest(),
        "shadow_implementation_sha256": hashlib.sha256(implementation_path.read_bytes()).hexdigest(),
        "mode": "balanced", "context_budget": 6000,
        "baseline_reproduced": True,
        "aggregate": {"current_full_core_areas": baseline_full,
                      "candidate_full_core_areas": candidate_full,
                      "core_area_regressions": core_regressions,
                      "test_evidence_regressions": test_regressions,
                      "candidate_within_budget_and_safe": safe,
                      "sensitivity_excluded_areas": sorted([list(item) for item in DISPUTED_AREAS]),
                      "sensitivity_current": _sensitivity(rows, candidate=False),
                      "sensitivity_candidate": _sensitivity(rows, candidate=True),
                      "decision": "ACCEPT_FOR_FURTHER_OFFLINE_RESEARCH" if accepted else "REJECT"},
        "tasks": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="save metadata-only JSON under docs")
    args = parser.parse_args()
    result = run_shadow()
    if args.save:
        target = ROOT / "docs/source_range_shadow_result.json"
        if target.is_symlink() or not target.resolve().is_relative_to(ROOT / "docs"):
            raise RuntimeError("unsafe shadow result target")
        target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scope": result["scope"], "model_calls": result["model_calls"],
                      "aggregate": result["aggregate"],
                      "tasks": [{"task_id": row["task_id"],
                                 "full": [row["current"]["range_core_areas_full"],
                                          row["candidate"]["range_core_areas_full"]],
                                 "tokens": [row["current"]["selected_source_tokens"],
                                            row["candidate"]["selected_source_tokens"]],
                                 "proposal_changes": len(row["proposal_changes"])}
                                for row in result["tasks"]]}, sort_keys=True))


if __name__ == "__main__":
    main()
