"""V2 preregistration and smoke archive checks; no model process is launched."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from middle_man.gateway.codex_runner.infrastructure import CodexCLI
from middle_man.gateway.codex_runner.runner import build_invocation
from middle_man.gateway.locator_shadow import load_shadow_corpus
from scripts import run_codex_pair_experiment as experiment


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/codex_variance_calibration_v2_plan.json"


def load_plan() -> dict:
    return json.loads(PLAN.read_text(encoding="utf-8"))


def test_v2_task_source_rubric_and_source_pins() -> None:
    plan = load_plan()
    v1 = json.loads((ROOT / "docs/codex_variance_calibration_plan.json").read_text(encoding="utf-8"))
    smoke = json.loads((ROOT / "docs/codex_windows_native_read_smoke_plan.json").read_text(encoding="utf-8"))
    prospective = json.loads((ROOT / "docs/locator_quality_prospective_plan.json").read_text(encoding="utf-8"))
    corpus = load_shadow_corpus(ROOT / plan["task"]["task_source"])
    task = next(item for item in corpus["tasks"] if item["task_id"] == "M01")
    rubric = next(item["semantic_rubric"] for item in prospective["tasks"] if item["task_id"] == "M01")

    assert plan["schema_version"] == 2
    assert plan["task"]["task_sha256"] == task["sha256"] == v1["task"]["task_sha256"]
    assert hashlib.sha256(task["task"].encode("utf-8")).hexdigest() == task["sha256"]
    assert plan["task"]["semantic_rubric_source"] == v1["task"]["semantic_rubric_source"]
    assert rubric["core_facts"] and rubric["implementation_areas"] and rubric["material_errors"]
    assert plan["task"]["evaluator_facts_in_model_prompt"] is False
    assert {key: plan["source"][key] for key in v1["source"]} == v1["source"]
    assert plan["source"]["commit"] == smoke["source"]["commit"]
    assert plan["source"]["tree"] == smoke["source"]["tree"]
    assert plan["source"]["content_fingerprint"] == smoke["source"]["content_fingerprint"]
    assert plan["source"]["tracked_agents_blob"] == smoke["source"]["agents_blob"]
    commit = plan["source"]["commit"]
    tree = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", f"{commit}^{{tree}}"], text=True).strip()
    blob = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", f"{commit}:AGENTS.md"], text=True).strip()
    assert tree == plan["source"]["tree"]
    assert blob == plan["source"]["tracked_agents_blob"]


def test_v2_execution_schedule_and_no_outcomes() -> None:
    plan = load_plan()
    auth = plan["authorization"]
    execution = plan["execution"]
    assert plan["design_status"] == "PREREGISTERED_NO_MODEL_RUN"
    assert auth == {
        "model_processes_authorized_now": 0,
        "maximum_future_model_processes_with_separate_authorization": 4,
        "calibration_calls_completed": 0,
        "no_retries": True,
    }
    assert plan["schedule"] == [
        {"call": 1, "arm": "BASELINE", "replicate": "A"},
        {"call": 2, "arm": "MIDDLE_MAN", "replicate": "A"},
        {"call": 3, "arm": "MIDDLE_MAN", "replicate": "B"},
        {"call": 4, "arm": "BASELINE", "replicate": "B"},
    ]
    assert (execution["expected_codex_cli_version"], execution["model"],
            execution["reasoning_effort"], execution["timeout_seconds"]) == (
                "codex-cli 0.162.0-alpha.2", "gpt-6-sol", "high", 360)
    assert execution["windows_sandbox"] == "unelevated"
    assert execution["both_arms_share_backend"] is True
    assert execution["unelevated_security_equivalence_to_elevated_established"] is False
    assert execution["production_windows_sandbox_default_unchanged"] is True
    assert execution["mcp_registration_allowed"] is False
    assert "no locator" in execution["baseline_prompt"]
    assert "unchanged production AUTO" in execution["middle_man_prompt"]
    assert all(term in plan["snapshot_rule"] for term in ("four independent", "AGENTS.md", "never reuse"))
    assert "observations" not in plan and "results" not in plan


def test_v2_isolation_flags_and_production_default_are_unchanged() -> None:
    execution = load_plan()["execution"]
    cli = CodexCLI("fake-codex", execution["expected_codex_cli_version"])
    common = dict(mode="read-only", model=execution["model"], effort=execution["reasoning_effort"])
    research = build_invocation(cli, ROOT, "task", **common,
                                research_windows_sandbox=execution["windows_sandbox"])
    production = build_invocation(cli, ROOT, "task", **common)
    assert 'windows.sandbox="unelevated"' in research
    assert not any(part.startswith("windows.sandbox=") for part in production)
    command = (*research[:-1], "--json", research[-1])
    for flag in execution["required_controls"]:
        if flag in {"-a never", "-s read-only"}:
            first, second = flag.split()
            assert command[command.index(first) + 1] == second
        else:
            assert flag in command
    assert not any(part.startswith("mcp_servers.") for part in command)


def test_existing_runner_accepts_v2_structure_without_inference(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class PrelaunchBoundary(Exception):
        pass

    def stop_before_launch():
        raise PrelaunchBoundary

    monkeypatch.setattr(experiment, "discover_codex", stop_before_launch)
    monkeypatch.setattr(experiment, "run_arm", lambda *_args, **_kwargs: pytest.fail("model arm launched"))
    with pytest.raises(PrelaunchBoundary):
        experiment.main([
            "--plan", str(PLAN), "--snapshot", str(tmp_path / "unused-snapshot"),
            "--task-id", "M01", "--arm", "BASELINE", "--call-number", "1",
            "--receipt", str(tmp_path / "call-1.json"), "--confirm-external-service",
        ])
    assert not (tmp_path / "call-1.json").exists()


def test_v2_validity_measurements_and_historical_exclusions() -> None:
    plan = load_plan()
    validity = plan["validity"]
    requirements = " ".join(validity["each_arm"])
    for item in ("AGENTS.md", "task SHA-256", "unelevated", "nonempty final answer",
                 "malformed JSONL", "MCP", "HEAD", "semantic PASS", "preserved"):
        assert item in requirements
    assert validity["stop_after_runtime_or_infrastructure_failure"] is True
    assert validity["record_semantic_failure_without_substitution_or_retry"] is True
    assert validity["semantic_failure_does_not_authorize_schedule_change"] is True
    assert validity["analyze_full_four_run_only_if_all_four_valid"] is True
    metrics = set(plan["metrics_per_arm"])
    for item in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
                 "elapsed_seconds", "native_tool_calls", "explicit_reads", "unique_explicit_read_files",
                 "rereads", "search_calls", "listing_calls", "content_search_calls",
                 "file_targeted_searches", "repository_wide_searches", "file_listing_searches",
                 "git_inspections", "unclassified_commands", "malformed_event_lines",
                 "external_tool_activity_count", "mcp_call_count", "repository_integrity",
                 "semantic_result", "windows_sandbox", "output_rendering", "locator_metadata_for_middle_man"):
        assert item in metrics
    analysis = plan["analysis"]
    assert analysis["baseline_within_arm_signed_input_difference"] == "B_B - B_A"
    assert analysis["middle_man_within_arm_signed_input_difference"] == "M_B - M_A"
    assert "NOT BILLING OR QUOTA" in analysis["input_minus_cached"]
    assert analysis["no_significance_claim_from_two_per_arm"] is True
    assert analysis["no_winner_or_locator_quality_rule"] is True
    assert analysis["no_retroactive_threshold"] is True
    assert plan["historical_exclusions"]["pool_historical_observations_with_v2"] is False
    assert plan["historical_exclusions"]["change_rejected_shadow_policy"] is False


def test_separately_archived_smoke_receipt_summary_is_not_v2_data() -> None:
    archived = json.loads((ROOT / "docs/codex_windows_native_read_smoke_result_v1.json")
                          .read_text(encoding="utf-8"))
    observed = archived["observed"]
    assert archived["schema_version"] == 1 and archived["status"] == "PASS"
    assert archived["source_receipt"]["verified_from_sanitized_receipt"] is True
    assert observed["successful_hash_commands"] == 1
    assert observed["native_output_matched_all_three_targets"] is True
    assert observed["final_answer_matched_all_three_targets"] is True
    assert observed["repository_unchanged"] is True
    assert observed["mcp_call_count"] == observed["external_tool_activity_count"] == 0
    assert archived["token_savings_evidence"] is archived["v2_calibration_observation"] is False
