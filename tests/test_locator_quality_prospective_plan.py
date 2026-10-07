"""Locked local-only preregistration; no model process is started."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.codex_runner import execution
from middle_man.gateway.codex_runner.infrastructure import CodexCLI, capture_repository_state
from middle_man.gateway.codex_runner.runner import build_invocation, preview_codex
from middle_man.gateway.locator_shadow import (
    evaluate_locator_quality_shadow, load_shadow_corpus, numeric_features,
)
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint
from scripts.measure_locator_quality import _measure
from scripts.measure_locator_shadow_corpus import CORPUS_PATH, ROOT, _snapshot


MANIFEST_PATH = ROOT / "docs" / "locator_quality_prospective_plan.json"
SHADOW_PATH = ROOT / "docs" / "locator_quality_shadow_results.json"
EXPECTED_HASHES = {
    "M01": "380ce2cdd99f2d2ea66a2b9c4dfa417af8227b1af4402c51387d45fb9d13531d",
    "M02": "99e572ef26121c9f2260a6d16994cb68bef999c41be79981405056b22cf109a8",
    "T03": "249495e619f0a94db0c9fa1283072e6dacc97ae616822a491ea21f88b7c39cc2",
    "G04": "89b8827390c274d2c7bfade1248a5de0b4f5050aa1a4976725628bcb685ec673",
}


@pytest.fixture(scope="module")
def plan() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory, plan: dict) -> Path:
    root = _snapshot(plan["source"]["commit"], tmp_path_factory.mktemp("preregister") / "source")
    assert subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True, timeout=15
    ).strip() == plan["source"]["tree"]
    assert source_fingerprint(root) == plan["source"]["content_fingerprint"]
    assert not subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        timeout=15,
    ).strip()
    return root


def test_only_four_locked_tasks_hashes_and_orders(plan: dict) -> None:
    corpus = load_shadow_corpus(CORPUS_PATH)
    tasks = {item["task_id"]: item for item in corpus["tasks"]}
    assert plan["source"]["commit"] == "db187e0f48f54222dd250502a2e40b7f1fb16401"
    assert plan["source"]["selector_fingerprint"] == selector_implementation_fingerprint()
    assert plan["task_ids"] == ["M01", "M02", "T03", "G04"]
    assert [item["task_id"] for item in plan["tasks"]] == plan["task_ids"]
    assert plan["execution"]["model_processes_authorized_by_this_manifest"] == 0
    assert plan["execution"]["maximum_future_model_processes"] == 8
    assert plan["execution"]["expected_codex_cli_version"] == "codex-cli 0.162.0-alpha.2"
    first_arms = []
    for entry in plan["tasks"]:
        task_id = entry["task_id"]
        source = tasks[task_id]
        assert source["sha256"] == entry["task_sha256"] == EXPECTED_HASHES[task_id]
        assert hashlib.sha256(source["task"].encode("utf-8")).hexdigest() == EXPECTED_HASHES[task_id]
        assert entry["archetype"] == source["archetype"]
        assert entry["explicit_paths_supplied"] == source["explicit_paths_supplied"]
        assert entry["explicit_symbols_supplied"] == source["explicit_symbols_supplied"]
        expected_first = "BASELINE" if int(entry["task_sha256"][-1], 16) % 2 == 0 else "MIDDLE_MAN"
        assert entry["arm_order"] == [expected_first, "MIDDLE_MAN" if expected_first == "BASELINE" else "BASELINE"]
        first_arms.append(expected_first)
    assert first_arms.count("MIDDLE_MAN") == first_arms.count("BASELINE") == 2
    assert plan["batches"][0]["task_ids"] == ["M01", "M02"]
    assert plan["batches"][1]["task_ids"] == ["T03", "G04"]
    assert all(item["maximum_future_model_processes"] == 4 for item in plan["batches"])
    assert all("separate authorization" in item["authorization"] for item in plan["batches"])


def test_shadow_decisions_are_not_rewritten_and_rubrics_are_source_grounded(
        plan: dict, pinned: Path) -> None:
    shadow = json.loads(SHADOW_PATH.read_text(encoding="utf-8"))
    decisions = {item["task_id"]: item for item in shadow["shadow_policy"]["decisions"]}
    assert plan["shadow_reference"]["policy_name"] == shadow["shadow_policy"]["name"]
    assert plan["shadow_reference"]["policy_status"] == "SHADOW_ONLY"
    expected = {
        "M01": ("BYPASS", ["DISCONNECTED_SELECTION", "AMBIGUOUS_EXACT_SYMBOL"]),
        "M02": ("PASS", []),
        "T03": ("UNCERTAIN", ["DISCONNECTED_SELECTION"]),
        "G04": ("UNCERTAIN", ["AMBIGUOUS_EXACT_SYMBOL"]),
    }
    for entry in plan["tasks"]:
        task_id = entry["task_id"]
        decision, reasons = expected[task_id]
        assert (entry["shadow_decision"], entry["shadow_reason_codes"]) == (decision, reasons)
        assert (decisions[task_id]["decision"], decisions[task_id]["reason_codes"]) == (decision, reasons)
        assert evaluate_locator_quality_shadow(entry["prerun"]["quality_features"]) == (
            decision, tuple(reasons))
        rubric = entry["semantic_rubric"]
        assert 4 <= len(rubric["core_facts"]) <= 7
        assert len(rubric["implementation_areas"]) >= 3
        assert rubric["material_errors"] and rubric["equivalent_wording_allowed"] is True
        assert rubric["optional_precision"]
        assert all((pinned / relative).is_file() for relative in rubric["source_refs"])
    assert plan["pair_validity"]["no_retry"] is True
    assert plan["pair_validity"]["continue_after_first_arm_semantic_fail_if_runtime_valid"] is True
    assert any("semantic rubric passes for both answers" in rule
               for rule in plan["pair_validity"]["valid_only_if_both_arms"])


def test_pinned_prerun_receipts_and_production_preview_never_launch_model(
        plan: dict, pinned: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("model launched"))
    corpus = load_shadow_corpus(CORPUS_PATH)
    tasks = {item["task_id"]: item for item in corpus["tasks"]}
    cli = CodexCLI("fake-codex", plan["execution"]["expected_codex_cli_version"])
    before = capture_repository_state(pinned)
    for entry in plan["tasks"]:
        task = tasks[entry["task_id"]]["task"]
        receipt = entry["prerun"]
        measurement = _measure(pinned, task)
        quality = measurement["quality"]
        assert receipt["source_commit"] == before.head
        assert receipt["task_sha256"] == measurement["task_sha256"]
        assert receipt["locator_sha256"] == measurement["locator_sha256"]
        assert receipt["selected_paths"] == [row["path"] for row in quality["selected_paths"]]
        assert receipt["selected_path_count"] == quality["selected_path_count"]
        assert receipt["candidate_source_tokens_estimate"] == quality["candidate_source_tokens"]
        assert receipt["selected_source_tokens_estimate"] == quality["selected_source_tokens"]
        assert receipt["locator_tokens_estimate"] == quality["locator_tokens"]
        assert receipt["largest_cluster_share"] == quality["largest_cluster_share"]
        assert receipt["ambiguous_exact_symbol_pressure"] == quality["ambiguous_exact_symbol_pressure"]
        assert receipt["quality_features"] == numeric_features(quality)
        baseline = build_invocation(cli, pinned, task, mode="read-only", model="gpt-6-sol",
                                    effort="high")
        preview = preview_codex(pinned, task, mode="read-only", model="gpt-6-sol",
                                effort="high", cli=cli)
        assert baseline[-1] == task
        assert baseline[:-1] == preview.invocation[:-1]
        assert preview.prompt.startswith(task) and preview.prompt != task
        assert preview.audit.task_hash == entry["task_sha256"]
        assert preview.audit.decision == receipt["auto_decision"] == "LOCATOR USED"
        assert preview.audit.decision_reason == receipt["auto_reason"]
        assert preview.audit.locator_hash == receipt["locator_sha256"]
        assert preview.audit.model_visible_middle_man_tokens == receipt[
            "model_visible_middle_man_tokens_estimate"]
        command = preview.invocation
        for option in ("--ignore-user-config", "--strict-config", "--no-daemon", "--ephemeral"):
            assert option in command
        assert "features.apps=false" in command and "features.plugins=false" in command
        assert not any("mcp_servers." in part for part in command)
    assert capture_repository_state(pinned) == before


def test_manifest_has_no_observations_or_production_integration(plan: dict) -> None:
    assert plan["schema_version"] == 1
    assert plan["design_status"] == "PREREGISTERED_NO_MODEL_RUN"
    assert "results" not in plan and "observed_outcomes" not in plan
    assert "baseline_input_tokens" not in plan and "middle_man_input_tokens" not in plan
    assert not any("input_tokens" in entry["prerun"] for entry in plan["tasks"])
    assert not any("answer" in entry for entry in plan["tasks"])
    assert plan["execution"]["mcp_registration_allowed"] is False
    assert plan["metrics"]["heuristic_token_estimates_are_provider_usage"] is False
    assert set(plan["metrics"]["both_arms"]) >= {
        "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
        "content_search_calls", "file_targeted_searches", "repository_wide_searches",
        "file_listing_searches", "external_tool_activity", "mcp_calls", "repository_unchanged",
    }
    for path in (
        ROOT / "middle_man" / "gateway" / "codex_benchmark" / "offline_auto.py",
        ROOT / "middle_man" / "gateway" / "codex_runner" / "runner.py",
        ROOT / "middle_man" / "gateway" / "codex_runner" / "execution.py",
    ):
        assert "locator_quality_prospective_plan" not in path.read_text(encoding="utf-8")
