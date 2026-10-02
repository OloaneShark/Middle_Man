"""Local-only edit AUTO and compact-anchor regression tests."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark import runner
from middle_man.gateway.codex_benchmark.offline_anchor import render_offline_anchors
from middle_man.gateway.codex_benchmark.offline_auto import decide_offline_locator
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator, build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery


@pytest.fixture(scope="module")
def large_edit(tmp_path_factory: pytest.TempPathFactory):
    task = next(item for item in TASKS if item.id == "large-edit-v1")
    _, root, _ = prepare_pair(task, tmp_path_factory.mktemp("phase-22-16") / "pair", None)
    config = GatewayConfig(root)
    pack = ContextBuilder(config).build(ContextQuery(task.prompt), mode="balanced",
                                        max_context_tokens=6000)
    return task, root, config, pack


def test_workspace_write_gate_is_generic_and_prompt_is_identical(large_edit) -> None:
    task, root, config, pack = large_edit
    locator = build_offline_locator(config, ContextQuery(task.prompt))
    assert pack.metrics.estimated_raw_candidate_tokens == 23982
    for renamed_task in (task, replace(task, id="unrelated-workspace-write-task")):
        decision = decide_offline_locator(pack, locator, read_only=renamed_task.read_only)
        assert not decision.use_locator
        assert decision.reason == "workspace_write_not_validated_for_full_locator"
    assert decide_offline_locator(pack, locator, read_only=True).use_locator
    baseline = runner.build_invocation("codex", task, "baseline", root, model="gpt-6-sol",
                                       effort="high", optimized_mode="offline-auto")
    optimized = runner.build_invocation("codex", task, "optimized", root, model="gpt-6-sol",
                                        effort="high", optimized_mode="offline-auto")
    assert optimized == baseline
    assert optimized[-1].encode("utf-8") == baseline[-1].encode("utf-8")
    assert not (root / "AGENTS.md").exists()
    assert not any("mcp_servers." in part or "AGENTS.md" in part for part in optimized)
    forced = runner.build_invocation("codex", task, "optimized", root, model="gpt-6-sol",
                                     effort="high", optimized_mode="offline-locator",
                                     locator_text=locator.text)
    assert forced[-1] == append_offline_locator(baseline[-1], locator.text)
    assert locator.sha256 == "5217171cd64bca42a207a2cbf070c4b9a9964dfe96bf5375e944a5045e70ad50"


def test_large_edit_auto_audit_is_local_only(large_edit, tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    task, root, _, _ = large_edit
    observed: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(argv: list[str], **kwargs):
        if argv[0] == "codex":
            observed.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no MCP")))
    monkeypatch.setattr(runner, "_evaluate", lambda *args: (True, (), None, None))
    result = runner.run_one(task, "optimized", root, source_fingerprint(root), order=1,
                            codex_command="codex", codex_version="local", model="gpt-6-sol",
                            effort="high", timeout=10, artifact_root=tmp_path,
                            primary_repository_root=tmp_path, windows_sandbox="unelevated",
                            optimized_mode="offline-auto")
    assert len(observed) == 1 and result.valid and result.mcp_calls_by_tool == ()
    audit = result.offline_locator_audit
    assert audit["auto_decision"] == "BYPASSED"
    assert audit["auto_reason"] == "workspace_write_not_validated_for_full_locator"
    assert audit["model_visible_middle_man_tokens"] == 0
    assert audit["locator_sha256"] is None and audit["locator_estimated_tokens"] == 0
    baseline = runner.build_invocation("codex", task, "baseline", root, model="gpt-6-sol",
                                       effort="high", optimized_mode="offline-auto",
                                       windows_sandbox="unelevated")
    assert observed[0][-1].encode("utf-8") == baseline[-1].encode("utf-8")
    assert not (root / "AGENTS.md").exists()


def test_anchor_is_deterministic_source_free_and_not_auto_visible(large_edit) -> None:
    task, root, config, pack = large_edit
    anchor = render_offline_anchors(pack, config)
    assert anchor == render_offline_anchors(pack, config)
    assert 2 <= len(anchor.anchors) <= 4
    assert len({item.path for item in anchor.anchors}) == len(anchor.anchors)
    assert anchor.text.startswith("Relevant entry points:\n")
    assert {item.path for item in anchor.anchors} == {
        "middle_man/lab/engine.py", "middle_man/lab/request.py",
        "middle_man/lab/events.py", "tests/test_batch_cancellation.py",
    }
    assert "InferenceRequest.cancel" in anchor.text
    assert "class SimulationEngine" not in anchor.text
    assert "IndependentCancellationAcceptance" not in anchor.text
    assert "test_unknown_id_is_rejected_before_mutation" not in anchor.text
    assert "cancelled_requests=sum(" not in anchor.text
    assert "middle_man/lab/benchmarks.py" not in anchor.text
    assert "middle_man/lab/reporting.py" not in anchor.text
    assert "middle_man/lab/visualization.py" not in anchor.text
    assert all(item.phase in {"REQUIRED", "COVERAGE"} and item.matched_query_terms
               for item in anchor.anchors)
    baseline = runner.build_invocation("codex", task, "baseline", root, model="gpt-6-sol",
                                       effort="high", optimized_mode="offline-auto")
    optimized = runner.build_invocation("codex", task, "optimized", root, model="gpt-6-sol",
                                        effort="high", optimized_mode="offline-auto")
    assert anchor.text not in optimized[-1] and optimized == baseline
