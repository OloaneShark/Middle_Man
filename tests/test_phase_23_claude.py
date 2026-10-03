from __future__ import annotations

import json
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.claude_benchmark.events import parse_stream_json
from middle_man.gateway.claude_benchmark.infrastructure import (
    ClaudeCli, discover_cli, git_clean, memory_contamination, require_memory_isolation,
)
from middle_man.gateway.claude_benchmark.runner import (
    READ_TOOLS, WRITE_TOOLS, build_invocation, preview_pair, prepare_snapshots,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS


FIXTURES = Path(__file__).parent / "fixtures"
FLAGS = ("-p", "--output-format", "--verbose", "--model", "--tools", "--max-turns",
         "--setting-sources")
CLI = ClaudeCli("claude", "synthetic", FLAGS, "os=nt", None)


def task(name):
    return next(item for item in TASKS if item.id == name)


def events(name, **options):
    return parse_stream_json((FIXTURES / name).read_text(encoding="utf-8").splitlines(), **options)


def test_cli_missing(monkeypatch):
    monkeypatch.setattr("middle_man.gateway.claude_benchmark.infrastructure.shutil.which", lambda _: None)
    value = discover_cli()
    assert not value.ready and value.version is None and "PATH" in value.error


def test_cli_discovery_version_help_only(monkeypatch):
    calls = []
    monkeypatch.setattr("middle_man.gateway.claude_benchmark.infrastructure.shutil.which",
                        lambda _: "C:/claude.exe")

    def fake_run(args, **kwargs):
        calls.append(args[-1])
        return type("Result", (), {"stdout": "2.0.0" if args[-1] == "--version" else
                     "-p --output-format --verbose --model --tools --max-turns --setting-sources",
                     "stderr": ""})()

    monkeypatch.setattr("middle_man.gateway.claude_benchmark.infrastructure.subprocess.run", fake_run)
    found = discover_cli()
    assert found.ready and found.version == "2.0.0"
    assert calls == ["--version", "--help"]
    assert "--setting-sources" in found.flags


def test_discovery_fails_closed_on_missing_flags(monkeypatch):
    monkeypatch.setattr("middle_man.gateway.claude_benchmark.infrastructure.shutil.which",
                        lambda _: "claude")
    monkeypatch.setattr("middle_man.gateway.claude_benchmark.infrastructure.subprocess.run",
                        lambda args, **kwargs: type("Result", (), {"stdout": "1.0" if args[-1] == "--version" else
                                                                  "-p --verbose", "stderr": ""})())
    assert not discover_cli().ready


def test_command_profiles_model_and_turns():
    readonly = build_invocation(CLI, model="sonnet", read_only=True, max_turns=20, prompt="task")
    write = build_invocation(CLI, model="custom-model", read_only=False, max_turns=None, prompt="edit")
    assert readonly[:3] == ("claude", "-p", "task")
    assert readonly[readonly.index("--tools") + 1] == READ_TOOLS
    assert "Bash" not in readonly[readonly.index("--tools") + 1]
    assert readonly[-2:] == ("--max-turns", "20")
    assert write[write.index("--tools") + 1] == WRITE_TOOLS
    assert write[write.index("--model") + 1] == "custom-model"
    assert "--max-turns" not in write
    assert not any("dangerously" in part for part in readonly + write)
    isolated = build_invocation(CLI, model="sonnet", read_only=True, max_turns=None,
                                prompt="task", setting_sources="project")
    assert isolated[-2:] == ("--setting-sources", "project")


def test_command_requires_documented_flags_and_valid_turns():
    with pytest.raises(RuntimeError):
        build_invocation(ClaudeCli(None, None, (), "os=nt", "absent"),
                         model="sonnet", read_only=True, max_turns=None, prompt="task")
    with pytest.raises(ValueError):
        build_invocation(CLI, model="sonnet", read_only=True, max_turns=0, prompt="task")
    with pytest.raises(RuntimeError):
        build_invocation(ClaudeCli("claude", "x", FLAGS[:-2], "os=nt", None),
                         model="sonnet", read_only=True, max_turns=5, prompt="task")


def test_success_usage_cost_and_native_actions():
    result = events("claude_success.jsonl")
    assert result.status == "success" and result.session_id == "synthetic-session"
    assert result.result_text == "Synthetic answer" and result.observed_model == "synthetic-sonnet"
    assert (result.duration_ms, result.duration_api_ms, result.num_turns) == (1100, 900, 2)
    assert (result.usage.input_tokens, result.usage.output_tokens,
            result.usage.cache_creation_input_tokens, result.usage.cache_read_input_tokens) == (22, 8, 4, 6)
    assert result.total_cost_usd == 0.003
    assert [action.kind for action in result.actions] == ["read", "search", "listing", "read", "read", "bash"]
    assert result.unique_files == ("app/a.py", "app/b.py")
    assert result.rereads == 1
    assert (result.tool_calls, result.file_reads, result.searches,
            result.listings, result.bash_commands) == (6, 3, 1, 1, 1)


def test_absent_usage_and_edit_actions():
    result = events("claude_usage_absent.jsonl")
    assert result.usage.input_tokens is None and result.usage.output_tokens is None
    assert result.total_cost_usd == 0.01
    assert [item.kind for item in result.actions] == ["write", "edit"]
    assert (result.writes, result.edits) == (1, 1)


def test_message_usage_fallback_only_observed_fields():
    result = parse_stream_json([
        json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 3}, "content": []}}),
        json.dumps({"type": "result", "subtype": "success", "result": "ok"}),
    ])
    assert result.usage.input_tokens == 3 and result.usage.output_tokens is None


def test_error_timeout_incomplete_and_malformed():
    assert events("claude_error.jsonl").status == "error"
    assert events("claude_incomplete.jsonl").status == "incomplete"
    timeout = events("claude_incomplete.jsonl", timed_out=True)
    assert timeout.status == "timeout" and "process timed out" in timeout.warnings
    with pytest.raises(ValueError, match="line 2"):
        events("claude_malformed.jsonl")
    assert "line 2" in events("claude_malformed.jsonl", strict=False).warnings[0]


@pytest.mark.parametrize("name", ("CLAUDE.md", "CLAUDE.local.md"))
def test_snapshot_memory_rejected(tmp_path, name):
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / name).write_text("memory", encoding="utf-8")
    with pytest.raises(RuntimeError, match="memory"):
        require_memory_isolation(root)


@pytest.mark.parametrize("name", ("CLAUDE.md", "CLAUDE.local.md"))
def test_ancestor_memory_rejected(tmp_path, name):
    child = tmp_path / "parent" / "snapshot"
    child.mkdir(parents=True)
    (tmp_path / "parent" / name).write_text("memory", encoding="utf-8")
    assert memory_contamination(child)
    with pytest.raises(RuntimeError):
        require_memory_isolation(child)


def test_snapshots_source_identical_committed_clean_and_without_mcp(tmp_path):
    baseline, optimized, fingerprint = prepare_snapshots(task("large-edit-v1"), tmp_path / "pair")
    assert fingerprint and git_clean(baseline) and git_clean(optimized)
    assert not (baseline / ".mcp.json").exists()
    assert not (optimized / ".mcp.json").exists()
    assert not (baseline / ".middle_man_cache").exists()
    assert not (optimized / ".middle_man_cache").exists()
    assert not (baseline / "tests" / "test_middleman_benchmark_acceptance.py").exists()
    assert not (optimized / "tests" / "test_middleman_benchmark_acceptance.py").exists()
    assert not (baseline / "AGENTS.md").exists()
    assert not (optimized / "AGENTS.md").exists()


def test_task_a_auto_locator_source_free_and_no_hidden_tests(tmp_path):
    value = preview_pair(task("preemption-v4"), tmp_path / "pair", CLI)
    assert value.decision == "LOCATOR_USED" and value.model_visible_middle_man_tokens_estimate > 0
    assert value.candidate_source_tokens_estimate >= 10_000
    assert not value.prompt_equal and not value.mcp_registered
    assert value.external_inference_calls == 0 and value.observed_model is None
    assert "source-free locator" in value.optimized_command[2]
    assert "acceptance" not in value.optimized_command[2].lower()
    assert "middleman" not in " ".join(value.optimized_command)


def test_large_edit_auto_bypass_exact_prompt_and_zero_tokens(tmp_path):
    value = preview_pair(task("large-edit-v1"), tmp_path / "pair", CLI)
    assert value.decision == "BYPASSED" and value.prompt_equal
    assert value.baseline_prompt_sha256 == value.optimized_prompt_sha256
    assert value.baseline_command == value.optimized_command
    assert value.model_visible_middle_man_tokens_estimate == 0
    assert not value.mcp_registered


def test_cli_refuses_inference_even_with_confirmation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external process must not start")
    monkeypatch.setattr("subprocess.run", forbidden)
    with pytest.raises(SystemExit, match="dry-run-only"):
        main(["claude", "benchmark", "run", "preemption-v4", "--confirm-external-service"])


def test_cli_dry_run_and_report_never_spawn_claude(monkeypatch, tmp_path, capsys):
    import subprocess

    real_run = subprocess.run

    def guarded(args, **kwargs):
        assert "claude" not in str(args[0]).lower()
        return real_run(args, **kwargs)

    monkeypatch.setattr("subprocess.run", guarded)
    monkeypatch.setattr("middle_man.gateway.claude_benchmark.infrastructure.shutil.which", lambda _: None)
    main(["claude", "benchmark", "run", "large-edit-v1", "--dry-run", "--repo", str(tmp_path)])
    preview = json.loads(capsys.readouterr().out)
    assert preview["decision"] == "BYPASSED" and preview["external_inference_calls"] == 0
    main(["claude", "benchmark", "report", preview["run_id"], "--repo", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["run_id"] == preview["run_id"]
