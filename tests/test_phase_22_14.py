"""Local-only adaptive offline-locator tests; no external Codex process."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark import infrastructure, runner
from middle_man.gateway.codex_benchmark.offline_auto import (
    MIN_CANDIDATE_SOURCE_TOKENS, decide_offline_locator,
)
from middle_man.gateway.codex_benchmark.offline_locator import (
    LOCATOR_HEADING, append_offline_locator, build_offline_locator,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.relevance import ContextQuery
from tests.test_phase_22_11 import ACTUAL_QUERY, STRONG


def _selection(root: Path, query: ContextQuery):
    config = GatewayConfig(root)
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    locator = build_offline_locator(config, query)
    return pack, locator, decide_offline_locator(pack, locator)


@pytest.fixture(scope="module")
def task_a_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    task = next(item for item in TASKS if item.id == "preemption-v4")
    _, root, _ = prepare_pair(task, tmp_path_factory.mktemp("auto-task-a") / "pair", None)
    return root


def test_auto_measurements_and_determinism(task_a_root: Path, tmp_path: Path) -> None:
    task = next(item for item in TASKS if item.id == "preemption-v4")
    queries = {"exact": ContextQuery(task.prompt),
               "recorded": ContextQuery(ACTUAL_QUERY, symbols=("WorkKind", "InferenceRequest")),
               **{name: ContextQuery(prompt) for name, prompt in STRONG.items()}}
    for name, query in queries.items():
        pack, locator, decision = _selection(task_a_root, query)
        assert decision == decide_offline_locator(pack, locator)
        assert decision.use_locator, name
        assert decision.candidate_tokens >= 33030
        assert decision.selected_paths >= 12
        if name == "exact":
            assert decision.selected_tokens == 5983 and decision.locator_tokens == 159
            assert locator.sha256 == "14587213a088bcc66d0304ee0473fc23000bd01e2f13042c714a14550da62e97"
    for task_id in ("oauth-bug", "upload-feature"):
        task = next(item for item in TASKS if item.id == task_id)
        _, root, _ = prepare_pair(task, tmp_path / task_id, None)
        pack, locator, decision = _selection(root, ContextQuery(task.prompt))
        assert decision == decide_offline_locator(pack, locator)
        assert not decision.use_locator
        assert decision.candidate_tokens < 600
    for case in coverage_cases():
        root = tmp_path / case.name
        for relative, source in case.files:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        pack, locator, decision = _selection(root, ContextQuery(case.query))
        assert not decision.use_locator, case.name
        assert decision.candidate_tokens < 2300
    assert MIN_CANDIDATE_SOURCE_TOKENS == 10_000


def test_auto_gate_uses_metrics_not_task_identity(task_a_root: Path) -> None:
    task = next(item for item in TASKS if item.id == "preemption-v4")
    pack, locator, decision = _selection(task_a_root, ContextQuery(task.prompt))
    assert decision.use_locator
    assert decide_offline_locator(replace(pack, metrics=replace(
        pack.metrics, estimated_raw_candidate_tokens=MIN_CANDIDATE_SOURCE_TOKENS - 1)),
        locator).use_locator is False
    assert decide_offline_locator(replace(pack, metrics=replace(
        pack.metrics, estimated_raw_candidate_tokens=MIN_CANDIDATE_SOURCE_TOKENS)),
        locator).use_locator is True
    assert decide_offline_locator(pack, replace(locator, selected_paths=())).use_locator is False


@pytest.mark.parametrize("task_id,used", [
    ("preemption-v4", True), ("oauth-bug", False), ("upload-feature", False),
])
def test_auto_prompt_parity_and_locator_unchanged(task_id: str, used: bool,
                                                   task_a_root: Path, tmp_path: Path) -> None:
    task = next(item for item in TASKS if item.id == task_id)
    if task_id == "preemption-v4":
        root = task_a_root
    else:
        _, root, _ = prepare_pair(task, tmp_path / task_id, None)
    _, locator, decision = _selection(root, ContextQuery(task.prompt))
    assert decision.use_locator is used
    baseline = runner.build_invocation("codex", task, "baseline", root, model="gpt-6-sol",
                                       effort="high", optimized_mode="offline-auto")
    optimized = runner.build_invocation("codex", task, "optimized", root, model="gpt-6-sol",
                                        effort="high", optimized_mode="offline-auto",
                                        locator_text=locator.text if used else None)
    assert all(not any("mcp_servers." in arg or "AGENTS.md" in arg for arg in argv)
               for argv in (baseline, optimized))
    assert not (root / "AGENTS.md").exists()
    if used:
        assert optimized[-1] == append_offline_locator(baseline[-1], locator.text)
        assert LOCATOR_HEADING in optimized[-1]
        assert hashlib.sha256(locator.text.encode("utf-8")).hexdigest() == locator.sha256
    else:
        assert optimized[-1].encode("utf-8") == baseline[-1].encode("utf-8")
        assert optimized == baseline
        assert LOCATOR_HEADING not in optimized[-1]
        assert "candidate_source_" not in optimized[-1]


@pytest.mark.parametrize("task_id,used", [
    ("preemption-v4", True), ("oauth-bug", False), ("upload-feature", False),
])
def test_auto_dry_run_has_no_external_call(task_id: str, used: bool, tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(runner, "_codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    main(["codex", "benchmark", "run", task_id, "--repo", str(tmp_path),
          "--dry-run", "--optimized-mode", "offline-auto", "--windows-sandbox", "unelevated"])
    output = capsys.readouterr().out
    assert f"Offline AUTO: {'LOCATOR USED' if used else 'BYPASSED'}" in output
    assert (LOCATOR_HEADING in output) is used
    assert "mcp_servers." not in output and "no AGENTS.md or MCP registration" in output
    assert not (tmp_path / ".middle_man_cache").exists()


@pytest.mark.parametrize("task_id,used", [("preemption-v4", True), ("oauth-bug", False)])
def test_auto_run_local_audit(task_id: str, used: bool, task_a_root: Path, tmp_path: Path,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    task = next(item for item in TASKS if item.id == task_id)
    if used:
        root = task_a_root
    else:
        _, root, _ = prepare_pair(task, tmp_path / task_id, None)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    actual_run = subprocess.run
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[0] == "codex":
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        return actual_run(argv, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("MCP must not run")))
    monkeypatch.setattr(runner, "_evaluate", lambda *args: (True, (), None, None))
    result = runner.run_one(task, "optimized", root, source_fingerprint(root), order=1,
                            codex_command="codex", codex_version="local", model="gpt-6-sol",
                            effort="high", timeout=10, artifact_root=artifacts,
                            primary_repository_root=tmp_path, windows_sandbox="unelevated",
                            optimized_mode="offline-auto")
    assert len(seen) == 1 and result.valid and result.mcp_calls_by_tool == ()
    assert not any("mcp_servers." in arg for arg in seen[0])
    assert (LOCATOR_HEADING in seen[0][-1]) is used
    audit = result.offline_locator_audit
    assert audit and audit["auto_decision"] == ("LOCATOR_USED" if used else "BYPASSED")
    assert audit["auto_metrics"]["candidate_tokens"] > 0
    assert audit["model_visible_locator"] is used
    assert (audit["model_visible_middle_man_tokens"] > 0) is used
    assert (audit["locator_sha256"] is not None) is used
    assert result.primary_repo_usage_unchanged
    if not used:
        baseline = runner.build_invocation("codex", task, "baseline", root, model="gpt-6-sol",
                                           effort="high", optimized_mode="offline-auto")
        assert seen[0][-1].encode("utf-8") == baseline[-1].encode("utf-8")
        assert audit["locator_estimated_tokens"] == 0
        assert result.native_read_locator_coverage == ()
    report = runner.format_report({"run_id": "local", "codex_version": "local",
                                   "model": "gpt-6-sol", "effort": "high",
                                   "optimized_mode": "offline-auto", "pairs": [{
                                       "title": task.title, "task_version": task.schema_version,
                                       "quality_gate": "CORRECT", "valid": True,
                                       "baseline": asdict(result), "optimized": asdict(result),
                                   }]})
    assert f"Offline AUTO: {'LOCATOR USED' if used else 'BYPASSED'}" in report
    assert f"Model-visible Middle_Man tokens: {audit['model_visible_middle_man_tokens']}" in report
    assert "Aggregate optimized MCP calls/packs" not in report
    if not used:
        assert "not applicable (locator withheld)" in report


def test_auto_preflight_skips_mcp_without_codex(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(infrastructure.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runner, "_codex_version", lambda _: "local-cli")
    monkeypatch.setattr(runner, "_mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("MCP must not run")))
    monkeypatch.setattr(infrastructure, "_snapshot_mcp_call",
                        lambda *_: (_ for _ in ()).throw(AssertionError("MCP must not run")))

    def fake_probe(command: str, root: Path, permission: str, script: str,
                   windows_sandbox: str) -> subprocess.CompletedProcess[str]:
        if permission == ":read-only" and "Get-Content" in script:
            return subprocess.CompletedProcess([], 0, "original\n", "")
        if permission == ":read-only":
            return subprocess.CompletedProcess([], 1, "", "blocked")
        (root / "marker.txt").write_text("written\n", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(infrastructure, "_probe", fake_probe)
    result = infrastructure.run_local_preflight("codex", model="gpt-6-sol", effort="high",
                                                 windows_sandbox="unelevated", snapshot_root=tmp_path,
                                                 repository_root=tmp_path, optimized_mode="offline-auto")
    assert result.passed and not result.optimized_mcp_root_verified
    assert result.primary_repo_usage_unchanged
