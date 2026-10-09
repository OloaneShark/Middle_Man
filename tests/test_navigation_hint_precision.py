"""Synthetic safety and pinned parity tests for the precision-only shadow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from middle_man.experiments.navigation_hint_precision import refine_navigation_hints
from middle_man.experiments.navigation_only_shadow import ShadowLocator
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import IndexedFile, IndexStats, RepositoryIdentity, RepositoryIndex, Symbol
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.tokens import HeuristicTokenEstimator
from scripts.evaluate_navigation_hint_precision import run_precision


ROOT = Path(__file__).resolve().parents[1]


def _index(root: Path, files: list[tuple[str, tuple[Symbol, ...]]]) -> RepositoryIndex:
    records = []
    for path, symbols in files:
        source = root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("source line\n" * 20, encoding="utf-8")
        records.append(IndexedFile(path, source.name, ".py", "Python", source.stat().st_size,
                                   None, 0, 20, True, path.startswith("tests/"), "parsed",
                                   symbols=symbols))
    return RepositoryIndex(RepositoryIdentity(str(root), "synthetic", False, None, None, "now"),
                           tuple(records), (), IndexStats())


def _shadow(text: str) -> ShadowLocator:
    paths = tuple(line[2:].split(":", 1)[0] for line in text.splitlines())
    estimate = HeuristicTokenEstimator()
    return ShadowLocator(text, hashlib.sha256(text.encode()).hexdigest(), estimate.estimate(text),
                         estimate.estimate(append_offline_locator("", text)), paths, paths, (), 0, len(paths))


def _refine(root: Path, index: RepositoryIndex, task: str, text: str, *,
            budget: int = 200) -> object:
    return refine_navigation_hints(GatewayConfig(root), index, ContextQuery(task),
                                   _shadow(text), max_appendix_tokens=budget)


def test_unique_function_term_replaces_misleading_class_hint(tmp_path: Path) -> None:
    path = "src/relevance.py"
    index = _index(tmp_path, [(path, (
        Symbol(path, "Engine", "Engine", "class", 1, 20),
        Symbol(path, "find", "Engine.find", "method", 8, 12),
        Symbol(path, "reset", "Engine.reset", "method", 14, 16),
    ))])
    text = "- src/relevance.py:1-20 (Engine)"
    result = _refine(tmp_path, index, "How does find locate candidates?", text)
    assert result.text == "- src/relevance.py:8-12 (Engine.find)"
    assert result.selected_paths == (path,)
    assert result.substitutions[0][-1] == "task_lexical"


def test_class_only_evidence_does_not_narrow(tmp_path: Path) -> None:
    path = "src/context.py"
    index = _index(tmp_path, [(path, (
        Symbol(path, "ContextBuilder", "ContextBuilder", "class", 1, 20),
        Symbol(path, "build", "ContextBuilder.build", "method", 4, 7),
        Symbol(path, "expand", "ContextBuilder.expand", "method", 9, 13),
    ))])
    text = "- src/context.py:1-20 (ContextBuilder)"
    assert _refine(tmp_path, index, "Explain context selection", text).text == text


def test_ambiguous_equal_scores_retain_original_deterministically(tmp_path: Path) -> None:
    path = "src/a.py"
    index = _index(tmp_path, [(path, (
        Symbol(path, "release_one", "Owner.release_one", "method", 3, 5),
        Symbol(path, "release_two", "Owner.release_two", "method", 8, 10),
    ))])
    text = "- src/a.py:1-20 (Owner)"
    first = _refine(tmp_path, index, "Explain release", text)
    second = _refine(tmp_path, index, "Explain release", text)
    assert first == second and first.text == text
    assert first.ambiguous_paths == (path,)


def test_explicit_qualified_anchor_outranks_lexical_competitor(tmp_path: Path) -> None:
    path = "src/a.py"
    index = _index(tmp_path, [(path, (
        Symbol(path, "choose_victim", "Policy.choose_victim", "method", 3, 6),
        Symbol(path, "release_victim", "Policy.release_victim", "method", 9, 12),
    ))])
    result = _refine(tmp_path, index, "Explain Policy.choose_victim and release", "- src/a.py:1-20")
    assert result.text == "- src/a.py:3-6 (Policy.choose_victim)"
    assert result.substitutions[0][-1] == "explicit_anchor"


def test_invalid_range_or_sensitive_symbol_never_emitted(tmp_path: Path) -> None:
    path = "src/a.py"
    index = _index(tmp_path, [(path, (
        Symbol(path, "release", "Owner.release", "method", 21, 25),
        Symbol(path, "token", "TOKEN=privatevalue", "method", 3, 5),
    ))])
    text = "- src/a.py:1-20"
    result = _refine(tmp_path, index, "release token", text)
    assert result.text == text and "privatevalue" not in result.text


def test_budget_keeps_original_and_path_order(tmp_path: Path) -> None:
    first, second = "src/a.py", "tests/test_a.py"
    index = _index(tmp_path, [(first, (Symbol(first, "release", "LongOwner.release", "method", 4, 6),)),
                              (second, (Symbol(second, "release", "Test.release", "function", 7, 9),))])
    text = "- src/a.py:1-20\n- tests/test_a.py:1-20"
    budget = _shadow(text).appendix_estimated_tokens
    result = _refine(tmp_path, index, "release", text, budget=budget)
    assert result.text == text
    assert result.selected_paths == (first, second)
    assert result.budget_blocked_paths == (first, second)


def test_unsafe_or_changed_b_paths_fail_closed(tmp_path: Path) -> None:
    index = _index(tmp_path, [("src/a.py", ())])
    with pytest.raises(ValueError):
        _refine(tmp_path, index, "task", "- ../outside.py:1-10")
    old = _shadow("- src/a.py:1-20")
    tampered = ShadowLocator(old.text, old.sha256, old.estimated_tokens,
                             old.appendix_estimated_tokens, ("other.py",), (), (), 0, 1)
    with pytest.raises(ValueError, match="exactly one hint"):
        refine_navigation_hints(GatewayConfig(tmp_path), index, ContextQuery("task"),
                                tampered, max_appendix_tokens=200)


def test_sensitive_b_path_is_rejected(tmp_path: Path) -> None:
    path = "PASSWORD=privatevalue.py"
    index = _index(tmp_path, [(path, ())])
    with pytest.raises(ValueError, match="unsafe B-selected"):
        _refine(tmp_path, index, "task", f"- {path}:1-20")


def test_pinned_abc_is_development_only_and_reproducible() -> None:
    result = run_precision(ROOT, ROOT / "tests/fixtures/locator_shadow_corpus.json",
                           ROOT / "docs/source_selection_reference_dataset.json",
                           ROOT / "docs/source_free_locator_navigation_audit.json",
                           ROOT / "docs/navigation_only_shadow_result.json")
    assert result == json.loads((ROOT / "docs/navigation_hint_precision_result.json").read_text())
    assert result["model_calls"] == 0 and result["scope"] == "DEVELOPMENT_ONLY"
    assert [row["task_id"] for row in result["tasks"]] == ["N01", "M02", "C02", "T01", "G02", "E01"]
    assert all(row["B_C_identical_selected_paths"] for row in result["tasks"])
    serialized = json.dumps(result)
    assert '"task":' not in serialized and '"text":' not in serialized
