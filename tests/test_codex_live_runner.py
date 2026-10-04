"""Live product flow under a fake process; never invokes installed Codex."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from middle_man.cli.codex_run import run_codex_command
from middle_man.cli.main import build_parser
from middle_man.gateway.codex_runner import execution
from middle_man.gateway.codex_runner.infrastructure import CodexCLI, capture_repository_state
from middle_man.gateway.codex_runner.runner import preview_codex
from middle_man.gateway.offline_navigation import append_offline_locator, build_offline_locator
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.relevance import ContextQuery


CLI = CodexCLI("fake-codex", "codex-cli synthetic")
ROOT = Path(__file__).resolve().parents[1]
LARGE_TASK = "Explain how the Agent Gateway selects repository context and how offline AUTO decides whether Codex receives a locator."


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "queue.py").write_text("def queue_state():\n    return 'ready'\n", encoding="utf-8")
    return tmp_path


def _events(*, answer: str = "All set.", usage: bool = True, commands: bool = True) -> str:
    lines = [{"type": "thread.started", "thread_id": "synthetic-thread"}, {"type": "turn.started"}]
    if commands:
        lines.extend([
            {"type": "item.completed", "item": {"type": "command_execution", "command": "Get-Content queue.py"}},
            {"type": "item.completed", "item": {"type": "command_execution", "command": "Get-Content queue.py"}},
            {"type": "item.completed", "item": {"type": "command_execution", "command": "rg -n queue ."}},
            {"type": "item.completed", "item": {"type": "command_execution", "command": "rg --files"}},
        ])
    if answer:
        lines.append({"type": "item.completed", "item": {"type": "agent_message", "text": answer}})
    lines.append({"type": "turn.completed", "usage": {
        "input_tokens": 100, "cached_input_tokens": 20,
        "output_tokens": 40, "reasoning_output_tokens": 7} if usage else {}})
    return "\n".join(json.dumps(item) for item in lines) + "\n"


class FakeProcess:
    def __init__(self, stdout: str, *, exit_code: int = 0, stderr: str = "", timeout: bool = False,
                 change=None) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = exit_code
        self.timeout = timeout
        self.change = change
        self.killed = False

    def communicate(self, timeout=None):
        if timeout is not None and self.timeout:
            raise subprocess.TimeoutExpired("fake-codex", timeout, output=self.stdout)
        if self.change:
            self.change()
            self.change = None
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True
        self.returncode = -9


def _fake_launch(monkeypatch: pytest.MonkeyPatch, process: FakeProcess):
    calls = []

    def launch(command, **kwargs):
        assert command[0] == "fake-codex"  # Installed Codex must never be reached.
        assert command.count("exec") == 1 and command.count("--json") == 1
        assert "--no-daemon" in command and "--ignore-user-config" in command
        assert "mcp_servers" not in " ".join(command)
        assert "benchmark working copy" not in command[-1]
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(execution, "_Popen", launch)
    return calls


def test_live_read_only_locator_and_usage_are_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(_events(commands=False))
    calls = _fake_launch(monkeypatch, process)
    result = execution.run_codex(ROOT, LARGE_TASK, mode="read-only", confirm_external_service=True, cli=CLI)
    locator = build_offline_locator(GatewayConfig(ROOT, cache_writes_enabled=False), ContextQuery(LARGE_TASK))
    assert result.status == "SUCCESS" and result.external_calls == 1 and len(calls) == 1
    assert not result.audit.dry_run and result.audit.external_calls == 1
    assert result.audit.decision == "LOCATOR USED"
    assert calls[0][0][-1] == append_offline_locator(LARGE_TASK, locator.text)
    assert calls[0][0][calls[0][0].index("-s") + 1] == "read-only"
    assert result.final_message == "All set." and result.thread_id == "synthetic-thread"
    assert (result.input_tokens, result.cached_input_tokens, result.output_tokens,
            result.reasoning_output_tokens) == (100, 20, 40, 7)
    assert result.repository_unchanged and result.git_status_before == result.git_status_after
    assert result.git_head_before == result.git_head_after
    assert result.git_head_before is not None


def test_small_bypass_counts_reads_without_prompt_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    task = "Explain queue state."
    calls = _fake_launch(monkeypatch, FakeProcess(_events()))
    result = execution.run_codex(root, task, mode="read-only", confirm_external_service=True, cli=CLI)
    assert result.status == "SUCCESS" and result.audit.decision == "BYPASSED"
    assert calls[0][0][-1].encode() == task.encode()
    assert result.audit.model_visible_middle_man_tokens == 0
    assert result.native_tool_calls == 4 and result.explicit_reads == 2
    assert result.unique_files == ("queue.py",) and result.rereads == 1
    assert result.search_calls == 1 and result.listing_calls == 1
    assert task not in json.dumps(result.audit_dict())
    assert not (root / "AGENTS.md").exists() and not (root / ".middle_man_cache").exists()


def test_workspace_write_records_change_from_dirty_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    task = "Fix the queue."
    (root / "queue.py").write_text("def queue_state():\n    return 'user edit'\n", encoding="utf-8")
    before = capture_repository_state(root)
    process = FakeProcess(_events(commands=False), change=lambda: (root / "queue.py").write_text(
        "def queue_state():\n    return 'codex edit'\n", encoding="utf-8"))
    calls = _fake_launch(monkeypatch, process)
    result = execution.run_codex(root, task, mode="workspace-write", confirm_external_service=True, cli=CLI)
    assert result.status == "SUCCESS" and result.audit.decision == "BYPASSED"
    assert calls[0][0][-1].encode() == task.encode()
    assert calls[0][0][calls[0][0].index("-s") + 1] == "workspace-write"
    assert result.git_status_before == before.status
    assert result.git_status_after == before.status  # Same dirty status, different bytes.
    assert result.changed_paths == ("queue.py",)
    assert not result.repository_unchanged and result.external_calls == 1


@pytest.mark.parametrize("kind,expected", [
    ("timeout", "TIMEOUT"), ("nonzero", "CODEX_EXIT_NONZERO"),
    ("malformed", "MALFORMED_EVENTS"), ("missing", "MISSING_FINAL_RESULT"),
])
def test_failure_preserves_partial_observations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                kind: str, expected: str) -> None:
    root = _repo(tmp_path)
    output = _events(answer="" if kind == "missing" else "Partial answer.")
    if kind == "malformed":
        output = "{broken json\n" + output
    process = FakeProcess(output, exit_code=1 if kind == "nonzero" else 0, timeout=kind == "timeout",
                          stderr="synthetic failure")
    calls = _fake_launch(monkeypatch, process)
    result = execution.run_codex(root, "Explain queue state", mode="read-only",
                                 confirm_external_service=True, cli=CLI, timeout=3)
    assert result.status == expected and expected in result.failure_reasons
    assert result.input_tokens == 100 and result.native_tool_calls == 4
    assert result.stderr_sha256 and result.stderr_length_bytes > 0
    assert result.external_calls == 1 and len(calls) == 1
    assert result.timed_out == (kind == "timeout")
    assert process.killed == (kind == "timeout")
    assert result.malformed_event_lines == ((1,) if kind == "malformed" else ())


def test_read_only_mutation_is_invalid_even_on_zero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    process = FakeProcess(_events(commands=False), change=lambda: (root / "queue.py").write_text(
        "changed by synthetic Codex\n", encoding="utf-8"))
    _fake_launch(monkeypatch, process)
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    assert result.exit_code == 0 and result.status == "READ_ONLY_INTEGRITY_FAILURE"
    assert result.changed_paths == ("queue.py",) and not result.repository_unchanged
    assert (root / "queue.py").read_text(encoding="utf-8") == "changed by synthetic Codex\n"


def test_dirty_read_only_worktree_is_accepted_if_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    (root / "notes.txt").write_text("user work\n", encoding="utf-8")
    before = capture_repository_state(root)
    _fake_launch(monkeypatch, FakeProcess(_events(commands=False)))
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    assert result.status == "SUCCESS" and result.repository_unchanged
    assert result.git_status_before == before.status == result.git_status_after


def test_missing_usage_fields_remain_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    _fake_launch(monkeypatch, FakeProcess(_events(commands=False, usage=False)))
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    assert result.status == "SUCCESS"
    assert (result.input_tokens, result.cached_input_tokens, result.output_tokens,
            result.reasoning_output_tokens) == (None, None, None, None)


def test_no_confirmation_or_preprocessing_mutation_never_launches(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    calls = _fake_launch(monkeypatch, FakeProcess(_events()))
    with pytest.raises(ValueError, match="confirm-external-service"):
        execution.run_codex(root, "Explain queue", mode="read-only", cli=CLI)
    with pytest.raises(ValueError, match="timeout"):
        execution.run_codex(root, "Explain queue", mode="read-only",
                            confirm_external_service=True, cli=CLI, timeout=0)
    original = execution.preview_codex

    def mutating_preview(*args, **kwargs):
        result = original(*args, **kwargs)
        (root / "queue.py").write_text("modified before launch\n", encoding="utf-8")
        return result

    monkeypatch.setattr(execution, "preview_codex", mutating_preview)
    with pytest.raises(RuntimeError, match="preprocessing"):
        execution.run_codex(root, "Explain queue", mode="read-only",
                            confirm_external_service=True, cli=CLI)
    assert not calls


def test_cli_gate_and_dry_run_cannot_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path)
    for flags in ([], ["--dry-run", "--confirm-external-service"]):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["codex", "run", "--repo", str(root), "--read-only", *flags, "task"])
    monkeypatch.setattr("middle_man.gateway.codex_runner.runner.discover_codex", lambda: CLI)
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("external process started"))
    args = build_parser().parse_args(["codex", "run", "--repo", str(root), "--read-only",
                                      "--dry-run", "task"])
    run_codex_command(args)
    assert "External call: NO (dry-run)" in capsys.readouterr().out


def test_spawn_failure_is_structured_and_no_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    attempts = []

    def fail_spawn(command, **_kwargs):
        assert command[0] == "fake-codex"
        attempts.append(command)
        raise OSError("synthetic missing binary")

    monkeypatch.setattr(execution, "_Popen", fail_spawn)
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    assert result.status == "SPAWN_ERROR" and result.external_calls == 0
    assert len(attempts) == 1


def test_unreadable_post_run_state_is_structured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    _fake_launch(monkeypatch, FakeProcess(_events(commands=False)))
    original = execution.capture_repository_state
    checks = 0

    def capture(path):
        nonlocal checks
        checks += 1
        if checks == 4:
            raise RuntimeError("synthetic locked file")
        return original(path)

    monkeypatch.setattr(execution, "capture_repository_state", capture)
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    assert result.status == "POST_RUN_INTEGRITY_UNKNOWN"
    assert result.external_calls == 1 and not result.repository_unchanged


def test_interrupt_kills_child_and_preserves_partial_usage(tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)

    class InterruptedProcess(FakeProcess):
        def communicate(self, timeout=None):
            if timeout is not None:
                raise KeyboardInterrupt
            return super().communicate()

    process = InterruptedProcess(_events(commands=False))
    _fake_launch(monkeypatch, process)
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    assert result.status == "INTERRUPTED" and process.killed
    assert result.external_calls == 1 and result.input_tokens == 100


def test_unexpected_mcp_event_invalidates_product_run(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    lines = _events(commands=False).splitlines()
    lines.insert(-1, json.dumps({"type": "item.completed", "item": {
        "type": "mcp_tool_call", "server": "middle-man", "tool": "middleman_context"}}))
    _fake_launch(monkeypatch, FakeProcess("\n".join(lines)))
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    assert result.status == "UNEXPECTED_MCP_ACTIVITY"
    assert result.mcp_calls == (("middle-man", "middleman_context"),)


def test_live_cli_prints_summary_and_final_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path)
    _fake_launch(monkeypatch, FakeProcess(_events(commands=False)))
    result = execution.run_codex(root, "Explain queue", mode="read-only",
                                 confirm_external_service=True, cli=CLI)
    monkeypatch.setattr("middle_man.cli.codex_run.run_codex", lambda *_args, **_kwargs: result)
    args = build_parser().parse_args(["codex", "run", "--repo", str(root), "--read-only",
                                      "--confirm-external-service", "Explain queue"])
    run_codex_command(args)
    output = capsys.readouterr().out
    assert "MIDDLE_MAN CODEX" in output and "status: SUCCESS" in output
    assert "Usage (input/cached/output/reasoning): 100 / 20 / 40 / 7" in output
    assert output.rstrip().endswith("All set.")
    assert "Explain queue" not in output
