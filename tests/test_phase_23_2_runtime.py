from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.claude_benchmark import runtime_probe
from middle_man.gateway.claude_benchmark.infrastructure import ClaudeCli


FLAGS = ("-p", "--output-format", "--verbose", "--model", "--tools",
         "--safe-mode", "--restricted", "--strict-mcp-config", "--no-session-persistence")
CLI = ClaudeCli("claude", "test-release", FLAGS, "os=nt", None,
                supports_stream_json=True, supports_tool_filtering=True,
                supports_mcp_isolation=True, supports_safe_mode=True,
                supports_restricted_mode=True, supports_no_session_persistence=True)


def stream(kind: str, *, error: bool = False, mcp: bool = False) -> str:
    if error:
        events = [
            {"type": "system", "subtype": "init", "session_id": "synthetic"},
            {"type": "assistant", "message": {"model": "<synthetic>", "content": []}},
            {"type": "result", "subtype": "error_during_execution", "is_error": True,
             "result": "authentication required", "usage": {"input_tokens": 0},
             "total_cost_usd": 0.0},
        ]
    else:
        tools = (["Read"] if kind == "read-only" else ["Read", "Write", "Read", "Bash"])
        if mcp:
            tools.append("mcp__unexpected")
        blocks = [{"type": "tool_use", "id": f"tool-{index}", "name": name,
                   "input": {"file_path": "sentinel.txt" if name == "Read" else "allowed.txt"}}
                  for index, name in enumerate(tools)]
        results = [{"type": "tool_result", "tool_use_id": f"tool-{index}",
                    "content": "ok"} for index in range(len(tools))]
        events = [
            {"type": "system", "subtype": "init", "session_id": "synthetic", "mcp_servers": []},
            {"type": "assistant", "message": {"model": "observed-test-model",
                                              "content": blocks}},
            {"type": "user", "message": {"content": results}},
            {"type": "result", "subtype": "success", "is_error": False,
             "result": "MIDDLE_MAN_CLAUDE_READ_PROBE" if kind == "read-only" else "done",
             "usage": {"input_tokens": 12, "output_tokens": 4,
                       "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3},
             "total_cost_usd": 0.01, "duration_ms": 200, "duration_api_ms": 150,
             "num_turns": 2},
        ]
    return "\n".join(json.dumps(event) for event in events)


def fake_process(monkeypatch, *, error=False, mutate_read=False, timeout=False,
                 mcp=False, primary_changed=False):
    original = subprocess.run
    calls = []

    def run(args, **kwargs):
        if args[0] != "claude":
            return original(args, **kwargs)
        calls.append(args)
        cwd = Path(kwargs["cwd"])
        kind = "read-only" if args[args.index("--tools") + 1] == "Read,Glob,Grep" else "workspace-write"
        if timeout:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=b"")
        if kind == "read-only" and mutate_read:
            (cwd / "forbidden.txt").write_text("unexpected", encoding="utf-8")
        if kind == "workspace-write" and not error:
            (cwd / "allowed.txt").write_bytes(runtime_probe.WRITE_SENTINEL)
        return subprocess.CompletedProcess(args, 1 if error else 0, stream(kind, error=error, mcp=mcp),
                                           "AUTH SECRET_CREDENTIAL" if error else "")

    monkeypatch.setattr(runtime_probe.subprocess, "run", run)
    state = {"calls": 0}

    def signature(_):
        state["calls"] += 1
        head = "changed" if primary_changed and state["calls"] > 2 else "head"
        return head, (), tuple(runtime_probe.FROZEN_HASHES.items())

    monkeypatch.setattr(runtime_probe, "_primary_signature", signature)
    return calls


def test_confirmation_guard_prevents_process(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_probe.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("process started"))
    with pytest.raises(ValueError, match="confirm-external-service"):
        runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=False)
    with pytest.raises(SystemExit, match="confirm-external-service"):
        main(["claude", "benchmark", "runtime-probe", "--repo", str(tmp_path)])


def test_dry_run_never_starts_claude(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_probe.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("process started"))
    result = runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=False, dry_run=True)
    assert result["model_calls"] == 0 and len(result["commands"]) == 2
    assert all("--strict-mcp-config" in command for command in result["commands"])
    assert all("--dangerously-skip-permissions" not in command for command in result["commands"])


def test_two_successful_mock_probes_and_sanitized_artifact(monkeypatch, tmp_path):
    calls = fake_process(monkeypatch)
    result = runtime_probe.run_runtime_probes(
        tmp_path, CLI, confirmed=True,
        artifact_root=tmp_path / ".middle_man_cache" / "claude_runtime_probes")
    assert result["model_calls"] == len(calls) == 2
    read, write = result["probes"]
    assert read["status"] == "PASS" and read["sentinel_returned"]
    assert not read["forbidden_exists"] and read["filesystem_invariant_passed"]
    assert read["tool_names"] == ("Read",) and read["file_reads"] == 1
    assert write["status"] == "PASS" and write["allowed_valid"]
    assert write["tool_names"] == ("Read", "Write", "Read", "Bash")
    assert write["bash_calls"] == 1 and write["tool_result_count"] == 4
    assert write["usage"]["input_tokens"] == 12 and write["cost_usd"] == 0.01
    assert write["observed_model"] == "observed-test-model"
    artifact = tmp_path / ".middle_man_cache" / "claude_runtime_probes" / result["run_id"] / "result.json"
    saved = artifact.read_text(encoding="utf-8")
    assert "MIDDLE_MAN_CLAUDE_READ_PROBE" not in saved
    assert json.loads(saved)["model_calls"] == 2
    assert not (tmp_path / "allowed.txt").exists()
    assert not (tmp_path / ".mcp.json").exists()


def test_auth_failure_stops_after_one_and_sanitizes(monkeypatch, tmp_path):
    calls = fake_process(monkeypatch, error=True)
    result = runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=True)
    assert result["model_calls"] == len(calls) == 1
    probe = result["probes"][0]
    assert probe["status"] == "FAIL" and probe["error_category"] == "authentication_error"
    assert probe["event_types"] == ("assistant", "result", "system")
    assert probe["usage"]["input_tokens"] == 0 and probe["cost_usd"] == 0.0
    assert probe["observed_model"] == "<synthetic>"
    assert "SECRET_CREDENTIAL" not in json.dumps(result)


def test_readonly_mutation_fails_and_prevents_second_call(monkeypatch, tmp_path):
    calls = fake_process(monkeypatch, mutate_read=True)
    result = runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=True)
    assert len(calls) == result["model_calls"] == 1
    assert result["probes"][0]["status"] == "FAIL"
    assert not result["probes"][0]["filesystem_invariant_passed"]


def test_timeout_stops_without_retry(monkeypatch, tmp_path):
    calls = fake_process(monkeypatch, timeout=True)
    result = runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=True)
    assert len(calls) == result["model_calls"] == 1
    assert result["probes"][0]["timed_out"]
    assert result["probes"][0]["error_category"] == "timeout"


def test_unexpected_mcp_tool_invalidates_probe(monkeypatch, tmp_path):
    calls = fake_process(monkeypatch, mcp=True)
    result = runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=True)
    assert len(calls) == 1
    assert not result["probes"][0]["mcp_isolation_passed"]


def test_primary_change_stops_after_first_call(monkeypatch, tmp_path):
    calls = fake_process(monkeypatch, primary_changed=True)
    result = runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=True)
    assert len(calls) == 1 and result["probes"][0]["status"] == "FAIL"
    assert not result["primary_integrity_passed"]


def test_memory_contamination_stops_before_model_call(monkeypatch, tmp_path):
    calls = fake_process(monkeypatch)
    monkeypatch.setattr(runtime_probe, "require_memory_isolation",
                        lambda _: (_ for _ in ()).throw(RuntimeError("memory contamination")))
    with pytest.raises(RuntimeError, match="memory contamination"):
        runtime_probe.run_runtime_probes(tmp_path, CLI, confirmed=True)
    assert calls == []


def test_observed_receipt_is_not_raw_stream_or_benchmark_result():
    path = Path(__file__).parent / "fixtures" / "claude_runtime_auth_failure_receipt.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source"].endswith("not a raw stream")
    assert data["event_types"] == ["assistant", "result", "system"]
    assert data["usage"]["input_tokens"] == 0
    assert data["cost_usd"] == 0.0 and data["tool_names"] == []
    assert "account" not in json.dumps(data).lower()
