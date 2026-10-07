"""Historical outcome and future calibration pins; no inference process."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from middle_man.gateway.locator_shadow import load_shadow_corpus


ROOT = Path(__file__).resolve().parents[1]


def test_batch1_outcome_preserves_preregistration_and_unknown_m02() -> None:
    result = json.loads((ROOT / "docs/locator_quality_batch1_result.json").read_text(encoding="utf-8"))
    for path_key, hash_key in (("manifest_path", "manifest_sha256"),
                               ("plan_path", "plan_sha256")):
        reference = result["preregistration"]
        assert hashlib.sha256((ROOT / reference[path_key]).read_bytes()).hexdigest() == reference[hash_key]
    m01, m02 = result["pairs"]
    assert m01["validity"] == "VALID" and m01["directional_interpretation"] == "CONTRADICTS_BYPASS"
    assert m01["middle_man"]["usage"]["input_tokens"] - m01["baseline"]["usage"]["input_tokens"] == -8219
    assert m02["validity"] == "INVALID_PAIR"
    assert m02["middle_man"]["process_started"] is True
    assert m02["middle_man"]["result_preserved"] is False
    assert all(m02["middle_man"][key] is None for key in
               ("runtime", "semantic", "usage", "elapsed_seconds", "telemetry", "locator_coverage"))
    assert m02["input_delta_middle_man_minus_baseline"] is None
    assert result["conclusion"]["candidate_policy_status"].endswith("REJECTED_FOR_PRODUCTION_ENABLEMENT")
    assert result["conclusion"]["batch_2"] == "NOT_AUTHORIZED_NOT_RUN"


def test_calibration_is_new_unrun_abba_sample_with_frozen_m01() -> None:
    result = json.loads((ROOT / "docs/locator_quality_batch1_result.json").read_text(encoding="utf-8"))
    plan = json.loads((ROOT / "docs/codex_variance_calibration_plan.json").read_text(encoding="utf-8"))
    corpus = load_shadow_corpus(ROOT / "tests/fixtures/locator_shadow_corpus.json")
    m01 = next(task for task in corpus["tasks"] if task["task_id"] == "M01")
    assert plan["design_status"] == "PREREGISTERED_NO_MODEL_RUN"
    assert plan["authorization"]["model_processes_authorized_now"] == 0
    assert plan["authorization"]["maximum_future_model_processes_with_separate_authorization"] == 4
    assert plan["authorization"]["no_retries"] is True
    assert plan["source"] == result["source"]
    assert plan["task"]["task_sha256"] == result["pairs"][0]["task_sha256"] == m01["sha256"]
    assert hashlib.sha256(m01["task"].encode("utf-8")).hexdigest() == m01["sha256"]
    assert [(item["arm"], item["replicate"]) for item in plan["schedule"]] == [
        ("BASELINE", "A"), ("MIDDLE_MAN", "A"), ("MIDDLE_MAN", "B"), ("BASELINE", "B")]
    assert plan["execution"]["expected_codex_cli_version"] == result["execution"]["cli_version"]
    assert plan["execution"]["model"] == "gpt-6-sol"
    assert plan["execution"]["reasoning_effort"] == "high"
    assert plan["execution"]["timeout_seconds"] == 360
    assert plan["analysis"]["no_retroactive_threshold"] is True
    assert "observations" not in plan and "results" not in plan
