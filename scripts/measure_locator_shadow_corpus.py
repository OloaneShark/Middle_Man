"""Run a pinned, unlabeled locator-quality corpus without model inference."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint
from middle_man.gateway.locator_shadow import (
    anchor_positions, evaluate_locator_quality_shadow, feature_distributions,
    load_shadow_corpus, numeric_features,
)
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint
from scripts.measure_locator_quality import (
    LOSS_HEAD, LOSS_LOCATOR_SHA256, LOSS_SELECTED_PATHS, LOSS_TASK,
    LOSS_TASK_SHA256, ROOT, TASK_A_ARTIFACT, _measure,
)


CORPUS_PATH = ROOT / "tests" / "fixtures" / "locator_shadow_corpus.json"
SOURCE_COMMIT = "0680a1cb8812d35b17ebd628de7ffba95798da7f"
SOURCE_TREE_SHA = "6276b4a959bc93df8bb82cdde0bfc371d2c99770"
SELECTOR_FINGERPRINT = "3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555"
SOURCE_FINGERPRINT = "6f360e98d7d87339129d0fde8725b6e26a03fcdf0f16f9a24d8c7a3f6a3db340"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


def _snapshot(commit: str, destination: Path) -> Path:
    subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                    "--no-checkout", "-q", str(ROOT), str(destination)],
                   check=True, capture_output=True, text=True, timeout=120)
    _git(destination, "checkout", "--detach", "-q", commit)
    if _git(destination, "rev-parse", "HEAD") != commit or _git(
            destination, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("pinned snapshot is not clean at its requested commit")
    return destination


def _validated_anchors(base: Path) -> dict[str, dict[str, object]]:
    task_a = next(task for task in TASKS if task.id == "preemption-v4")
    _, task_a_root, task_a_fingerprint = prepare_pair(task_a, base / "task_a", None)
    task_a_report = _measure(task_a_root, task_a.prompt)
    artifact = json.loads(TASK_A_ARTIFACT.read_text(encoding="utf-8"))
    frozen_pair = artifact["pairs"][0]
    frozen_locator = frozen_pair["optimized"]["offline_locator_audit"]
    if (task_a_fingerprint != frozen_pair["source_tree_fingerprint"] or
            task_a_report["locator_sha256"] != frozen_locator["locator_sha256"] or
            tuple(row["path"] for row in task_a_report["quality"]["selected_paths"])
            != tuple(frozen_locator["selected_paths"])):
        raise RuntimeError("Task A diagnostic no longer matches the frozen valid pair")
    task_a_report["source_fingerprint"] = task_a_fingerprint
    task_a_report["source_commit"] = task_a.source_ref

    loss_root = _snapshot(LOSS_HEAD, base / "production_loss")
    loss_report = _measure(loss_root, LOSS_TASK)
    if (loss_report["task_sha256"] != LOSS_TASK_SHA256 or
            loss_report["locator_sha256"] != LOSS_LOCATOR_SHA256 or
            tuple(row["path"] for row in loss_report["quality"]["selected_paths"])
            != LOSS_SELECTED_PATHS):
        raise RuntimeError("production loss diagnostic no longer matches its locked pair")
    loss_report["source_fingerprint"] = source_fingerprint(loss_root)
    loss_report["source_commit"] = LOSS_HEAD
    return {"TASK_A_WIN": task_a_report, "PRODUCTION_LOSS": loss_report}


def run_shadow_corpus() -> dict[str, object]:
    corpus = load_shadow_corpus(CORPUS_PATH)
    if (corpus["source_commit"] != SOURCE_COMMIT or
            corpus["source_tree_sha"] != SOURCE_TREE_SHA or
            corpus["selector_fingerprint"] != SELECTOR_FINGERPRINT or
            selector_implementation_fingerprint() != SELECTOR_FINGERPRINT or
            _git(ROOT, "rev-parse", f"{SOURCE_COMMIT}^{{tree}}") != SOURCE_TREE_SHA):
        raise RuntimeError("shadow source or selector pin has changed")
    with TemporaryDirectory(prefix="middle-man-locator-shadow-") as temporary:
        base = Path(temporary).resolve()
        if not base.is_relative_to(Path(gettempdir()).resolve()):
            raise RuntimeError("shadow snapshots escaped the system temp directory")
        shadow_root = _snapshot(SOURCE_COMMIT, base / "shadow_source")
        if _git(shadow_root, "rev-parse", "HEAD^{tree}") != SOURCE_TREE_SHA:
            raise RuntimeError("shadow snapshot tree differs from pin")
        fingerprint = source_fingerprint(shadow_root)
        if fingerprint != SOURCE_FINGERPRINT:
            raise RuntimeError("shadow source content fingerprint differs from pin")
        tasks = []
        for entry in corpus["tasks"]:
            measurement = _measure(shadow_root, entry["task"])
            tasks.append({
                "task_id": entry["task_id"],
                "archetype": entry["archetype"],
                "task_sha256": entry["sha256"],
                "explicit_paths_supplied": entry["explicit_paths_supplied"],
                "explicit_symbols_supplied": entry["explicit_symbols_supplied"],
                "locator_sha256": measurement["locator_sha256"],
                "quality": measurement["quality"],
                "features": numeric_features(measurement["quality"]),
            })
        anchors = _validated_anchors(base)
        rows = [entry["features"] for entry in tasks]
        anchor_features = {
            name: numeric_features(entry["quality"]) for name, entry in anchors.items()
        }
        if _git(shadow_root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("shadow snapshot was modified by local measurement")
        distributions = feature_distributions(rows)
        decisions = []
        manual_review = []
        for entry in tasks:
            features = entry["features"]
            decision, reasons = evaluate_locator_quality_shadow(features)
            decisions.append({
                "task_id": entry["task_id"], "decision": decision, "reason_codes": reasons,
            })
            review_reasons = []
            if decision == "PASS":
                if features["directory_dispersion"] > distributions["directory_dispersion"]["p75"]:
                    review_reasons.append("HIGH_DIRECTORY_DISPERSION")
                if (features["median_to_top_score_ratio"] <
                        distributions["median_to_top_score_ratio"]["p25"]):
                    review_reasons.append("LOW_SCORE_CONCENTRATION")
            if decision == "BYPASS":
                if entry["explicit_paths_supplied"]:
                    review_reasons.append("EXPLICIT_PATH")
                if features["unique_exact_symbol_paths"]:
                    review_reasons.append("UNIQUE_EXACT_SYMBOL")
            if review_reasons:
                manual_review.append({
                    "task_id": entry["task_id"], "decision": decision,
                    "reason_codes": tuple(review_reasons),
                })
        return {
            "schema_version": 1,
            "source_commit": SOURCE_COMMIT,
            "source_tree_sha": SOURCE_TREE_SHA,
            "source_fingerprint": fingerprint,
            "selector_fingerprint": SELECTOR_FINGERPRINT,
            "archetype_counts": dict(sorted(Counter(
                entry["archetype"] for entry in tasks).items())),
            "shadow_tasks": tasks,
            "distributions": distributions,
            "anchors": {
                name: {
                    "source_commit": entry["source_commit"],
                    "source_fingerprint": entry["source_fingerprint"],
                    "task_sha256": entry["task_sha256"],
                    "locator_sha256": entry["locator_sha256"],
                    "features": anchor_features[name],
                    "positions": anchor_positions(rows, anchor_features[name]),
                }
                for name, entry in anchors.items()
            },
            "shadow_policy": {
                "name": "coherence_and_exact_symbol_ambiguity",
                "decisions": decisions,
                "counts": {name: sum(item["decision"] == name for item in decisions)
                           for name in ("PASS", "BYPASS", "UNCERTAIN")},
                "anchors": {
                    name: dict(zip(("decision", "reason_codes"),
                                   evaluate_locator_quality_shadow(features)))
                    for name, features in anchor_features.items()
                },
                "manual_review": manual_review,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true",
                        help="include all source-free per-task quality metadata")
    parser.add_argument("--save-full", action="store_true",
                        help="write the complete deterministic JSON to docs/locator_quality_shadow_results.json")
    args = parser.parse_args()
    report = run_shadow_corpus()
    if args.save_full:
        target = ROOT / "docs" / "locator_quality_shadow_results.json"
        if target.is_symlink() or not target.resolve().is_relative_to(ROOT):
            raise RuntimeError("unsafe shadow report target")
        target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if not args.full:
        report["shadow_tasks"] = [
            {key: value for key, value in entry.items() if key != "quality"}
            for entry in report["shadow_tasks"]
        ]
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
