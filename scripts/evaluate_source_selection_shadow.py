"""Compare production and code-anchor candidate selection on frozen local sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

from middle_man.experiments.source_selection import CodeAnchorContextBuilder, code_anchor_candidates
from middle_man.gateway.codex_benchmark.offline_locator import build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.locator_diagnostics import diagnose_locator
from middle_man.gateway.locator_shadow import load_shadow_corpus
from middle_man.gateway.relevance import ContextQuery, RelevanceEngine
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint
from scripts.measure_locator_shadow_corpus import (
    CORPUS_PATH, ROOT, SELECTOR_FINGERPRINT, SOURCE_FINGERPRINT, _git, _snapshot,
)


RESULT_PATH = ROOT / "docs" / "source_selection_shadow_result.json"
EXPERIMENT_PATH = ROOT / "middle_man" / "experiments" / "source_selection.py"
V2_PLAN_PATH = ROOT / "docs" / "codex_variance_calibration_v2_plan.json"
V2_RECEIPT_DIR = ROOT / "docs" / "codex_variance_calibration_v2_receipts"
RUBRIC_PATH = ROOT / "docs" / "locator_quality_prospective_plan.json"


def _measure(config: GatewayConfig, query: ContextQuery, index) -> tuple[dict, object, object]:
    current = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    candidate = CodeAnchorContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)

    def describe(pack) -> dict[str, object]:
        quality = diagnose_locator(pack, index, locator_tokens=0)
        return {
            "candidate_path_count": len(pack.candidates),
            "top_candidate_paths": [item.path for item in pack.candidates[:10]],
            "selected_paths": list(pack.selected_files),
            "candidate_source_tokens_estimate": pack.metrics.estimated_raw_candidate_tokens,
            "selected_source_tokens_estimate": pack.metrics.estimated_selected_tokens,
            "useful_query_terms": list(quality["useful_query_terms"]),
            "selected_matched_query_terms": list(quality["selected_matched_query_terms"]),
            "direct_supported_query_terms": list(quality["direct_supported_query_terms"]),
            "weak_only_supported_query_terms": list(quality["weak_only_supported_query_terms"]),
            "evidence_specificity_path_counts": quality["evidence_specificity_path_counts"],
            "direct_evidence_paths": quality["direct_evidence_paths"],
            "weak_only_paths": quality["weak_only_paths"],
            "selected_induced_graph_cluster_sizes": list(quality["selected_induced_graph_cluster_sizes"]),
            "test_selected_path_count": quality["test_selected_path_count"],
            "non_test_selected_path_count": quality["non_test_selected_path_count"],
            "selected_paths_without_novel_query_terms": quality["selected_paths_without_novel_query_terms"],
            "omission_reason_counts": dict(sorted(Counter(
                item.omission_reason for item in pack.selection_diagnostics
                if not item.selected and item.omission_reason).items())),
        }

    left, right = describe(current), describe(candidate)
    return {
        "current": left,
        "candidate": right,
        "added_paths": sorted(set(right["selected_paths"]) - set(left["selected_paths"])),
        "removed_paths": sorted(set(left["selected_paths"]) - set(right["selected_paths"])),
    }, current, candidate


def _case_paths(index, query: ContextQuery, current, candidate, paths: set[str]) -> list[dict]:
    engine = RelevanceEngine(index, GatewayConfig(Path(index.identity.root), cache_writes_enabled=False))
    full_current = engine.find(query, top_k=len(index.files))
    full_candidate = code_anchor_candidates(index, engine, query, len(index.files))
    ranked = ({item.path: (position, item) for position, item in enumerate(group, 1)}
              for group in (full_current, full_candidate))
    details = []
    for label, pack, lookup in zip(("current", "candidate"), (current, candidate), ranked):
        diagnostics = {item.candidate_path: item for item in pack.selection_diagnostics}
        selected = set(pack.selected_files)
        for path in sorted(paths):
            found = lookup.get(path)
            diagnostic = diagnostics.get(path)
            if not found and not diagnostic:
                continue
            position, relevance = found if found else (None, None)
            linked_imports = set(index.imports_for(path)) | set(index.importers_of(path))
            linked_tests = set(index.tests_for(path))
            details.append({
                "selector": label,
                "path": path,
                "is_test": index.get_file(path).is_test if index.get_file(path) else None,
                "candidate_rank": position,
                "within_candidate_cap": path in {item.path for item in pack.candidates},
                "score": relevance.score if relevance else None,
                "role": relevance.role if relevance else None,
                "matched_query_terms": list(relevance.matched_terms) if relevance else [],
                "matched_symbols": list(relevance.matched_symbols) if relevance else [],
                "signals": [f"{signal.kind}:{signal.term or signal.key}"
                            for signal in relevance.signals] if relevance else [],
                "exact_symbol_path_frequency": {
                    signal.key.removeprefix("symbol:"): len({symbol.path for symbol in
                        index.find_symbol(signal.key.removeprefix("symbol:"))})
                    for signal in relevance.signals if signal.kind == "exact_symbol"
                } if relevance else {},
                "import_neighbors_selected": sorted(linked_imports & selected),
                "related_tests_selected": sorted(linked_tests & selected),
                "selected": path in selected,
                "omission_reason": (diagnostic.omission_reason if diagnostic else
                                    "outside_candidate_cap" if position else "not_ranked"),
                "proposed_source_cost": diagnostic.estimated_source_cost if diagnostic else None,
                "proposed_source_ranges": [list(item) for item in diagnostic.proposed_source_ranges]
                if diagnostic else [],
                "budget_before": diagnostic.budget_before if diagnostic else None,
                "covered_signals": list(diagnostic.covered_signals) if diagnostic else [],
                "selected_phases": [item.phase for item in diagnostic.selected_range_phases]
                if diagnostic else [],
            })
    return details


def evaluate() -> dict[str, object]:
    corpus = load_shadow_corpus(CORPUS_PATH)
    v2_plan = json.loads(V2_PLAN_PATH.read_text(encoding="utf-8"))
    receipts = [json.loads((V2_RECEIPT_DIR / f"call-{n}.json").read_text(encoding="ascii"))
                for n in (2, 3)]
    if selector_implementation_fingerprint() != SELECTOR_FINGERPRINT or (
            corpus["selector_fingerprint"] != SELECTOR_FINGERPRINT):
        raise RuntimeError("production selector fingerprint differs from frozen corpus")
    with TemporaryDirectory(prefix="middle-man-source-selection-") as temporary:
        base = Path(temporary).resolve()
        if not base.is_relative_to(Path(gettempdir()).resolve()):
            raise RuntimeError("local snapshots escaped the system temp directory")
        corpus_root = _snapshot(corpus["source_commit"], base / "corpus")
        v2_root = _snapshot(v2_plan["source"]["commit"], base / "v2")
        if (_git(corpus_root, "rev-parse", "HEAD^{tree}") != corpus["source_tree_sha"]
                or source_fingerprint(corpus_root) != SOURCE_FINGERPRINT
                or _git(v2_root, "rev-parse", "HEAD^{tree}") != v2_plan["source"]["tree"]
                or source_fingerprint(v2_root) != v2_plan["source"]["content_fingerprint"]):
            raise RuntimeError("offline snapshot differs from source pin")
        corpus_config = GatewayConfig(corpus_root, cache_writes_enabled=False)
        corpus_index = RepositoryIndexer(corpus_config).index()
        rows = []
        for task in corpus["tasks"]:
            measured, _, _ = _measure(corpus_config, ContextQuery(task["task"]), corpus_index)
            rows.append({"task_id": task["task_id"], "archetype": task["archetype"],
                         "task_sha256": task["sha256"], **measured})

        case_entry = next(task for task in corpus["tasks"]
                          if task["sha256"] == v2_plan["task"]["task_sha256"])
        v2_config = GatewayConfig(v2_root, cache_writes_enabled=False)
        v2_index = RepositoryIndexer(v2_config).index()
        case_query = ContextQuery(case_entry["task"])
        case_measure, current, candidate = _measure(v2_config, case_query, v2_index)
        locator = build_offline_locator(v2_config, case_query)
        archived_paths = [receipt["locator"]["selected_paths"] for receipt in receipts]
        if (any(paths != list(current.selected_files) for paths in archived_paths)
                or any(receipt["locator"]["locator_hash"] != locator.sha256
                       for receipt in receipts)):
            raise RuntimeError("archived V2 locator does not reproduce locally")
        rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
        case_rubric = next(task["semantic_rubric"] for task in rubric["tasks"]
                           if task["task_id"] == case_entry["task_id"])
        source_refs = set(case_rubric["source_refs"])
        searched = {path for receipt in receipts for key in (
            "locator_paths_searched", "non_locator_paths_searched")
                    for path in receipt["locator"][key] if v2_index.get_file(path)}
        case_paths = (set(current.selected_files) | set(candidate.selected_files)
                      | source_refs | searched)
        case = {
            "task_id": case_entry["task_id"],
            "source_commit": v2_plan["source"]["commit"],
            "source_tree": v2_plan["source"]["tree"],
            "source_fingerprint": v2_plan["source"]["content_fingerprint"],
            "archived_locator_hash": locator.sha256,
            "archived_selected_paths_reproduced": True,
            "source_grounded_reference_basis": "Original prospective M01 semantic rubric source_refs; not Codex search behavior",
            "source_grounded_reference_paths": sorted(source_refs),
            "current_reference_paths_selected": sorted(source_refs & set(current.selected_files)),
            "candidate_reference_paths_selected": sorted(source_refs & set(candidate.selected_files)),
            "comparison": case_measure,
            "path_diagnostics": _case_paths(v2_index, case_query, current, candidate, case_paths),
        }
        if any(_git(root, "status", "--porcelain=v1", "--untracked-files=all")
               for root in (corpus_root, v2_root)):
            raise RuntimeError("offline selection changed a pinned snapshot")
    groups = defaultdict(list)
    for row in rows:
        groups[row["archetype"]].append(row)
    archetypes = {}
    for name, members in sorted(groups.items()):
        archetypes[name] = {
            "tasks": len(members),
            "changed_selections": sum(bool(row["added_paths"] or row["removed_paths"])
                                      for row in members),
            "direct_term_coverage_increased": sum(
                len(row["candidate"]["direct_supported_query_terms"])
                > len(row["current"]["direct_supported_query_terms"]) for row in members),
            "direct_term_coverage_decreased": sum(
                len(row["candidate"]["direct_supported_query_terms"])
                < len(row["current"]["direct_supported_query_terms"]) for row in members),
            "test_path_count_decreased": sum(
                row["candidate"]["test_selected_path_count"]
                < row["current"]["test_selected_path_count"] for row in members),
        }
    return {
        "schema_version": 1,
        "status": "OFFLINE_SHADOW_COMPARISON_NOT_PRODUCTION_POLICY",
        "source_commit": corpus["source_commit"],
        "source_tree": corpus["source_tree_sha"],
        "source_fingerprint": SOURCE_FINGERPRINT,
        "production_selector_fingerprint": SELECTOR_FINGERPRINT,
        "experiment_implementation_sha256": hashlib.sha256(EXPERIMENT_PATH.read_bytes()).hexdigest(),
        "budget": corpus["max_context_tokens"],
        "task_count": len(rows),
        "archetypes": archetypes,
        "tasks": rows,
        "archived_m01_case": case,
        "interpretation_limit": "Unlabeled tasks have no ground-truth relevance judgments; path and signal metrics are descriptive, not Codex usage or correctness.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="write the deterministic shadow report under docs")
    args = parser.parse_args()
    report = evaluate()
    if args.save:
        if RESULT_PATH.is_symlink() or not RESULT_PATH.resolve().is_relative_to(ROOT):
            raise RuntimeError("unsafe shadow report target")
        RESULT_PATH.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps({key: report[key] for key in (
            "status", "source_commit", "production_selector_fingerprint", "budget",
            "task_count", "archetypes")}, sort_keys=True))


if __name__ == "__main__":
    main()
