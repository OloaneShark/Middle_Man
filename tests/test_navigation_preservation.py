"""Fixed-union preservation tests; no selector or reference scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from middle_man.experiments.navigation_preservation import (
    Hint, checked_hints, format_hints, measure, preservation_scenario,
)
from middle_man.gateway.config import GatewayConfig
from scripts.evaluate_navigation_preservation import run_preservation


ROOT = Path(__file__).resolve().parents[1]


def _record(path: str, start: int, end: int, symbol: str | None = None) -> dict[str, object]:
    return {"path": path, "range": [start, end], "symbol": symbol}


def test_same_path_ranges_and_exact_duplicate_removal() -> None:
    original = Hint("src/a.py", 1, 4, "Owner.first")
    added = Hint("src/a.py", 8, 12, "Owner.second")
    result = preservation_scenario((original,), ((original, added),), appendix_budget=60)
    assert result["selected_paths"] == ["src/a.py"]
    assert result["distinct_paths"] == 1 and result["distinct_locations"] == 2
    assert result["exact_duplicates_removed"] == 1
    assert format_hints((original, added)) == "- src/a.py:1-4 (Owner.first); 8-12 (Owner.second)"


def test_same_range_distinct_symbols_are_preserved() -> None:
    first = Hint("src/a.py", 3, 7, "Owner.one")
    second = Hint("src/a.py", 3, 7, "Owner.two")
    result = preservation_scenario((first,), ((second,),), appendix_budget=100)
    assert result["distinct_paths"] == result["distinct_locations"] == 1
    assert result["distinct_hints"] == 2 and result["exact_duplicates_removed"] == 0


def test_original_order_and_cross_path_union() -> None:
    a = Hint("src/a.py", 1, 2)
    c = Hint("src/c.py", 1, 2)
    b = Hint("src/b.py", 3, 4)
    extra_a = Hint("src/a.py", 5, 6)
    result = preservation_scenario((a, c), ((b, extra_a),), appendix_budget=200)
    assert result["selected_paths"] == ["src/a.py", "src/c.py", "src/b.py"]
    assert result["hints"] == [a.as_dict(), extra_a.as_dict(), c.as_dict(), b.as_dict()]
    assert format_hints((a, c, b, extra_a)).startswith("- src/a.py:1-2; 5-6\n- src/c.py:1-2")


def test_budget_arithmetic_measures_complete_union_without_trimming() -> None:
    base = Hint("src/a.py", 1, 20, "Owner.original")
    addition = Hint("src/a.py", 30, 40, "Owner.extra")
    budget = measure(format_hints((base,)))["appendix_estimated_tokens"]
    result = preservation_scenario((base,), ((addition,),), appendix_budget=budget)
    assert result["appendix_budget"] == budget
    assert result["appendix_over_under_tokens"] > 0 and not result["fits_fixed_budget"]
    assert result["supplemental_hints_beyond_budget_in_input_order"] == 1
    assert result["distinct_hints"] == 2
    assert (result["path_bytes"] + result["range_bytes"] + result["symbol_bytes"]
            + result["format_separator_bytes"] == result["locator_bytes"])


def test_deterministic_output_and_duplicate_base() -> None:
    hint = Hint("src/a.py", 1, 2)
    first = preservation_scenario((hint, hint), ((hint,),), appendix_budget=100)
    second = preservation_scenario((hint, hint), ((hint,),), appendix_budget=100)
    assert first == second and first["distinct_hints"] == 1
    assert first["exact_duplicates_removed"] == 2


def test_checked_hints_reject_unsafe_paths_and_symbols(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("TOP_SECRET_SOURCE_TEXT", encoding="utf-8")
    config = GatewayConfig(tmp_path)
    good = checked_hints([_record("src/a.py", 1, 2, "Owner.method")], config)
    assert good == (Hint("src/a.py", 1, 2, "Owner.method"),)
    assert "TOP_SECRET_SOURCE_TEXT" not in format_hints(good)
    for record in (_record("../outside.py", 1, 2),
                   _record("src/a.py", 2, 1),
                   _record("src/a.py", 1, 2, "TOKEN=privatevalue")):
        with pytest.raises(ValueError):
            checked_hints([record], config)
    secret = tmp_path / "PASSWORD=privatevalue.py"
    secret.write_text("not emitted", encoding="utf-8")
    with pytest.raises(ValueError):
        checked_hints([_record(secret.name, 1, 1)], config)


def test_frozen_abc_reconstruction_without_reference_evaluation() -> None:
    result = run_preservation(ROOT, ROOT / "tests/fixtures/locator_shadow_corpus.json",
                              ROOT / "docs/source_selection_reference_dataset.json",
                              {"A": ROOT / "docs/source_free_locator_navigation_audit.json",
                               "B": ROOT / "docs/navigation_only_shadow_result.json",
                               "C": ROOT / "docs/navigation_hint_precision_result.json"})
    assert result == json.loads((ROOT / "docs/navigation_hint_preservation_feasibility.json").read_text())
    assert result["scope"] == "DEVELOPMENT_ONLY" and result["model_calls"] == 0
    assert [row["task_id"] for row in result["tasks"]] == ["N01", "M02", "C02", "T01", "G02", "E01"]
    serialized = json.dumps(result)
    assert '"task":' not in serialized and '"text":' not in serialized
