"""One-shot pilot integration under a fake process; never invoke installed Codex."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from middle_man.experiments import codex_exploration_pilot as pilot
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.codex_runner import execution
from middle_man.gateway.codex_runner.infrastructure import CodexCLI
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


CLI = CodexCLI("fake-codex", "codex-cli synthetic")
ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Synthetic tracked instructions.\n", encoding="utf-8")
    (tmp_path / "queue.py").write_text("def queue_state():\n    return 'ready'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test",
                    "-c", "user.email=test@example.invalid", "commit", "-qm", "synthetic pin"], check=True)
    task = "Explain synthetic queue state."
    for name, value in {
        "SOURCE_COMMIT": _git(tmp_path, "rev-parse", "HEAD"),
        "SOURCE_TREE": _git(tmp_path, "rev-parse", "HEAD^{tree}"),
        "SOURCE_FINGERPRINT": source_fingerprint(tmp_path),
        "AGENTS_BLOB": _git(tmp_path, "rev-parse", "HEAD:AGENTS.md"),
        "SELECTOR_FINGERPRINT": selector_implementation_fingerprint(),
        "TASK": task,
        "TASK_SHA256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "CLI_VERSION": CLI.version,
    }.items():
        monkeypatch.setattr(pilot, name, value)
    return tmp_path


def _events(*, malformed: bool = False, usage: bool = True,
            external: bool = False, answer: str = "SYNTHETIC_FINAL_8231") -> str:
    rows = [{"type": "thread.started", "thread_id": "synthetic"},
            {"type": "turn.started"}]
    rows.extend({"type": "item.completed", "item": {"type": "command_execution",
                 "command": command, "aggregated_output": "SYNTHETIC_SOURCE_7712"}}
                for command in ("Get-Content queue.py", "Get-Content queue.py",
                                "rg -n first queue.py", "rg -n different queue.py"))
    if external:
        rows.append({"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "unwanted", "tool": "lookup"}})
    rows.append({"type": "item.completed", "item": {"type": "agent_message", "text": answer}})
    rows.append({"type": "turn.completed", "usage": {
        "input_tokens": 100, "cached_input_tokens": 20,
        "output_tokens": 40, "reasoning_output_tokens": 7} if usage else {}})
    return ("{bad-json\n" if malformed else "") + "\n".join(json.dumps(row) for row in rows)


class FakeProcess:
    def __init__(self, stdout: str, change=None) -> None:
        self.stdout = stdout
        self.change = change
        self.returncode = 0
        self.timeouts: list[int] = []

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        if timeout is not None:
            self.timeouts.append(timeout)
        if self.change:
            self.change()
        return self.stdout, ""


def _fake_launch(monkeypatch: pytest.MonkeyPatch, root: Path, process: FakeProcess) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def launch(command: tuple[str, ...], cwd: Path, **_kwargs: object) -> FakeProcess:
        assert command[0] == "fake-codex" and cwd == root
        assert command[command.index("-s") + 1] == "read-only"
        assert command[command.index("-m") + 1] == pilot.MODEL
        assert f'windows.sandbox="{pilot.SANDBOX}"' in command
        assert f'model_reasoning_effort="{pilot.EFFORT}"' in command
        for required in ("--json", "--ephemeral", "--no-daemon", "--ignore-user-config",
                         "--strict-config", "features.apps=false", "features.plugins=false"):
            assert required in command
        assert not any("mcp_servers." in part for part in command)
        calls.append(command)
        return process

    monkeypatch.setattr(execution, "_Popen", launch)
    return calls


def test_one_mocked_pilot_preserves_production_usage_and_sanitizes_trace(
        snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preparation = pilot.prepare_pilot(snapshot, CLI)
    process = FakeProcess(_events())
    calls = _fake_launch(monkeypatch, snapshot, process)
    with pytest.raises(ValueError, match="separate external-service confirmation"):
        preparation.run_once(CLI)
    assert not calls
    result, assessment = preparation.run_once(CLI, confirm_external_service=True)
    assert len(calls) == 1 and process.timeouts == [pilot.TIMEOUT_SECONDS]
    assert result.status == "SUCCESS" and result.external_calls == 1
    assert (result.input_tokens, result.cached_input_tokens, result.output_tokens) == (100, 20, 40)
    assert assessment["valid"] and assessment["provider_usage"] == {
        "input_tokens": 100, "cached_input_tokens": 20,
        "output_tokens": 40, "reasoning_output_tokens": 7}
    steps = assessment["trace"]["steps"]
    assert len(steps) == 4
    assert steps[1]["previously_read_paths"] == ("queue.py",)
    assert steps[3]["revisited_search_target_paths"] == ("queue.py",)
    assert assessment["trace"]["summary"]["native_tool_calls"] == result.native_tool_calls
    assert result.audit_dict().get("research_evidence") is None
    serialized = json.dumps(assessment)
    for forbidden in ("Get-Content", "rg -n", "first", "different", "SYNTHETIC_FINAL_8231",
                      "SYNTHETIC_SOURCE_7712", str(snapshot), "fake-codex"):
        assert forbidden not in serialized
    with pytest.raises(RuntimeError, match="already been used"):
        preparation.run_once(CLI, confirm_external_service=True)
    assert len(calls) == 1


@pytest.mark.parametrize("fault", ["malformed", "missing_usage", "external", "mutation", "ignored_mutation"])
def test_mocked_pilot_fails_closed(snapshot: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    preparation = pilot.prepare_pilot(snapshot, CLI)
    process = FakeProcess(_events(malformed=fault == "malformed", usage=fault != "missing_usage",
                                  external=fault == "external"),
                          change=(lambda: (snapshot / "queue.py").write_text("changed\n", encoding="utf-8"))
                          if fault == "mutation" else
                          (lambda: (snapshot / ".env").write_text("synthetic\n", encoding="utf-8"))
                          if fault == "ignored_mutation" else None)
    calls = _fake_launch(monkeypatch, snapshot, process)
    result, assessment = preparation.run_once(CLI, confirm_external_service=True)
    assert len(calls) == 1 and not assessment["valid"]
    assert result.research_evidence["valid"] is False
    if fault == "missing_usage":
        assert result.status == "SUCCESS" and result.research_evidence["failure"] == "MISSING_PROVIDER_USAGE"
    elif fault == "mutation":
        assert result.status == "READ_ONLY_INTEGRITY_FAILURE"
        assert result.research_evidence["failure"] == "SNAPSHOT_CHANGED"
    elif fault == "ignored_mutation":
        assert result.status == "SUCCESS" and result.repository_unchanged
        assert result.research_evidence["failure"] == "SNAPSHOT_CHANGED"
    elif fault == "malformed":
        assert result.status == "MALFORMED_EVENTS"
    else:
        assert "UNEXPECTED_EXTERNAL_TOOL_ACTIVITY" in result.failure_reasons


def test_preflight_rejects_ignored_extra_file_without_reading_it(
        snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (snapshot / ".env").write_text("SYNTHETIC_NOT_A_CREDENTIAL\n", encoding="utf-8")
    monkeypatch.setattr(pilot, "source_fingerprint", lambda _root: pytest.fail("ignored file was read"))
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("Codex process started"))
    with pytest.raises(ValueError, match="untracked files"):
        pilot.prepare_pilot(snapshot, CLI)


def test_preflight_rejects_dirty_snapshot_and_wrong_cli_without_launch(
        snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("Codex process started"))
    with pytest.raises(ValueError, match="CLI version"):
        pilot.prepare_pilot(snapshot, CodexCLI("fake-codex", "different"))
    (snapshot / "queue.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="begin clean"):
        pilot.prepare_pilot(snapshot, CLI)


def test_clean_but_wrong_source_fingerprint_never_launches(
        snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pilot, "SOURCE_FINGERPRINT", "0" * 64)
    monkeypatch.setattr(execution, "_Popen", lambda *_args, **_kwargs: pytest.fail("Codex process started"))
    with pytest.raises(ValueError, match="source, selector, or clean-state pin"):
        pilot.prepare_pilot(snapshot, CLI)


def test_changed_snapshot_before_launch_and_aggregate_mismatch_fail_closed(
        snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preparation = pilot.prepare_pilot(snapshot, CLI)
    (snapshot / "ignored.tmp").write_text("new\n", encoding="utf-8")
    calls = _fake_launch(monkeypatch, snapshot, FakeProcess(_events()))
    with pytest.raises(RuntimeError, match="changed before process"):
        preparation.run_once(CLI, confirm_external_service=True)
    assert not calls
    (snapshot / "ignored.tmp").unlink()
    result, assessment = preparation.run_once(CLI, confirm_external_service=True)
    assert assessment["valid"]
    assert not pilot.assess_pilot(replace(result, explicit_reads=result.explicit_reads + 1), preparation)["valid"]
    corrupt = replace(result, research_evidence={"valid": True, "trace": {}})
    assert pilot.assess_pilot(corrupt, preparation)["failure"] == "AGGREGATE_PARITY_FAILURE"


def test_historical_pilot_identity_is_still_available_locally() -> None:
    assert hashlib.sha256(pilot.TASK.encode("utf-8")).hexdigest() == pilot.TASK_SHA256
    assert _git(ROOT, "rev-parse", f"{pilot.SOURCE_COMMIT}^{{tree}}") == pilot.SOURCE_TREE
    assert _git(ROOT, "rev-parse", f"{pilot.SOURCE_COMMIT}:AGENTS.md") == pilot.AGENTS_BLOB
