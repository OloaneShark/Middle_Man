"""Measure fixed source-free locator unions without reference scoring or selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from middle_man.experiments.locator_navigation_eval import SOURCE_FINGERPRINT
from middle_man.experiments.navigation_preservation import (
    checked_hints, format_hints, measure, preservation_scenario,
)
from middle_man.experiments.source_selection_reference_eval import DEVELOPMENT_IDS
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


SOURCE_COMMIT = "0680a1cb8812d35b17ebd628de7ffba95798da7f"
SOURCE_TREE = "6276b4a959bc93df8bb82cdde0bfc371d2c99770"
CORPUS_SHA256 = "6b1be495325413f5fc5e1e4bd53cbfc93a784c8f0365515e8f6a3e6d2ad803b5"
REFERENCE_SHA256 = "ef000d32fb4e7d2344fd0461dc3a95be763771588acea71295a8ea08a1fc9317"
SELECTOR_FINGERPRINT = "3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555"
ARTIFACT_SHA256 = {
    "A": "22730f8892df9de09c757cc69cc02abcd715cf5afa46f1a3d66e0aad04e4f141",
    "B": "4e83f7a6df2b8f1c96a4c45261794187ad679240d25937ad895d5edcf9e86a4f",
    "C": "5b986ed9062da72db63735eb0da584b382a82d53b558246f9e237802714aeda0",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=60).stdout.strip()


def _read_pins(corpus_path: Path, reference_path: Path,
               artifact_paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    corpus_bytes = corpus_path.read_bytes()
    if (hashlib.sha256(corpus_bytes).hexdigest() != CORPUS_SHA256
            or hashlib.sha256(reference_path.read_bytes()).hexdigest() != REFERENCE_SHA256
            or selector_implementation_fingerprint() != SELECTOR_FINGERPRINT):
        raise RuntimeError("frozen corpus, reference, or selector fingerprint differs")
    corpus = json.loads(corpus_bytes)
    if (corpus["source_commit"] != SOURCE_COMMIT or corpus["source_tree_sha"] != SOURCE_TREE
            or corpus["selector_fingerprint"] != SELECTOR_FINGERPRINT
            or len(corpus["tasks"]) != 24
            or any(hashlib.sha256(item["task"].encode("utf-8")).hexdigest() != item["sha256"]
                   for item in corpus["tasks"])):
        raise RuntimeError("frozen task hash or source identity differs")
    tasks = {item["task_id"]: item for item in corpus["tasks"]}
    artifacts = {}
    for name, path in artifact_paths.items():
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ARTIFACT_SHA256[name]:
            raise RuntimeError(f"frozen {name} artifact checksum differs")
        artifact = json.loads(raw)
        if (artifact["source_commit"] != SOURCE_COMMIT
                or artifact["source_tree"] != SOURCE_TREE
                or artifact["selector_fingerprint"] != SELECTOR_FINGERPRINT
                or artifact["corpus_sha256"] != CORPUS_SHA256
                or artifact["reference_dataset_sha256"] != REFERENCE_SHA256
                or artifact["scope"] != "DEVELOPMENT_ONLY"
                or [row["task_id"] for row in artifact["tasks"]] != list(DEVELOPMENT_IDS)
                or any(row["task_sha256"] != tasks[row["task_id"]]["sha256"]
                       for row in artifact["tasks"])):
            raise RuntimeError(f"frozen {name} artifact task/source identity differs")
        artifacts[name] = artifact
    return tasks, artifacts


def _original(records: list[dict[str, object]], config: GatewayConfig,
              expected_sha: str, expected_tokens: int, expected_paths: list[str]) -> tuple:
    hints = checked_hints(records, config)
    text = format_hints(hints)
    measured = measure(text)
    if (measured["locator_sha256"] != expected_sha
            or measured["appendix_estimated_tokens"] != expected_tokens
            or list(dict.fromkeys(hint.path for hint in hints)) != expected_paths):
        raise RuntimeError("original locator reconstruction differs")
    return hints


def run_preservation(root: Path, corpus_path: Path, reference_path: Path,
                     artifact_paths: dict[str, Path]) -> dict[str, Any]:
    _, artifacts = _read_pins(corpus_path, reference_path, artifact_paths)
    before_primary = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    rows = []
    with TemporaryDirectory(prefix="middle-man-navigation-preservation-") as temporary:
        snapshot = Path(temporary) / "source"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                        "--no-checkout", "-q", str(root), str(snapshot)],
                       check=True, capture_output=True, text=True, timeout=120)
        _git(snapshot, "checkout", "--detach", "-q", SOURCE_COMMIT)
        if (_git(snapshot, "rev-parse", "HEAD") != SOURCE_COMMIT
                or _git(snapshot, "rev-parse", "HEAD^{tree}") != SOURCE_TREE
                or _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all")
                or source_fingerprint(snapshot) != SOURCE_FINGERPRINT):
            raise RuntimeError("pinned source snapshot differs")
        config = GatewayConfig(snapshot, cache_writes_enabled=False)
        for index, task_id in enumerate(DEVELOPMENT_IDS):
            a = artifacts["A"]["tasks"][index]
            b = artifacts["B"]["tasks"][index]
            c = artifacts["C"]["tasks"][index]
            A = _original(a["hints"], config, a["locator_sha256"],
                          a["model_visible_appendix_estimated_tokens"], a["selected_paths"])
            B = _original(b["candidate_hints"], config, b["candidate_locator_sha256"],
                          b["candidate"]["model_visible_appendix_estimated_tokens"],
                          b["candidate_selected_paths"])
            C = _original(c["C_hints"], config, c["C_locator_sha256"],
                          c["C"]["model_visible_appendix_estimated_tokens"], c["selected_paths"])
            if tuple(dict.fromkeys(item.path for item in B)) != tuple(dict.fromkeys(item.path for item in C)):
                raise RuntimeError("B/C selected path order differs")
            budget = a["model_visible_appendix_estimated_tokens"]
            bc = preservation_scenario(B, (C,), appendix_budget=budget)
            abc = preservation_scenario(A, (B, C), appendix_budget=budget)
            rows.append({"task_id": task_id, "task_sha256": a["task_sha256"],
                         "originals": {
                             "A": {"locator_sha256": a["locator_sha256"],
                                   "appendix_estimated_tokens": budget,
                                   "distinct_paths": len(set(a["selected_paths"])),
                                   "hint_count": len(A)},
                             "B": {"locator_sha256": b["candidate_locator_sha256"],
                                   "appendix_estimated_tokens": b["candidate"]["model_visible_appendix_estimated_tokens"],
                                   "distinct_paths": len(set(b["candidate_selected_paths"])),
                                   "hint_count": len(B)},
                             "C": {"locator_sha256": c["C_locator_sha256"],
                                   "appendix_estimated_tokens": c["C"]["model_visible_appendix_estimated_tokens"],
                                   "distinct_paths": len(set(c["selected_paths"])),
                                   "hint_count": len(C)}},
                         "B_plus_C": bc, "A_plus_B_plus_C": abc})
        if _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("preservation analysis mutated pinned source")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all") != before_primary:
        raise RuntimeError("preservation analysis mutated primary repository")
    return {"schema_version": 1, "scope": "DEVELOPMENT_ONLY", "model_calls": 0,
            "analysis": "SOURCE_FREE_PRESERVATION_FEASIBILITY_NO_REFERENCE_SCORING",
            "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "selector_fingerprint": SELECTOR_FINGERPRINT,
            "corpus_sha256": CORPUS_SHA256, "reference_dataset_sha256": REFERENCE_SHA256,
            "artifact_sha256": ARTIFACT_SHA256,
            "production_format_unchanged": True, "tasks": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-result", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = run_preservation(root, root / "tests/fixtures/locator_shadow_corpus.json",
                              root / "docs/source_selection_reference_dataset.json",
                              {"A": root / "docs/source_free_locator_navigation_audit.json",
                               "B": root / "docs/navigation_only_shadow_result.json",
                               "C": root / "docs/navigation_hint_precision_result.json"})
    if args.save_result:
        target = root / "docs/navigation_hint_preservation_feasibility.json"
        if target.is_symlink() or not target.resolve().is_relative_to(root / "docs"):
            raise RuntimeError("unsafe result target")
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"scope": result["scope"], "model_calls": 0,
                      "tasks": [{"id": row["task_id"],
                                 "B+C": row["B_plus_C"]["appendix_estimated_tokens"],
                                 "A+B+C": row["A_plus_B_plus_C"]["appendix_estimated_tokens"],
                                 "budget": row["originals"]["A"]["appendix_estimated_tokens"]}
                                for row in result["tasks"]]}))


if __name__ == "__main__":
    main()
