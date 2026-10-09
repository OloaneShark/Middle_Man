"""Local-only safety and parity checks for the frozen navigation shadow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from middle_man.experiments.navigation_only_shadow import build_navigation_shadow
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import IndexedFile, IndexStats, RepositoryIdentity, RepositoryIndex, Symbol
from middle_man.gateway.relevance import ContextQuery, MatchSignal, RelevanceCandidate, RelevanceEngine
from middle_man.gateway.tokens import HeuristicTokenEstimator
from scripts.evaluate_navigation_only_shadow import _validate_development_pins, run_shadow


ROOT = Path(__file__).resolve().parents[1]


def _index(root: Path, specs: list[tuple[str, tuple[Symbol, ...]]]) -> RepositoryIndex:
    files = []
    for path, symbols in specs:
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("TOP_SECRET_SOURCE_TEXT\n" * 10, encoding="utf-8")
        files.append(IndexedFile(path, file.name, ".py", "Python", file.stat().st_size,
                                 None, 0, 10, True, path.startswith("tests/"), "parsed",
                                 symbols=symbols))
    return RepositoryIndex(RepositoryIdentity(str(root), "synthetic", False, None, None, "now"),
                           tuple(files), (), IndexStats())


def _candidate(path: str, *, symbols: tuple[str, ...] = (),
               signals: tuple[MatchSignal, ...] = ()) -> RelevanceCandidate:
    return RelevanceCandidate(path, 100, "PRIMARY", symbols, (), signals=signals)


def _mock_find(monkeypatch: pytest.MonkeyPatch, candidates: tuple[RelevanceCandidate, ...]) -> None:
    def find(self: RelevanceEngine, query: ContextQuery, *, top_k: int | None = None,
             minimum_score: float | None = None) -> tuple[RelevanceCandidate, ...]:
        assert top_k == 50 and minimum_score is None
        return candidates
    monkeypatch.setattr(RelevanceEngine, "find", find)


def test_rank_order_symbol_location_and_duplicate_deduplication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "src/a.py"
    first = Symbol(path, "method", "Owner.method", "method", 3, 5)
    second = Symbol(path, "other", "Owner.other", "method", 7, 9)
    index = _index(tmp_path, [(path, (first, second)), ("src/b.py", ())])
    exact = MatchSignal("exact_symbol", "symbol:Owner.method", 95, "exact")
    _mock_find(monkeypatch, (_candidate(path, symbols=("Owner.other", "Owner.method"), signals=(exact,)),
                            _candidate(path), _candidate("src/b.py")))
    config = GatewayConfig(tmp_path)
    query = ContextQuery("Owner.method")
    one = build_navigation_shadow(config, index, query, max_appendix_tokens=200)
    two = build_navigation_shadow(config, index, query, max_appendix_tokens=200)
    assert one == two
    assert one.candidate_paths == (path, path, "src/b.py")
    assert one.selected_paths == (path, "src/b.py")
    assert one.text.splitlines() == ["- src/a.py:3-5 (Owner.method)", "- src/b.py:1-10"]
    assert one.symbol_hints == one.file_fallback_hints == 1
    assert "TOP_SECRET_SOURCE_TEXT" not in one.text


def test_explicit_anchor_and_test_focused_path_are_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _index(tmp_path, [("src/anchor.py", ()), ("tests/test_anchor.py", ())])
    _mock_find(monkeypatch, (_candidate("src/anchor.py"), _candidate("tests/test_anchor.py")))
    result = build_navigation_shadow(GatewayConfig(tmp_path), index,
                                     ContextQuery("test anchor", paths=("src/anchor.py",)),
                                     max_appendix_tokens=200)
    assert result.selected_paths == ("src/anchor.py", "tests/test_anchor.py")


def test_fixed_full_appendix_budget_skips_later_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _index(tmp_path, [("src/a.py", ()), ("src/b.py", ())])
    _mock_find(monkeypatch, (_candidate("src/a.py"), _candidate("src/b.py")))
    budget = HeuristicTokenEstimator().estimate(append_offline_locator("", "- src/a.py:1-10"))
    result = build_navigation_shadow(GatewayConfig(tmp_path), index, ContextQuery("task"),
                                     max_appendix_tokens=budget)
    assert result.selected_paths == ("src/a.py",)
    assert result.budget_prevented_paths == ("src/b.py",)
    assert result.appendix_estimated_tokens == budget


@pytest.mark.parametrize("unsafe", ["../outside.py", "C:/outside.py", "src/../outside.py"])
def test_invalid_or_out_of_root_candidate_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str,
) -> None:
    index = _index(tmp_path, [("src/valid.py", ())])
    _mock_find(monkeypatch, (_candidate(unsafe),))
    with pytest.raises(ValueError):
        build_navigation_shadow(GatewayConfig(tmp_path), index, ContextQuery("task"),
                                max_appendix_tokens=200)


def test_sensitive_path_is_rejected_before_emission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "PASSWORD=privatevalue.py"
    index = _index(tmp_path, [(path, ())])
    _mock_find(monkeypatch, (_candidate(path),))
    with pytest.raises(ValueError, match="sensitive"):
        build_navigation_shadow(GatewayConfig(tmp_path), index, ContextQuery("task"),
                                max_appendix_tokens=200)


def test_invalid_or_sensitive_symbol_falls_back_without_leaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "src/a.py"
    symbol = Symbol(path, "secret", "TOKEN=privatevalue", "function", 3, 5)
    index = _index(tmp_path, [(path, (symbol,))])
    _mock_find(monkeypatch, (_candidate(path, symbols=(symbol.qualified_name,)),))
    result = build_navigation_shadow(GatewayConfig(tmp_path), index, ContextQuery("task"),
                                     max_appendix_tokens=200)
    assert result.text == "- src/a.py:1-10"
    assert "privatevalue" not in result.text


def test_pinned_development_parity_and_reserved_protection() -> None:
    class GuardedDataset(dict):
        def __getitem__(self, key: str) -> object:
            if key == "reserved_evaluation_tasks":
                raise AssertionError("reserved reference labels must stay sealed")
            return super().__getitem__(key)

    guarded = GuardedDataset(json.loads((ROOT / "docs/source_selection_reference_dataset.json").read_text()))
    _validate_development_pins(guarded, ROOT / "tests/fixtures/locator_shadow_corpus.json")
    result = run_shadow(ROOT, ROOT / "tests/fixtures/locator_shadow_corpus.json",
                        ROOT / "docs/source_selection_reference_dataset.json",
                        ROOT / "docs/source_free_locator_navigation_audit.json")
    assert result["scope"] == "DEVELOPMENT_ONLY" and result["model_calls"] == 0
    assert result["baseline_areas_navigable"] == 6
    assert all(row["candidate_pool_identical"] for row in result["tasks"])
    assert [row["task_id"] for row in result["tasks"]] == ["N01", "M02", "C02", "T01", "G02", "E01"]
    assert all(row["candidate"]["model_visible_appendix_estimated_tokens"]
               <= row["baseline"]["model_visible_appendix_estimated_tokens"] for row in result["tasks"])
    assert result == json.loads((ROOT / "docs/navigation_only_shadow_result.json").read_text())
    serialized = json.dumps(result)
    assert "TOP_SECRET_SOURCE_TEXT" not in serialized
    assert '"task":' not in serialized and '"text":' not in serialized
