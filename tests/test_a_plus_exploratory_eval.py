"""Predeclared synthetic scoring contracts; never generate study locator outputs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from middle_man.experiments import a_plus_exploratory_eval as study
from middle_man.gateway.offline_navigation import append_offline_locator
from middle_man.gateway.tokens import HeuristicTokenEstimator


SHAPES = {
    "demo.py": (6, {"Worker": (1, 3, "class"), "Worker.run": (2, 3, "method"),
                    "other": (5, 6, "function")}),
    "extra.py": (2, {"fetch": (1, 2, "function")}),
}
SPAN = ["demo.py", "Worker.run", 2, 3]


def _reference(status: str = "COMPLETE_PROPOSED") -> dict:
    return {"reference_status": status, "unresolved_interpretations": [], "areas": [
        {"area": "dispatch", "alternatives": [
            [SPAN, ["extra.py", "fetch", 1, 2]],
            [["demo.py", "other", 5, 6]],
        ]},
    ]}


def _hint(path: str, first: int, last: int, symbol: str | None) -> dict:
    return {"path": path, "range": [first, last], "symbol": symbol}


def _locators(a: str, b: str, *, failure: bool = False) -> tuple[SimpleNamespace, SimpleNamespace]:
    estimate = HeuristicTokenEstimator()
    sha = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    a_tokens = estimate.estimate(append_offline_locator("", a))
    b_tokens = estimate.estimate(append_offline_locator("", b))
    additions = [] if a == b else [("demo.py", 5, 6, "other")]
    baseline = SimpleNamespace(text=a, sha256=sha(a))
    plus = SimpleNamespace(text=b, sha256=sha(b), baseline_sha256=baseline.sha256,
                           baseline_appendix_estimated_tokens=a_tokens,
                           appendix_estimated_tokens=b_tokens,
                           supplemental_hints=tuple(additions), new_file_count=0,
                           skip_reasons=(("BASELINE_OVER_BUDGET", 1),) if failure else (),
                           feasibility_failure=failure)
    return baseline, plus


def test_precise_navigation_requires_one_intersecting_exact_symbol_hint() -> None:
    hints = [_hint("demo.py", 1, 3, "Worker.run")]
    assert all(study.score_span(SPAN, hints, SHAPES)[key] for key in (
        "path_targeted", "range_intersects", "exact_symbol_match", "precise_navigation"))
    separated = [_hint("demo.py", 2, 3, None), _hint("demo.py", 5, 6, "Worker.run")]
    result = study.score_span(SPAN, separated, SHAPES)
    assert result["range_intersects"] and result["exact_symbol_match"]
    assert not result["precise_navigation"]


def test_whole_file_and_class_overlaps_are_diagnostics_only() -> None:
    whole = study.score_span(SPAN, [_hint("demo.py", 1, 6, None)], SHAPES)
    klass = study.score_span(SPAN, [_hint("demo.py", 1, 3, "Worker")], SHAPES)
    for result in (whole, klass):
        assert result["path_targeted"] and result["range_intersects"]
        assert result["broad_overlap_only"] and not result["precise_navigation"]
    assert study._broad(_hint("demo.py", 1, 6, None), SHAPES) == "WHOLE_FILE"
    assert study._broad(_hint("demo.py", 1, 3, "Worker"), SHAPES) == "CLASS_RANGE"


def test_multi_file_alternatives_and_complete_area_scoring() -> None:
    ref = _reference()
    one_of_two = study.score_arm(ref, [_hint("demo.py", 2, 3, "Worker.run")], SHAPES)
    assert one_of_two["areas"][0]["alternative_complete"] == [False, False]
    assert not one_of_two["complete_task_navigation"]
    both = study.score_arm(ref, [_hint("demo.py", 2, 3, "Worker.run"),
                                 _hint("extra.py", 1, 2, "fetch")], SHAPES)
    assert both["areas"][0]["alternative_complete"] == [True, False]
    assert both["complete_task_navigation"]
    other = study.score_arm(ref, [_hint("demo.py", 5, 6, "other")], SHAPES)
    assert other["areas"][0]["alternative_complete"] == [False, True]


def test_partial_references_have_only_span_diagnostics() -> None:
    scored = study.score_arm(_reference("PARTIAL_UNRESOLVED"),
                             [_hint("demo.py", 2, 3, "Worker.run")], SHAPES)
    assert scored["scoring_status"] == "PARTIAL_SPAN_DIAGNOSTIC_ONLY"
    assert scored["areas"] is None and scored["complete_task_navigation"] is None
    assert scored["span_diagnostics"]["precise_navigation_spans"] == 1


def test_invalid_and_stale_reference_spans_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("class Worker:\n    def run(self):\n        return 1\n\ndef other():\n    return 2\n", encoding="utf-8")
    shape = {"demo.py": study._source_shape(tmp_path, "demo.py")}
    study.validate_span(SPAN, shape)
    for invalid in (["demo.py", "Worker.run", 2, 4], ["demo.py", "missing", 2, 3],
                    ["missing.py", "Worker.run", 2, 3]):
        with pytest.raises(ValueError):
            study.validate_span(invalid, shape)
    with pytest.raises(ValueError):
        study._source_shape(tmp_path, "../outside.py")
    with pytest.raises(ValueError):
        study._safe_hints(tmp_path, [_hint("demo.py", 2, 4, "Worker.run")], shape,
                          supplemental=True)


def test_additive_preservation_anchors_budget_and_determinism(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("class Worker:\n    def run(self):\n        return 1\n\ndef other():\n    return 2\n", encoding="utf-8")
    a = "- demo.py:2-3 (Worker.run)"
    b = a + "\n- demo.py:5-6 (other)"
    baseline, plus = _locators(a, b)
    task = {"task_id": "synthetic", "archetype": "narrow_explicit_anchor",
            "sha256": "synthetic", "explicit_paths_supplied": ["demo.py"]}
    result = study.compare_task(task, _reference(), baseline, plus, dict(SHAPES), tmp_path)
    assert result == study.compare_task(task, _reference(), baseline, plus, dict(SHAPES), tmp_path)
    assert result["baseline_preserved"] and result["explicit_anchor_paths_lost"] == 0
    assert result["newly_navigable_areas"] == ["dispatch"] and not result["lost_navigable_areas"]
    assert result["a_appendix_estimated_tokens"] > HeuristicTokenEstimator().estimate(a)
    assert result["additional_estimated_tokens"] > 0 and result["external_inference_calls"] == 0
    plus.text = "- demo.py:5-6 (other)"
    plus.sha256 = hashlib.sha256(plus.text.encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="changed production A"):
        study.compare_task(task, _reference(), baseline, plus, dict(SHAPES), tmp_path)


def test_over_budget_baseline_remains_unchanged(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("class Worker:\n    def run(self):\n        return 1\n\ndef other():\n    return 2\n", encoding="utf-8")
    a = "\n".join(["- demo.py:2-3 (Worker.run)"] * 100)
    baseline, plus = _locators(a, a, failure=True)
    assert plus.baseline_appendix_estimated_tokens > study.APPENDIX_CEILING
    task = {"task_id": "synthetic", "archetype": "narrow_explicit_anchor",
            "sha256": "synthetic", "explicit_paths_supplied": ["demo.py"]}
    result = study.compare_task(task, _reference(), baseline, plus, dict(SHAPES), tmp_path)
    assert result["baseline_over_budget"] and not result["budget_feasible"]
    assert result["supplement_count"] == 0 and result["skip_reasons"] == {"BASELINE_OVER_BUDGET": 1}
    plus.feasibility_failure = False
    with pytest.raises(ValueError, match="over-budget A"):
        study.compare_task(task, _reference(), baseline, plus, dict(SHAPES), tmp_path)


def test_frozen_input_identity_without_locator_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    corpus, references = study.load_frozen_inputs()
    assert len(corpus["tasks"]) == len(references["tasks"]) == 16
    assert study.canonical_hash(references["tasks"]) == study.REFERENCE_SHA256
    real_git = study._git

    def bad_tree(root: Path, *args: str) -> str:
        if args and args[0] == "rev-parse":
            return "different"
        return real_git(root, *args)

    monkeypatch.setattr(study, "_git", bad_tree)
    with pytest.raises(ValueError, match="pinned source tree"):
        study.load_frozen_inputs()
