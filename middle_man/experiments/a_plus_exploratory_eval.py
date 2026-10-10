"""One-shot, source-free exploratory navigation comparison on frozen A-plus tasks."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from middle_man.experiments.a_plus_locator import build_a_plus_locator
from middle_man.experiments.locator_navigation_eval import parse_locator
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.offline_navigation import append_offline_locator, build_offline_locator
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "8a6dca9e3cfadd144f14e860d182ec44ac0faedc"
SOURCE_TREE = "467f280dfc781897099d726085974223cf9d6754"
SOURCE_FINGERPRINT = "bf192a20ad175d0714ddaeee4927c034f452fed5fb93c396acb0a94d515e3c9c"
CORPUS_SHA256 = "4580134b1ed60c4b75c3c951cda89e65e863ec32dbc70f39e192efaac69770af"
REFERENCE_SHA256 = "d9511d4d626e900faf570953fe6a80443217f086f00c9d62bb47ec2cff490b1c"
DESIGN_SHA256 = "0E9862460C492457BE09034E9A0C0FAE236C08893AC8D1CDDE9B7E3CC818F1CD"
SELECTOR_FINGERPRINT = "3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555"
A_PLUS_BLOB = "4a1bc5fc812d288582650a6f1fc6351f32d5e5f0"
APPENDIX_CEILING = 512
SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8", timeout=60,
    ).strip()


def _source_shape(root: Path, path: str) -> tuple[int, dict[str, tuple[int, int, str]]]:
    if (not path or path.startswith(("/", "\\")) or ":" in path or
            ".." in Path(path).parts or "\\" in path):
        raise ValueError("unsafe reference path")
    candidate = root / path
    if (not candidate.is_file() or
            any((root / Path(*Path(path).parts[:index])).is_symlink()
                for index in range(1, len(Path(path).parts) + 1)) or
            not candidate.resolve().is_relative_to(root.resolve())):
        raise ValueError("missing or unsafe pinned source path")
    lines = candidate.read_text(encoding="utf-8").splitlines()
    symbols: dict[str, tuple[int, int, str]] = {}
    if path.endswith(".py"):
        for node in ast.parse("\n".join(lines)).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                symbols[node.name] = (node.lineno, node.end_lineno, kind)
                if isinstance(node, ast.ClassDef):
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols[f"{node.name}.{child.name}"] = (
                                child.lineno, child.end_lineno, "method")
    return len(lines), symbols


def validate_span(span: list[object], shapes: dict[str, tuple[int, dict[str, tuple[int, int, str]]]]) -> None:
    if not isinstance(span, list) or len(span) != 4:
        raise ValueError("invalid reference span")
    path, symbol, first, last = span
    if path not in shapes or not isinstance(symbol, str) or not isinstance(first, int) or not isinstance(last, int):
        raise ValueError("missing pinned reference path or symbol")
    count, named = shapes[path]
    if not 1 <= first <= last <= count or symbol not in named or named[symbol][:2] != (first, last):
        raise ValueError("stale pinned reference symbol or line interval")


def load_frozen_inputs(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    corpus = json.loads((root / "tests/fixtures/a_plus_prospective_corpus.json").read_text(encoding="utf-8"))
    references = json.loads((root / "docs/a_plus_ai_proposed_references.json").read_text(encoding="utf-8"))
    if (corpus["source"]["commit"], corpus["source"]["tree"]) != (SOURCE_COMMIT, SOURCE_TREE):
        raise ValueError("corpus source pin changed")
    if corpus["corpus_sha256"] != CORPUS_SHA256 or canonical_hash(corpus["tasks"]) != CORPUS_SHA256:
        raise ValueError("frozen task corpus changed")
    if references["source"] != {"commit": SOURCE_COMMIT, "tree": SOURCE_TREE}:
        raise ValueError("reference source pin changed")
    if references["status"] != "AI_PROPOSED_SOURCE_GROUNDED_NOT_HUMAN_VALIDATED":
        raise ValueError("reference validation status changed")
    if references["reference_sha256"] != REFERENCE_SHA256 or canonical_hash(references["tasks"]) != REFERENCE_SHA256:
        raise ValueError("frozen reference tasks changed")
    if [item["task_id"] for item in references["tasks"]] != [item["task_id"] for item in corpus["tasks"]]:
        raise ValueError("task identities changed")
    if (len(corpus["tasks"]) != 16 or
            Counter(item["reference_status"] for item in references["tasks"]) !=
            {"COMPLETE_PROPOSED": 10, "PARTIAL_UNRESOLVED": 6}):
        raise ValueError("frozen reference coverage changed")
    for task, reference in zip(corpus["tasks"], references["tasks"], strict=True):
        if (reference["task_sha256"] != task["sha256"] or
                hashlib.sha256(task["task"].encode("utf-8")).hexdigest() != task["sha256"]):
            raise ValueError("task wording or reference identity changed")
    design = root / "docs/a_plus_locator_prospective_design.json"
    if hashlib.sha256(design.read_bytes()).hexdigest().upper() != DESIGN_SHA256:
        raise ValueError("frozen prospective design changed")
    if _git(root, "hash-object", "middle_man/experiments/a_plus_locator.py") != A_PLUS_BLOB:
        raise ValueError("A-plus implementation changed")
    if selector_implementation_fingerprint() != SELECTOR_FINGERPRINT:
        raise ValueError("production selector changed")
    if _git(root, "rev-parse", f"{SOURCE_COMMIT}^{{tree}}") != SOURCE_TREE:
        raise ValueError("pinned source tree changed")
    return corpus, references


def validate_references(root: Path, references: dict[str, Any]) -> dict[str, tuple[int, dict[str, tuple[int, int, str]]]]:
    paths = {span[0] for task in references["tasks"] for area in task["areas"]
             for option in area["alternatives"] for span in option}
    paths.update(span[0] for task in references["tasks"] for span in task["supporting_tests"])
    shapes = {path: _source_shape(root, path) for path in sorted(paths)}
    for task in references["tasks"]:
        for area in task["areas"]:
            if not area["alternatives"] or any(not option for option in area["alternatives"]):
                raise ValueError("empty proposed evidence alternative")
            for option in area["alternatives"]:
                for span in option:
                    validate_span(span, shapes)
        for span in task["supporting_tests"]:
            validate_span(span, shapes)
    return shapes


def _broad(hint: dict[str, Any], shapes: dict[str, tuple[int, dict[str, tuple[int, int, str]]]]) -> str | None:
    shape = shapes.get(hint["path"])
    if shape is None:
        return None
    count, named = shape
    first, last = hint["range"]
    if first == 1 and last >= count:
        return "WHOLE_FILE"
    symbol = hint["symbol"]
    if symbol in named and named[symbol][2] == "class":
        return "CLASS_RANGE"
    return None


def score_span(span: list[object], hints: list[dict[str, Any]],
               shapes: dict[str, tuple[int, dict[str, tuple[int, int, str]]]]) -> dict[str, bool]:
    path, symbol, first, last = span
    on_path = [hint for hint in hints if hint["path"] == path]
    intersecting = [hint for hint in on_path if hint["range"][0] <= last
                    and hint["range"][1] >= first]
    exact = [hint for hint in on_path if hint["symbol"] == symbol]
    precise = any(hint["symbol"] == symbol for hint in intersecting)
    return {
        "path_targeted": bool(on_path),
        "range_intersects": bool(intersecting),
        "exact_symbol_match": bool(exact),
        "precise_navigation": precise,
        "broad_overlap_only": not precise and any(_broad(hint, shapes) for hint in intersecting),
        "imprecise_overlap_only": bool(intersecting) and not precise,
    }


def score_arm(reference: dict[str, Any], hints: list[dict[str, Any]],
              shapes: dict[str, tuple[int, dict[str, tuple[int, int, str]]]]) -> dict[str, Any]:
    unique = list(dict.fromkeys(tuple(span) for area in reference["areas"]
                                 for option in area["alternatives"] for span in option))
    rows = {span: score_span(list(span), hints, shapes) for span in unique}
    summary = {"cited_spans": len(unique),
               "referenced_paths_targeted": len({span[0] for span in unique if rows[span]["path_targeted"]}),
               "referenced_paths_total": len({span[0] for span in unique})}
    for key in ("path_targeted", "range_intersects", "exact_symbol_match", "precise_navigation",
                "broad_overlap_only", "imprecise_overlap_only"):
        summary[key + "_spans"] = sum(row[key] for row in rows.values())
    summary["broad_whole_file_hints"] = sum(_broad(hint, shapes) == "WHOLE_FILE" for hint in hints)
    summary["broad_class_hints"] = sum(_broad(hint, shapes) == "CLASS_RANGE" for hint in hints)
    if reference["reference_status"] == "PARTIAL_UNRESOLVED":
        return {"span_diagnostics": summary, "areas": None, "complete_task_navigation": None,
                "scoring_status": "PARTIAL_SPAN_DIAGNOSTIC_ONLY"}
    if reference["reference_status"] != "COMPLETE_PROPOSED":
        raise ValueError("unknown reference status")
    areas = []
    for area in reference["areas"]:
        alternatives = [all(rows[tuple(span)]["precise_navigation"] for span in option)
                        for option in area["alternatives"]]
        areas.append({"area": area["area"], "complete": any(alternatives),
                      "alternative_complete": alternatives})
    return {"span_diagnostics": summary, "areas": areas,
            "complete_task_navigation": all(item["complete"] for item in areas),
            "scoring_status": "COMPLETE_PROPOSED_STRUCTURAL_ONLY"}


def _safe_hints(root: Path, hints: list[dict[str, Any]],
                shapes: dict[str, tuple[int, dict[str, tuple[int, int, str]]]], *,
                supplemental: bool) -> None:
    redactor = SecretRedactor()
    config = GatewayConfig(root, cache_writes_enabled=False)
    for hint in hints:
        path = hint["path"]
        symbol = hint["symbol"]
        if (config.relative_path(path) != path or redactor.redact(path).text != path or
                not SYMBOL.fullmatch(symbol or "x") or
                redactor.redact(symbol or "").text != (symbol or "")):
            raise ValueError("unsafe locator path or symbol")
        if path not in shapes:
            shapes[path] = _source_shape(root, path)
        count, named = shapes[path]
        first, last = hint["range"]
        if not 1 <= first <= last <= count:
            raise ValueError("locator span is stale or out of bounds")
        if supplemental and (hint["symbol"] not in named or
                             named[hint["symbol"]] != (first, last, named[hint["symbol"]][2]) or
                             named[hint["symbol"]][2] not in {"function", "method"}):
            raise ValueError("supplement is not an exact pinned method/function")


def compare_task(task: dict[str, Any], reference: dict[str, Any], baseline: Any, plus: Any,
                 shapes: dict[str, tuple[int, dict[str, tuple[int, int, str]]]], root: Path) -> dict[str, Any]:
    if (baseline.sha256 != hashlib.sha256(baseline.text.encode("utf-8")).hexdigest() or
            plus.sha256 != hashlib.sha256(plus.text.encode("utf-8")).hexdigest()):
        raise ValueError("locator content hash mismatch")
    if (plus.baseline_sha256 != baseline.sha256 or
            (plus.text != baseline.text and not plus.text.startswith(baseline.text + "\n"))):
        raise ValueError("A-plus changed production A hint bytes")
    redactor = SecretRedactor()
    if redactor.redact(baseline.text).text != baseline.text or redactor.redact(plus.text).text != plus.text:
        raise ValueError("unsafe locator text")
    a_hints, b_hints = parse_locator(baseline.text), parse_locator(plus.text)
    if b_hints[:len(a_hints)] != a_hints:
        raise ValueError("A-plus removed or reordered production hints")
    _safe_hints(root, a_hints, shapes, supplemental=False)
    _safe_hints(root, b_hints[len(a_hints):], shapes, supplemental=True)
    additions = b_hints[len(a_hints):]
    if len(additions) != len(plus.supplemental_hints) or len(additions) > 3:
        raise ValueError("supplement count violates frozen rule")
    if [(item["path"], *item["range"], item["symbol"]) for item in additions] != list(plus.supplemental_hints):
        raise ValueError("supplement metadata differs from locator text")
    new_paths = {item["path"] for item in additions} - {item["path"] for item in a_hints}
    if len(new_paths) != plus.new_file_count or len(new_paths) > 2:
        raise ValueError("new-file count violates frozen rule")
    estimate = HeuristicTokenEstimator()
    a_tokens = estimate.estimate(append_offline_locator("", baseline.text))
    b_tokens = estimate.estimate(append_offline_locator("", plus.text))
    if (a_tokens != plus.baseline_appendix_estimated_tokens or
            b_tokens != plus.appendix_estimated_tokens):
        raise ValueError("full-appendix accounting differs")
    if a_tokens > APPENDIX_CEILING:
        if not plus.feasibility_failure or additions or plus.text != baseline.text:
            raise ValueError("over-budget A must be preserved without supplements")
    elif plus.feasibility_failure or b_tokens > APPENDIX_CEILING:
        raise ValueError("A-plus exceeded feasible appendix ceiling")
    a_score = score_arm(reference, a_hints, shapes)
    b_score = score_arm(reference, b_hints, shapes)
    gained = lost = None
    if reference["reference_status"] == "COMPLETE_PROPOSED":
        gained = [item["area"] for old, item in zip(a_score["areas"], b_score["areas"], strict=True)
                  if not old["complete"] and item["complete"]]
        lost = [item["area"] for old, item in zip(a_score["areas"], b_score["areas"], strict=True)
                if old["complete"] and not item["complete"]]
    anchors = task["explicit_paths_supplied"]
    anchor_before = {path for path in anchors if any(item["path"] == path for item in a_hints)}
    anchor_after = {path for path in anchors if any(item["path"] == path for item in b_hints)}
    if not anchor_before <= anchor_after:
        raise ValueError("explicit production path anchor lost")
    citations = {tuple(span) for area in reference["areas"] for option in area["alternatives"]
                 for span in option}
    supplement_diagnostics = []
    for hint in additions:
        matches = [span for span in citations if span[0] == hint["path"]]
        precise = any(score_span(list(span), [hint], shapes)["precise_navigation"] for span in matches)
        supplement_diagnostics.append({"path": hint["path"], "range": hint["range"],
                                       "symbol": hint["symbol"],
                                       "reference_relation": ("EXACT_CITED_SPAN" if precise else
                                                              "CITED_PATH_OTHER_SYMBOL" if matches else
                                                              "UNREFERENCED_UNKNOWN"),
                                       "misleading_judgment": "AI_REVIEW_PENDING"})
    return {
        "task_id": task["task_id"], "archetype": task["archetype"],
        "reference_status": reference["reference_status"], "task_sha256": task["sha256"],
        "a_locator_sha256": baseline.sha256, "a_plus_locator_sha256": plus.sha256,
        "a_appendix_estimated_tokens": a_tokens, "a_plus_appendix_estimated_tokens": b_tokens,
        "additional_estimated_tokens": b_tokens - a_tokens,
        "supplement_count": len(additions), "new_file_count": len(new_paths),
        "supplements": supplement_diagnostics, "skip_reasons": dict(plus.skip_reasons),
        "budget_feasible": a_tokens <= APPENDIX_CEILING and b_tokens <= APPENDIX_CEILING,
        "baseline_over_budget": a_tokens > APPENDIX_CEILING,
        "baseline_preserved": True, "explicit_anchor_paths_retained": len(anchor_before),
        "explicit_anchor_paths_lost": len(anchor_before - anchor_after),
        "a": a_score, "a_plus": b_score,
        "newly_navigable_areas": gained, "lost_navigable_areas": lost,
        "unresolved_interpretations": reference["unresolved_interpretations"],
        "provider_usage": None, "external_inference_calls": 0,
    }


def run_once(repository: Path = ROOT) -> dict[str, Any]:
    corpus, references = load_frozen_inputs(repository)
    with TemporaryDirectory(prefix="middle-man-a-plus-exploratory-") as temporary:
        snapshot = Path(temporary) / "source"
        subprocess.run(["git", "clone", "--no-hardlinks",
                        "--no-checkout", "-q", str(repository), str(snapshot)],
                       check=True, capture_output=True, text=True, timeout=120)
        _git(snapshot, "checkout", "--detach", "-q", SOURCE_COMMIT)
        before = (_git(snapshot, "rev-parse", "HEAD"), _git(snapshot, "rev-parse", "HEAD^{tree}"),
                  _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"),
                  source_fingerprint(snapshot))
        if before != (SOURCE_COMMIT, SOURCE_TREE, "", SOURCE_FINGERPRINT):
            raise RuntimeError("disposable evaluation source identity mismatch: " +
                               repr({"head": before[0], "tree": before[1],
                                     "clean": not bool(before[2]), "fingerprint": before[3]}))
        shapes = validate_references(snapshot, references)
        config = GatewayConfig(snapshot, cache_writes_enabled=False)
        index = RepositoryIndexer(config).index()
        if index.identity.head != SOURCE_COMMIT or index.changed_paths:
            raise RuntimeError("index is not pinned to clean source")
        outcomes = []
        for task, reference in zip(corpus["tasks"], references["tasks"], strict=True):
            query = ContextQuery(task["task"])
            baseline = build_offline_locator(config, query)
            plus = build_a_plus_locator(config, index, query, baseline, expected_head=SOURCE_COMMIT)
            outcomes.append(compare_task(task, reference, baseline, plus, shapes, snapshot))
        after = (_git(snapshot, "rev-parse", "HEAD"), _git(snapshot, "rev-parse", "HEAD^{tree}"),
                 _git(snapshot, "status", "--porcelain=v1", "--untracked-files=all"),
                 source_fingerprint(snapshot))
        if after != before:
            raise RuntimeError("evaluation mutated pinned source")
    complete = [item for item in outcomes if item["reference_status"] == "COMPLETE_PROPOSED"]
    gains = Counter(item["archetype"] for item in complete for _ in item["newly_navigable_areas"])
    return {
        "schema": "middle_man.a_plus_exploratory_offline_result.v1",
        "status": "EXPLORATORY_AI_REFERENCES_NOT_HUMAN_VALIDATED",
        "source": {"commit": SOURCE_COMMIT, "tree": SOURCE_TREE, "fingerprint": SOURCE_FINGERPRINT},
        "input_hashes": {"corpus_tasks_sha256": CORPUS_SHA256,
                         "reference_tasks_sha256": REFERENCE_SHA256,
                         "design_sha256": DESIGN_SHA256,
                         "a_plus_git_blob": A_PLUS_BLOB,
                         "selector_fingerprint": SELECTOR_FINGERPRINT},
        "scoring_rule": "Precise span = one same-path hint intersecting cited lines with exact qualified symbol; every span in an option and any complete option per area; partial tasks have span diagnostics only.",
        "outcomes": outcomes,
        "summary": {"task_count": len(outcomes), "complete_reference_tasks": len(complete),
                    "partial_reference_tasks": len(outcomes) - len(complete),
                    "new_complete_areas": sum(len(item["newly_navigable_areas"]) for item in complete),
                    "lost_complete_areas": sum(len(item["lost_navigable_areas"]) for item in complete),
                    "gain_archetypes": dict(sorted(gains.items())),
                    "budget_feasible_tasks": sum(item["budget_feasible"] for item in outcomes),
                    "baseline_over_budget_tasks": sum(item["baseline_over_budget"] for item in outcomes),
                    "supplement_count": sum(item["supplement_count"] for item in outcomes)},
        "confirmatory_gate": "NOT_EVALUABLE_NO_INDEPENDENT_HUMAN_REVIEW_AND_PARTIAL_REFERENCES",
        "repository_integrity": "PASS", "provider_usage": None,
        "codex_benchmark_inference_calls": 0, "claude_benchmark_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_once()
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
