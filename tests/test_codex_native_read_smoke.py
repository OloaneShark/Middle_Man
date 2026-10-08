"""Synthetic-only checks for the preregistered native-read smoke path."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest

from middle_man.experiments import codex_native_read_smoke as smoke
from middle_man.experiments.codex_pair import record_and_render
from middle_man.gateway.codex_runner import execution
from middle_man.gateway.codex_runner.infrastructure import CodexCLI
from scripts.run_codex_windows_native_read_smoke import main as script_main


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/codex_windows_native_read_smoke_plan.json"
CLI = CodexCLI("fake-codex", smoke.CLI_VERSION)


@pytest.fixture
def pinned(tmp_path: Path) -> Path:
    snapshot = tmp_path / "pinned"
    subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                    "--no-checkout", "-q", str(ROOT), str(snapshot)], check=True)
    subprocess.run(["git", "-C", str(snapshot), "checkout", "--detach", "-q",
                    smoke.SOURCE.commit], check=True)
    return snapshot


def _events(expected: dict[str, str], *, answer: str | None = None,
            exit_code: int = 0, command: str | None = None,
            output: str | None = None, external: bool = False) -> str:
    command = command or ("Get-FileHash -Algorithm SHA256 -LiteralPath README.md,AGENTS.md,"
                          "middle_man/gateway/codex_runner/runner.py")
    output = output if output is not None else "\n".join(
        f"SHA256 {digest} {path}" for path, digest in expected.items())
    answer = answer if answer is not None else "\n".join(
        f"{path}: {digest}" for path, digest in expected.items())
    items = [{"type": "thread.started", "thread_id": "synthetic"},
             {"type": "turn.started"},
             {"type": "item.completed", "item": {
                 "type": "command_execution", "command": command,
                 "status": "completed" if exit_code == 0 else "failed",
                 "exit_code": exit_code, "aggregated_output": output}}]
    if external:
        items.append({"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "synthetic", "tool": "lookup"}})
    items.extend([{"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
                  {"type": "turn.completed", "usage": {"input_tokens": 10,
                                                        "output_tokens": 20}}])
    return "\n".join(json.dumps(item) for item in items) + "\n"


class FakeProcess:
    def __init__(self, stdout: str, change=None):
        self.stdout = stdout
        self.change = change
        self.returncode = 0

    def communicate(self, timeout=None):
        if self.change:
            self.change()
            self.change = None
        return self.stdout, "synthetic stderr"


def test_manifest_task_and_independent_worktree_hashes(pinned: Path) -> None:
    plan = smoke.load_plan(PLAN)
    assert smoke.TASK_SHA256 == hashlib.sha256(smoke.TASK.encode("utf-8")).hexdigest()
    assert plan["task"]["utf8_bytes"] == len(smoke.TASK.encode("utf-8")) == 313
    assert smoke.worktree_hashes(pinned) == plan["expected_worktree_sha256"]
    smoke.verify_source(pinned, plan["expected_worktree_sha256"])
    assert all(len(value) == 64 for value in plan["expected_worktree_sha256"].values())


@pytest.mark.parametrize("change", ["task", "hash", "backend", "processes"])
def test_manifest_drift_fails_before_launch(tmp_path: Path, change: str) -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if change == "task":
        plan["task"]["text"] += " changed"
    elif change == "hash":
        plan["task"]["utf8_sha256"] = "0" * 64
    elif change == "backend":
        plan["execution"]["windows_backend"] = "elevated"
    else:
        plan["maximum_processes_per_authorized_run"] = 2
    altered = tmp_path / "altered.json"
    altered.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="locked preregistration"):
        smoke.load_plan(altered)


def test_successful_synthetic_native_hash_evidence_is_sanitized(
        pinned: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = smoke.load_plan(PLAN)["expected_worktree_sha256"]
    calls = []
    def launch(command, **_kwargs):
        calls.append(command)
        return FakeProcess(_events(expected))
    monkeypatch.setattr(execution, "_Popen", launch)
    observation = smoke.run_smoke(pinned, PLAN, CLI, confirm_external_service=True)
    assert len(calls) == 1
    command = calls[0]
    assert command[-1] == smoke.TASK
    assert command.count('windows.sandbox="unelevated"') == 1
    assert "--ignore-user-config" in command and "--strict-config" in command
    assert "features.apps=false" in command and "features.plugins=false" in command
    assert "--no-daemon" in command and "--ephemeral" in command
    assert command[command.index("-s") + 1] == "read-only"
    assert not any("mcp_servers." in part for part in command)
    assert observation.receipt["smoke_evaluation"]["passed"] is True
    assert observation.receipt["research_evidence"]["matched_output_paths"] == sorted(smoke.PATHS)
    assert observation.final_answer == ""
    receipt = tmp_path / "receipt.json"
    assert record_and_render(observation, receipt, io.StringIO()) == "RENDERED"
    saved = receipt.read_text(encoding="ascii")
    assert smoke.TASK not in saved and "Get-FileHash" not in saved
    assert "aggregated_output" not in saved and "synthetic stderr" not in saved
    assert all(digest not in saved for digest in expected.values())


@pytest.mark.parametrize("failure", ["blocked", "wrong-answer", "listing-only",
                                     "missing-output", "external", "mutation"])
def test_smoke_failures_do_not_pass_from_final_answer_alone(
        pinned: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    expected = smoke.load_plan(PLAN)["expected_worktree_sha256"]
    answer = None
    command = None
    output = None
    code = 0
    change = None
    if failure == "blocked":
        code, output = 1, "Access is denied"
    elif failure == "wrong-answer":
        answer = "\n".join(f"{path}: {'0' * 64 if path == 'README.md' else digest}"
                           for path, digest in expected.items())
    elif failure == "listing-only":
        command = "Get-ChildItem ."
    elif failure == "missing-output":
        output = ""
    elif failure == "mutation":
        change = lambda: (pinned / "README.md").write_text("changed", encoding="utf-8")
    synthetic = _events(expected, answer=answer, exit_code=code, command=command,
                        output=output, external=failure == "external")
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: FakeProcess(synthetic, change))
    observation = smoke.run_smoke(pinned, PLAN, CLI, confirm_external_service=True)
    assert observation.receipt["smoke_evaluation"]["passed"] is False
    if failure == "mutation":
        assert observation.receipt["repository"]["unchanged"] is False
    if failure == "external":
        assert observation.receipt["metrics"]["mcp_call_count"] == 1


def test_missing_exit_or_output_field_fails_closed() -> None:
    expected = smoke.load_plan(PLAN)["expected_worktree_sha256"]
    item = json.loads(_events(expected).splitlines()[2])
    item["item"].pop("exit_code")
    assert smoke.inspect_native_hash_events(json.dumps(item), Path("."), expected)["valid"] is False
    item["item"]["exit_code"] = 0
    item["item"].pop("aggregated_output")
    assert smoke.inspect_native_hash_events(json.dumps(item), Path("."), expected)["valid"] is False


def test_absolute_outside_path_does_not_count_as_pinned_file(pinned: Path) -> None:
    expected = smoke.load_plan(PLAN)["expected_worktree_sha256"]
    outside = "C:/unrelated/README.md"
    command = ("Get-FileHash -LiteralPath " + outside + ",AGENTS.md,"
               "middle_man/gateway/codex_runner/runner.py")
    result = smoke.inspect_native_hash_events(_events(expected, command=command), pinned, expected)
    assert result["valid"] is False
    assert "README.md" in result["missing_output_paths"]
    output = "\n".join(f"{digest} {'C:/unrelated/README.md' if path == 'README.md' else path}"
                       for path, digest in expected.items())
    result = smoke.inspect_native_hash_events(_events(expected, output=output), pinned, expected)
    assert result["valid"] is False


def test_dirty_snapshot_fails_before_process_launch(
        pinned: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (pinned / "README.md").write_text("changed", encoding="utf-8")
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("launched"))
    with pytest.raises(RuntimeError, match="pinned source"):
        smoke.run_smoke(pinned, PLAN, CLI, confirm_external_service=True)


def test_expected_hash_drift_fails_before_process_launch(
        pinned: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan["expected_worktree_sha256"]["README.md"] = "0" * 64
    altered = tmp_path / "altered.json"
    altered.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("launched"))
    with pytest.raises(RuntimeError, match="working-tree hashes"):
        smoke.run_smoke(pinned, altered, CLI, confirm_external_service=True)


def test_unicode_console_failure_keeps_sanitized_observation(
        pinned: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = smoke.load_plan(PLAN)["expected_worktree_sha256"]
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: FakeProcess(_events(
        expected, answer="\u2192\n" + "\n".join(f"{p}: {h}" for p, h in expected.items()))))
    observation = smoke.run_smoke(pinned, PLAN, CLI, confirm_external_service=True)
    class BrokenConsole:
        def write(self, _value):
            raise UnicodeEncodeError("cp1252", "\u2192", 0, 1, "cannot encode")

        def flush(self):
            pass
    receipt = tmp_path / "receipt.json"
    assert record_and_render(observation, receipt, BrokenConsole()) == "OUTPUT_RENDERING_FAILURE"
    saved = json.loads(receipt.read_text(encoding="ascii"))
    assert saved["smoke_evaluation"]["passed"] is True
    assert saved["output_rendering"] == "OUTPUT_RENDERING_FAILURE"


def test_unconfirmed_script_and_runner_cannot_launch(
        pinned: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("launched"))
    with pytest.raises(ValueError, match="explicit external-service confirmation"):
        smoke.run_smoke(pinned, PLAN, CLI)
    with pytest.raises(SystemExit):
        script_main(["--snapshot", str(pinned), "--receipt", str(tmp_path / "receipt.json")])
