"""Synthetic navigation checks; no model, repository snapshot, or source excerpts."""

from __future__ import annotations

import pytest

from middle_man.experiments.locator_navigation_eval import (
    development_task, evaluate_navigation, parse_locator,
)


def ref(path: str, start: int, end: int, symbol: str) -> dict[str, object]:
    return {"path": path, "lines": [start, end], "symbol": symbol}


def task(*options: list[dict[str, object]]) -> dict[str, object]:
    return {"task_id": "N01", "areas": [{"id": "area", "options": list(options)}]}


def test_path_overlap_symbol_and_specific_range() -> None:
    result = evaluate_navigation(task([ref("src/a.py", 20, 30, "Owner.method")]),
                                 "- src/a.py:18-22 (Owner.method)", file_lengths={"src/a.py": 100})
    cited = result["areas"][0]["options"][0]["references"][0]
    assert cited["path_targeted"] and cited["range_intersects"] and cited["symbol_match"]
    assert result["areas_navigable"] == 1 and result["specific_hints"] == 1
    assert result["areas_locator_ranges_fully_cover"] == 0


def test_wrong_range_but_matching_symbol_still_navigable() -> None:
    result = evaluate_navigation(task([ref("src/a.py", 20, 30, "Owner.method")]),
                                 "- src/a.py:2-4 (Owner.method)", file_lengths={"src/a.py": 100})
    cited = result["areas"][0]["options"][0]["references"][0]
    assert not cited["range_intersects"] and cited["symbol_match"] and cited["navigable"]


def test_wrong_range_and_symbol_are_not_navigable() -> None:
    result = evaluate_navigation(task([ref("src/a.py", 20, 30, "Owner.method")]),
                                 "- src/a.py:2-4 (Other.method)", file_lengths={"src/a.py": 100})
    assert result["areas_navigable"] == 0
    assert result["wrong_range_or_symbol"] == ["src/a.py"]


def test_qualified_owner_matters_and_grouped_methods_inherit_owner() -> None:
    cited = ref("src/a.py", 20, 30, "Owner.publish / clear")
    wrong = evaluate_navigation(task([cited]), "- src/a.py:2-4 (Other.clear)",
                                file_lengths={"src/a.py": 100})
    right = evaluate_navigation(task([cited]), "- src/a.py:2-4 (Owner.clear)",
                                file_lengths={"src/a.py": 100})
    assert wrong["areas_navigable"] == 0
    assert right["areas_navigable"] == 1


def test_multifile_option_requires_all_references_but_alternative_can_win() -> None:
    result = evaluate_navigation(task(
        [ref("src/a.py", 20, 30, "a"), ref("src/b.py", 5, 9, "b")],
        [ref("src/c.py", 7, 9, "c")]),
        "- src/a.py:20-22\n- src/c.py:8-8", file_lengths={"src/a.py": 100, "src/c.py": 20},
        candidate_status={"src/b.py": "BEYOND_CANDIDATE_CAP"})
    options = result["areas"][0]["options"]
    assert not options[0]["navigable"] and options[1]["navigable"]
    assert options[0]["references"][1]["diagnosis"] == "BEYOND_CANDIDATE_CAP"


def test_whole_file_hint_is_broad_even_when_it_overlaps() -> None:
    result = evaluate_navigation(task([ref("src/a.py", 20, 30, "a")]),
                                 "- src/a.py:1-100", file_lengths={"src/a.py": 100})
    assert result["areas_navigable"] == 1 and result["broad_hints"] == 1
    assert result["areas_locator_ranges_fully_cover"] == 1
    assert result["hints"][0]["specificity"] == "BROAD_WHOLE_FILE"


def test_missing_candidates_and_empty_locator() -> None:
    result = evaluate_navigation(task([ref("src/a.py", 20, 30, "a")]),
                                 "- No selected locations; use native repository search.",
                                 file_lengths={}, candidate_status={"src/a.py": "OUTSIDE_TASK_CLUSTER"})
    assert result["areas_navigable"] == 0
    assert result["areas"][0]["options"][0]["references"][0]["diagnosis"] == "OUTSIDE_TASK_CLUSTER"
    assert parse_locator("- No selected locations; use native repository search.") == []


def test_reserved_labels_cannot_be_requested() -> None:
    with pytest.raises(ValueError, match="development"):
        development_task({"development_tasks": []}, "M01")


def test_malformed_locator_fails_closed() -> None:
    with pytest.raises(ValueError):
        parse_locator("- ../outside.py:1-10")
    with pytest.raises(ValueError):
        parse_locator("- src/a.py:10-1")
