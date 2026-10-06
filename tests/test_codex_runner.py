"""Production dry-run behavior, independent of frozen benchmark tasks."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from middle_man.cli.main import build_parser
from middle_man.cli.codex_run import run_codex_preview, run_isolation_preflight
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator, build_offline_locator
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.codex_runner.infrastructure import CodexCLI, discover_codex, repository_state
from middle_man.gateway.codex_runner.runner import preview_codex
from middle_man.gateway.codex_runner.runner import build_invocation
from middle_man.gateway.codex_runner.isolation import verify_isolation_command
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.offline_navigation import decide_offline_locator as shared_decision
from middle_man.gateway.codex_benchmark.offline_auto import decide_offline_locator as benchmark_decision
from middle_man.gateway.relevance import ContextQuery


CLI = CodexCLI("codex", "codex-cli test")
ROOT = Path(__file__).resolve().parents[1]
TASK = "Explain how repository context and the offline AUTO decision work."


def _small_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "queue.py").write_text("def cancel_queue():\n    return 'ready'\n", encoding="utf-8")
    return tmp_path


def test_small_read_only_bypasses_without_mutation(tmp_path: Path) -> None:
    root = _small_repo(tmp_path)
    before = repository_state(root)
    result = preview_codex(root, TASK, mode="read-only", cli=CLI)
    assert result.audit.decision == "BYPASSED"
    assert result.audit.candidate_tokens_estimate < 10_000
    assert result.prompt.encode("utf-8") == TASK.encode("utf-8")
    assert result.audit.model_visible_middle_man_tokens == 0
    assert result.audit.locator_hash is None
    assert result.audit.task_hash == hashlib.sha256(TASK.encode()).hexdigest()
    assert not (root / ".middle_man_cache").exists()
    assert repository_state(root) == before


def test_large_read_only_uses_existing_locator_exactly() -> None:
    before = repository_state(ROOT)
    result = preview_codex(ROOT, TASK, mode="read-only", cli=CLI)
    locator = build_offline_locator(GatewayConfig(ROOT, cache_writes_enabled=False), ContextQuery(TASK))
    assert result.audit.candidate_tokens_estimate >= 10_000
    assert result.audit.decision == "LOCATOR USED"
    assert result.prompt == append_offline_locator(TASK, locator.text)
    assert result.prompt.startswith(TASK)
    assert result.prompt.count("MIDDLE_MAN LOCAL LOCATOR") == 1
    assert result.audit.locator_hash == locator.sha256
    assert result.audit.locator_estimated_tokens == locator.estimated_tokens
    assert result.audit.model_visible_middle_man_tokens > 0
    pack = ContextBuilder(GatewayConfig(ROOT, cache_writes_enabled=False)).build(ContextQuery(TASK), mode="balanced", max_context_tokens=6000)
    assert all(excerpt.text not in result.prompt for excerpt in pack.excerpts if len(excerpt.text) > 80)
    assert shared_decision is benchmark_decision
    assert repository_state(ROOT) == before


def test_large_workspace_write_bypasses_exactly() -> None:
    result = preview_codex(ROOT, "Fix queue behavior and run tests", mode="workspace-write", cli=CLI)
    assert result.audit.decision == "BYPASSED"
    assert result.audit.candidate_tokens_estimate >= 10_000
    assert result.audit.decision_reason == "workspace_write_not_validated_for_full_locator"
    assert result.prompt.encode("utf-8") == b"Fix queue behavior and run tests"
    assert result.invocation[-1] == result.prompt
    assert result.audit.model_visible_middle_man_tokens == 0
    assert result.audit.locator_hash is None


@pytest.mark.parametrize("mode", ["read-only", "workspace-write"])
def test_command_has_no_benchmark_or_mcp_injection(tmp_path: Path, mode: str) -> None:
    root = _small_repo(tmp_path)
    result = preview_codex(root, "Arbitrary user task", mode=mode, cli=CLI)
    command = result.invocation
    assert command[-1] == "Arbitrary user task"
    assert "--no-daemon" in command and "--ignore-user-config" in command
    assert command[command.index("-s") + 1] == mode
    assert "benchmark working copy" not in result.prompt
    assert "features.apps=false" in command and "features.plugins=false" in command
    assert "mcp_servers" not in " ".join(command)
    assert "AGENTS.md" not in " ".join(command)
    assert "Arbitrary user task" not in " ".join(result.redacted_command_shape)
    assert result.audit.external_calls == 0 and result.audit.dry_run
    assert "task" not in result.audit.as_dict()  # Hash/length only, never full text.


@pytest.mark.parametrize("mode", ["read-only", "workspace-write"])
def test_shared_baseline_command_uses_identical_isolation(tmp_path: Path, mode: str) -> None:
    root = _small_repo(tmp_path)
    preview = preview_codex(root, "Arbitrary user task", mode=mode, cli=CLI)
    baseline = build_invocation(CLI, root, "Arbitrary user task", mode=mode,
                                model=preview.audit.requested_model, effort=preview.audit.requested_effort)
    assert baseline == preview.invocation
    verify_isolation_command(baseline)
    for missing in ("features.apps=false", "features.plugins=false", "--ignore-user-config"):
        with pytest.raises(RuntimeError, match="isolation"):
            verify_isolation_command(tuple(part for part in baseline if part != missing))
    with pytest.raises(RuntimeError, match="isolation"):
        verify_isolation_command((*baseline[:-1], "-c", "features.apps=true", baseline[-1]))
    with pytest.raises(RuntimeError, match="isolation"):
        verify_isolation_command((*baseline[:-1], "-c", "mcp_servers.custom.enabled=true", baseline[-1]))


@pytest.mark.parametrize("options", [[], ["--read-only", "--workspace-write"]])
def test_exactly_one_mode_required(options: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["codex", "run", *options, "task", "--dry-run"])


def test_dry_run_required_and_arbitrary_task_recognized() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["codex", "run", "--read-only", "task"])
    args = build_parser().parse_args(["codex", "run", "--workspace-write", "A task: with punctuation!", "--dry-run"])
    assert args.task == "A task: with punctuation!"
    assert args.workspace_write and args.dry_run
    assert build_parser().parse_args(["codex", "benchmark", "list"]).benchmark_action == "list"


def test_codex_discovery_checks_documented_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("middle_man.gateway.codex_runner.infrastructure.shutil.which", lambda _: "/bin/codex")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[-1] == "--version":
            return SimpleNamespace(stdout="codex-cli 0.155.0\n")
        if command[-1] == "--help" and "exec" not in command:
            return SimpleNamespace(stdout="--no-daemon --ask-for-approval --strict-config")
        if command[-1] == "list":
            return SimpleNamespace(stdout="apps stable false\nplugins stable false\n")
        return SimpleNamespace(stdout="--ignore-user-config --sandbox read-only workspace-write --cd --model --config --ephemeral --json")

    monkeypatch.setattr("middle_man.gateway.codex_runner.infrastructure.subprocess.run", fake_run)
    assert discover_codex().version == "codex-cli 0.155.0"
    assert calls == [["/bin/codex", "--version"], ["/bin/codex", "--help"],
                     ["/bin/codex", "exec", "--help"], ["/bin/codex", "-c", "features.apps=false",
                     "-c", "features.plugins=false", "features", "list"]]
    monkeypatch.setattr("middle_man.gateway.codex_runner.infrastructure.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="not found"):
        discover_codex()


def test_feature_probe_fails_closed_when_apps_remain_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("middle_man.gateway.codex_runner.infrastructure.shutil.which", lambda _: "/bin/codex")

    def fake_run(command, **_kwargs):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="codex-cli synthetic")
        if command[-1] == "list":
            return SimpleNamespace(stdout="apps stable true\nplugins stable false\n")
        return SimpleNamespace(stdout="--no-daemon --ask-for-approval --strict-config --ignore-user-config "
                                      "--sandbox read-only workspace-write --cd --model --config --ephemeral --json")

    monkeypatch.setattr("middle_man.gateway.codex_runner.infrastructure.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="cannot verify"):
        discover_codex()


def test_isolation_preflight_never_launches_model(monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("middle_man.cli.codex_run.discover_codex", lambda: CLI)
    run_isolation_preflight()
    output = capsys.readouterr().out
    assert "Apps disabled: YES" in output and "Plugins disabled: YES" in output
    assert "command-level only" in output and "UNVERIFIED" in output
    assert build_parser().parse_args(["codex", "isolation-preflight"]).codex_action == "isolation-preflight"


def test_repository_validation_and_task_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a Git repository"):
        preview_codex(tmp_path, TASK, mode="read-only", cli=CLI)
    root = _small_repo(tmp_path)
    with pytest.raises(ValueError, match="task must be nonempty"):
        preview_codex(root, "", mode="read-only", cli=CLI)
    with pytest.raises(ValueError, match="exactly one"):
        preview_codex(root, TASK, mode="invalid", cli=CLI)


def test_cli_redacts_task_and_never_starts_exec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    root = _small_repo(tmp_path)
    task = "Private user task that must remain in memory"
    monkeypatch.setattr("middle_man.gateway.codex_runner.runner.discover_codex", lambda: CLI)
    args = build_parser().parse_args(["codex", "run", "--repo", str(root), "--read-only",
                                      "--dry-run", "--json", task])
    run_codex_preview(args)
    output = capsys.readouterr().out
    assert task not in output
    assert "<REDACTED_USER_TASK_AND_OPTIONAL_LOCATOR>" in output
    assert '"external_calls": 0' in output
