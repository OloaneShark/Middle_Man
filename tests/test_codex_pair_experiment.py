"""The experiment harness is exercised only with synthetic Codex processes."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest

from middle_man.experiments import codex_pair
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.codex_runner import execution
from middle_man.gateway.codex_runner.infrastructure import CodexCLI
from scripts.run_codex_pair_experiment import main as experiment_main


CLI = CodexCLI("fake-codex", "codex-cli synthetic")
TASK = "Explain the queue state without editing files."
ANSWER = "\u2713 \u2192 \u65e5\u672c\u8a9e \u00e9 \U0001f680"


@pytest.fixture
def pinned(tmp_path: Path) -> tuple[Path, codex_pair.SourcePin]:
    root = tmp_path / "source"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "queue.py").write_text("def state():\n    return 'ready'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "queue.py"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Experiment Test",
                    "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "fixture"], check=True)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True).strip()
    return root, codex_pair.SourcePin(head, tree, source_fingerprint(root))


def events(answer: str = ANSWER, *, malformed: bool = False, external: bool = False) -> str:
    lines = [{"type": "thread.started", "thread_id": "synthetic"}, {"type": "turn.started"}]
    if external:
        lines.append({"type": "item.started", "item": {
            "type": "mcp_tool_call", "server": "synthetic", "tool": "lookup"}})
    lines.extend([
        {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
        {"type": "turn.completed", "usage": {
            "input_tokens": 101, "cached_input_tokens": 20,
            "output_tokens": 30, "reasoning_output_tokens": 4}},
    ])
    return ("{invalid\n" if malformed else "") + "\n".join(json.dumps(x) for x in lines) + "\n"


class FakeProcess:
    def __init__(self, stdout: str, *, code: int = 0, timeout: bool = False, change=None):
        self.stdout = stdout
        self.returncode = code
        self.timeout = timeout
        self.change = change
        self.killed = False

    def communicate(self, timeout=None):
        if timeout is not None and self.timeout:
            raise subprocess.TimeoutExpired("fake-codex", timeout)
        if self.change:
            self.change()
            self.change = None
        return self.stdout, "synthetic stderr"

    def kill(self):
        self.killed = True
        self.returncode = -9


def fake_launch(monkeypatch: pytest.MonkeyPatch, process: FakeProcess, *, arm: str):
    calls = []

    def launch(command, **_kwargs):
        assert command[0] == "fake-codex"
        assert command[-1].startswith(TASK)
        assert "--json" in command and "--ignore-user-config" in command
        assert "features.apps=false" in command and "features.plugins=false" in command
        assert "mcp_servers." not in " ".join(command)
        if arm == "BASELINE":
            assert command[-1] == TASK
        calls.append(command)
        return process

    if arm == "BASELINE":
        monkeypatch.setattr(codex_pair, "_Popen", launch)
    else:
        monkeypatch.setattr(execution, "_Popen", launch)
    return calls


@pytest.mark.parametrize("arm", ["BASELINE", "MIDDLE_MAN"])
def test_unicode_observation_survives_ascii_console_and_sanitized_receipt(
        pinned, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str) -> None:
    root, pin = pinned
    calls = fake_launch(monkeypatch, FakeProcess(events()), arm=arm)
    observation = codex_pair.run_arm(root, TASK, arm=arm, pin=pin, cli=CLI,
                                     expected_cli_version=CLI.version)
    assert len(calls) == 1 and observation.final_answer == ANSWER
    assert observation.receipt["status"] == "SUCCESS"
    assert observation.receipt["metrics"]["input_tokens"] == 101
    assert observation.receipt["metrics"]["cached_input_tokens"] == 20
    assert observation.receipt["semantic_review"] is None
    stream = io.StringIO()
    receipt = tmp_path / "results" / "arm.json"
    assert codex_pair.record_and_render(observation, receipt, stream) == "RENDERED"
    assert stream.getvalue().isascii() and "\\u2192" in stream.getvalue()
    persisted = receipt.read_text(encoding="ascii")
    assert json.loads(persisted)["task_sha256"] == hashlib.sha256(TASK.encode()).hexdigest()
    assert json.loads(persisted)["output_rendering"] == "RENDERED"
    assert ANSWER not in persisted and TASK not in persisted
    assert "turn.completed" not in persisted and "agent_message" not in persisted
    assert "synthetic stderr" not in persisted and "fake-codex" not in persisted


def test_render_failure_is_separate_from_captured_model_result(
        pinned, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, pin = pinned
    fake_launch(monkeypatch, FakeProcess(events()), arm="BASELINE")
    observation = codex_pair.run_arm(root, TASK, arm="BASELINE", pin=pin,
                                     cli=CLI, expected_cli_version=CLI.version)

    class BrokenConsole:
        def write(self, _value):
            raise UnicodeEncodeError("cp1252", "\u2192", 0, 1, "cannot encode")

        def flush(self):
            pass

    receipt = tmp_path / "results" / "arm.json"
    assert codex_pair.record_and_render(observation, receipt, BrokenConsole()) == "OUTPUT_RENDERING_FAILURE"
    assert observation.final_answer == ANSWER  # Still available for semantic review.
    assert observation.receipt["status"] == "SUCCESS"
    saved = json.loads(receipt.read_text(encoding="ascii"))
    assert saved["metrics"]["input_tokens"] == 101
    assert saved["status"] == "SUCCESS"
    assert saved["output_rendering"] == "OUTPUT_RENDERING_FAILURE"


@pytest.mark.parametrize("kind,reason", [
    ("timeout", "TIMEOUT"),
    ("nonzero", "CODEX_EXIT_NONZERO"),
    ("malformed", "MALFORMED_EVENTS"),
    ("external", "UNEXPECTED_EXTERNAL_TOOL_ACTIVITY"),
    ("mutation", "READ_ONLY_INTEGRITY_FAILURE"),
])
def test_baseline_failure_modes_preserve_metrics_without_real_codex(
        pinned, monkeypatch: pytest.MonkeyPatch, kind: str, reason: str) -> None:
    root, pin = pinned
    process = FakeProcess(
        events(malformed=kind == "malformed", external=kind == "external"),
        code=1 if kind == "nonzero" else 0, timeout=kind == "timeout",
        change=(lambda: (root / "queue.py").write_text("mutated\n", encoding="utf-8"))
        if kind == "mutation" else None)
    calls = fake_launch(monkeypatch, process, arm="BASELINE")
    observation = codex_pair.run_arm(root, TASK, arm="BASELINE", pin=pin,
                                     cli=CLI, expected_cli_version=CLI.version, timeout=3)
    assert len(calls) == 1 and reason in observation.receipt["failure_reasons"]
    assert observation.receipt["metrics"]["input_tokens"] == 101
    assert observation.final_answer == ANSWER
    assert observation.receipt["repository"]["unchanged"] == (kind != "mutation")
    assert process.killed == (kind == "timeout")


def test_version_mismatch_prevents_any_launch(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    root, pin = pinned
    monkeypatch.setattr(codex_pair, "_Popen", lambda *_args, **_kwargs: pytest.fail("launched"))
    with pytest.raises(RuntimeError, match="CLI version"):
        codex_pair.run_arm(root, TASK, arm="BASELINE", pin=pin, cli=CLI,
                           expected_cli_version="different")


def test_script_requires_confirmation_and_locked_schedule_before_discovery(
        pinned, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _pin = pinned
    plan = Path(__file__).resolve().parents[1] / "docs/codex_variance_calibration_plan.json"
    monkeypatch.setattr("scripts.run_codex_pair_experiment.discover_codex",
                        lambda: pytest.fail("Codex discovery reached"))
    base = ["--plan", str(plan), "--snapshot", str(root), "--task-id", "M01",
            "--arm", "MIDDLE_MAN", "--receipt", str(tmp_path / "call-2.json")]
    with pytest.raises(SystemExit):
        experiment_main(base)
    with pytest.raises(SystemExit):
        experiment_main(base + ["--confirm-external-service", "--call-number", "2"])
    manifest = json.loads(plan.read_text(encoding="utf-8"))
    (tmp_path / "call-1.json").write_text(json.dumps({
        "status": "SUCCESS", "arm": "BASELINE", "output_rendering": "OUTPUT_RENDERING_FAILURE",
        "task_sha256": manifest["task"]["task_sha256"],
        "source_commit": manifest["source"]["commit"],
        "source_tree": manifest["source"]["tree"],
        "cli_version": manifest["execution"]["expected_codex_cli_version"],
        "repository": {"unchanged": True},
        "metrics": {"external_tool_activity_count": 0, "mcp_call_count": 0},
    }), encoding="ascii")
    with pytest.raises(SystemExit):
        experiment_main(base + ["--confirm-external-service", "--call-number", "2"])


def test_receipt_refuses_overwrite(pinned, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, pin = pinned
    fake_launch(monkeypatch, FakeProcess(events()), arm="BASELINE")
    observation = codex_pair.run_arm(root, TASK, arm="BASELINE", pin=pin,
                                     cli=CLI, expected_cli_version=CLI.version)
    receipt = tmp_path / "arm.json"
    assert codex_pair.record_and_render(observation, receipt, io.StringIO()) == "RENDERED"
    with pytest.raises(FileExistsError, match="already exists"):
        codex_pair.record_and_render(observation, receipt, io.StringIO())
