"""Archived V2 observations are checked locally; no inference is launched."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs/codex_variance_calibration_v2_result.json"
EXPECTED_INPUTS = (444869, 538290, 339527, 412053)
EXPECTED_RECEIPT_HASHES = (
    "b24e623825b24913669c71892ee36c1deb6bd4acfd7a864186cd430d7bc0020a",
    "4dd3363d4b7f65fa7c51c5053fe1380248b7278538e88d36b99a01c4b8468a73",
    "24aa2a76a401e37925d3888c15d26723da20cf97535de2de27fbc93a7782a316",
    "9d956850f47bd5af0a1659490082e1840657b0369195f9597c1b53e51f3eaa09",
)
RECEIPT_KEYS = {
    "schema_version", "arm", "task_sha256", "source_commit", "source_tree",
    "source_fingerprint_before", "source_fingerprint_after", "cli_version",
    "windows_sandbox", "model", "effort", "timeout_seconds", "process_started",
    "status", "failure_reasons", "exit_code", "timed_out", "elapsed_seconds",
    "metrics", "locator", "semantic_review", "repository", "output_rendering",
}
METRIC_KEYS = {
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
    "native_tool_calls", "explicit_reads", "unique_explicit_read_files", "rereads",
    "search_calls", "listing_calls", "content_search_calls", "file_targeted_searches",
    "repository_wide_searches", "file_listing_searches", "git_inspections",
    "unclassified_commands", "event_count", "malformed_event_lines",
    "external_tool_activity_count", "mcp_call_count",
}
LOCATOR_KEYS = {
    "decision", "reason", "candidate_tokens_estimate", "selected_tokens_estimate",
    "locator_tokens_estimate", "model_visible_tokens_estimate", "selected_paths",
    "locator_hash", "locator_paths_explicitly_read", "locator_paths_searched",
    "non_locator_paths_searched",
}
REPOSITORY_KEYS = {
    "head_before", "head_after", "status_before", "status_after",
    "content_digest_before", "content_digest_after", "changed_paths", "unchanged",
}


@pytest.fixture(scope="module")
def archive() -> tuple[dict, dict, list[dict]]:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    plan = json.loads((ROOT / result["preregistration"]["manifest_path"]).read_text(encoding="utf-8"))
    receipts = [json.loads((ROOT / item["receipt_path"]).read_text(encoding="ascii"))
                for item in result["observations"]]
    return result, plan, receipts


def test_frozen_preregistration_and_exact_receipt_bytes(archive) -> None:
    result, plan, receipts = archive
    for path_key, hash_key in (("manifest_path", "manifest_sha256"), ("plan_path", "plan_sha256")):
        reference = result["preregistration"]
        assert hashlib.sha256((ROOT / reference[path_key]).read_bytes()).hexdigest() == reference[hash_key]
    assert result["result_status"] == "VALID_DESCRIPTIVE_CALIBRATION_REPORTED_SEMANTIC_PASS"
    assert result["source"] == plan["source"]
    assert result["task_sha256"] == plan["task"]["task_sha256"]
    assert [(item["call"], item["arm"], item["replicate"])
            for item in result["observations"]] == [
                (item["call"], item["arm"], item["replicate"]) for item in plan["schedule"]]
    assert tuple(item["receipt_sha256"] for item in result["observations"]) == EXPECTED_RECEIPT_HASHES
    assert tuple(receipt["metrics"]["input_tokens"] for receipt in receipts) == EXPECTED_INPUTS

    for item, receipt in zip(result["observations"], receipts):
        raw = (ROOT / item["receipt_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["receipt_sha256"]
        assert set(receipt) == RECEIPT_KEYS
        assert set(receipt["metrics"]) == METRIC_KEYS
        assert set(receipt["repository"]) == REPOSITORY_KEYS
        assert receipt["locator"] is None or set(receipt["locator"]) == LOCATOR_KEYS
        assert not any(marker in raw.lower() for marker in (
            b'final_answer', b'raw_jsonl', b'full_command', b'command_text',
            b'prompt_text', b'authorization: bearer', b'private_key', b'c:/users/'))
        if receipt["locator"]:
            paths = sum((receipt["locator"][key] for key in (
                "selected_paths", "locator_paths_explicitly_read", "locator_paths_searched",
                "non_locator_paths_searched")), [])
            assert all(path and not PurePosixPath(path).is_absolute() and ".." not in
                       PurePosixPath(path).parts and ":" not in path and "\\" not in path
                       for path in paths)


def test_observations_match_sanitized_runtime_fields_and_review_limit(archive) -> None:
    result, plan, receipts = archive
    assert result["execution"]["processes_started"] == 4
    assert result["execution"]["retries"] == result["execution"]["claude_calls"] == 0
    assert result["execution"]["windows_sandbox"] == plan["execution"]["windows_sandbox"]
    review = result["semantic_review"]
    assert review["reported_outcome"] == "PASS_ALL_FOUR"
    assert review["receipt_field"] is None
    assert review["final_answers_archived"] is False
    assert review["reviewer_spans_archived"] is False
    assert review["independently_reproducible_from_receipts"] is False
    for item, receipt in zip(result["observations"], receipts):
        assert receipt["arm"] == item["arm"]
        assert receipt["source_commit"] == plan["source"]["commit"]
        assert receipt["source_tree"] == plan["source"]["tree"]
        assert receipt["source_fingerprint_before"] == receipt["source_fingerprint_after"] == plan["source"]["content_fingerprint"]
        assert receipt["task_sha256"] == plan["task"]["task_sha256"]
        assert receipt["cli_version"] == plan["execution"]["expected_codex_cli_version"]
        assert (receipt["model"], receipt["effort"], receipt["timeout_seconds"],
                receipt["windows_sandbox"]) == ("gpt-6-sol", "high", 360, "unelevated")
        assert receipt["process_started"] and receipt["status"] == item["runtime_status"] == "SUCCESS"
        assert receipt["exit_code"] == 0 and not receipt["timed_out"] and not receipt["failure_reasons"]
        assert receipt["output_rendering"] == "RENDERED"
        assert receipt["semantic_review"] is None and item["reported_semantic_status"] == "PASS"
        assert receipt["repository"]["unchanged"] is item["repository_unchanged"] is True
        assert receipt["repository"]["head_before"] == receipt["repository"]["head_after"] == plan["source"]["commit"]
        assert receipt["repository"]["content_digest_before"] == receipt["repository"]["content_digest_after"]
        assert not receipt["repository"]["status_before"] and not receipt["repository"]["status_after"]
        assert not receipt["repository"]["changed_paths"]
        assert receipt["metrics"]["external_tool_activity_count"] == item["external_tool_activity_count"] == 0
        assert receipt["metrics"]["mcp_call_count"] == item["mcp_call_count"] == 0
        assert not receipt["metrics"]["malformed_event_lines"]
        for key in ("input_tokens", "cached_input_tokens", "output_tokens",
                    "reasoning_output_tokens", "native_tool_calls", "search_calls"):
            assert item[key] == receipt["metrics"][key]
        assert item["elapsed_seconds"] == receipt["elapsed_seconds"]


def test_preregistered_math_and_opposing_paired_directions(archive) -> None:
    result, _plan, receipts = archive
    analysis = result["analysis"]
    ba, ma, mb, bb = (r["metrics"] for r in receipts)
    bmean = (ba["input_tokens"] + bb["input_tokens"]) / 2
    mmean = (ma["input_tokens"] + mb["input_tokens"]) / 2
    bdiff = bb["input_tokens"] - ba["input_tokens"]
    mdiff = mb["input_tokens"] - ma["input_tokens"]
    assert analysis["baseline_mean_input"] == bmean == 428461
    assert analysis["middle_man_mean_input"] == mmean == 438908.5
    assert analysis["baseline_b_minus_a_input"] == bdiff == -32816
    assert analysis["middle_man_b_minus_a_input"] == mdiff == -198763
    assert analysis["baseline_absolute_within_arm_input"] == abs(bdiff)
    assert analysis["middle_man_absolute_within_arm_input"] == abs(mdiff)
    assert analysis["baseline_absolute_within_arm_percent_of_mean"] == round(100 * abs(bdiff) / bmean, 4)
    assert analysis["middle_man_absolute_within_arm_percent_of_mean"] == round(100 * abs(mdiff) / mmean, 4)
    assert analysis["middle_man_minus_baseline_mean_input"] == mmean - bmean == 10447.5
    assert analysis["middle_man_minus_baseline_mean_percent"] == round(100 * (mmean - bmean) / bmean, 4)
    assert analysis["all_four_input_range"] == max(EXPECTED_INPUTS) - min(EXPECTED_INPUTS)
    assert analysis["replicate_a_middle_man_minus_baseline_input"] == ma["input_tokens"] - ba["input_tokens"] == 93421
    assert analysis["replicate_b_middle_man_minus_baseline_input"] == mb["input_tokens"] - bb["input_tokens"] == -72526
    assert analysis["baseline_b_minus_a_cached_input"] == bb["cached_input_tokens"] - ba["cached_input_tokens"]
    assert analysis["middle_man_b_minus_a_cached_input"] == mb["cached_input_tokens"] - ma["cached_input_tokens"]
    assert analysis["baseline_b_minus_a_elapsed_seconds"] == pytest.approx(receipts[3]["elapsed_seconds"] - receipts[0]["elapsed_seconds"])
    assert analysis["middle_man_b_minus_a_elapsed_seconds"] == pytest.approx(receipts[2]["elapsed_seconds"] - receipts[1]["elapsed_seconds"])
    for prefix, a, b in (("baseline", ba, bb), ("middle_man", ma, mb)):
        assert analysis[f"{prefix}_b_minus_a_native_calls"] == b["native_tool_calls"] - a["native_tool_calls"]
        assert analysis[f"{prefix}_b_minus_a_search_calls"] == b["search_calls"] - a["search_calls"]
    assert analysis["input_minus_cached_by_call"] == [
        r["metrics"]["input_tokens"] - r["metrics"]["cached_input_tokens"] for r in receipts]
    assert "NOT BILLING OR QUOTA" in analysis["input_minus_cached_interpretation"]


def test_locator_exploration_and_historical_exclusions(archive) -> None:
    result, plan, receipts = archive
    assert receipts[0]["locator"] is receipts[3]["locator"] is None
    left, right = receipts[1]["locator"], receipts[2]["locator"]
    summary = result["middle_man_locator"]
    assert left["decision"] == right["decision"] == summary["decision_both"] == "LOCATOR USED"
    assert left["locator_hash"] == right["locator_hash"] == summary["same_locator_hash"]
    assert left["selected_paths"] == right["selected_paths"]
    assert len(left["selected_paths"]) == summary["selected_paths_both"] == 14
    for summary_key, receipt_key in (
        ("candidate_tokens_estimate_both", "candidate_tokens_estimate"),
        ("selected_tokens_estimate_both", "selected_tokens_estimate"),
        ("locator_tokens_estimate_both", "locator_tokens_estimate"),
        ("model_visible_tokens_estimate_both", "model_visible_tokens_estimate"),
    ):
        assert left[receipt_key] == right[receipt_key] == summary[summary_key]
    for name, receipt in (("replicate_a", receipts[1]), ("replicate_b", receipts[2])):
        loc, metrics = receipt["locator"], receipt["metrics"]
        observed = summary[name]
        for key in ("locator_paths_explicitly_read", "locator_paths_searched",
                    "non_locator_paths_searched"):
            assert observed[key] == len(loc[key])
        for key in ("unique_explicit_read_files", "rereads", "native_tool_calls",
                    "search_calls", "listing_calls", "unclassified_commands"):
            assert observed[key] == metrics[key]
    historical = result["historical_exclusions"]
    batch = json.loads((ROOT / "docs/locator_quality_batch1_result.json").read_text(encoding="utf-8"))
    assert historical["v1_baseline_in_v2_sample"] is False
    assert historical["prior_valid_m01_in_v2_sample"] is False
    assert historical["prior_valid_m01_middle_man_minus_baseline_input"] == batch["pairs"][0]["input_delta_middle_man_minus_baseline"] == -8219
    assert historical["prior_valid_m01_middle_man_minus_baseline_percent"] == pytest.approx(
        batch["pairs"][0]["input_delta_percent_of_baseline"], abs=0.0001)
    assert historical["prior_runtime_backend_differs"] is True
    assert plan["historical_exclusions"]["pool_historical_observations_with_v2"] is False
    assert all(result["interpretation"][key] is False for key in (
        "statistical_significance_claim", "middle_man_overhead_proven",
        "universal_noise_threshold_defined", "winner_declared", "new_locator_policy"))
