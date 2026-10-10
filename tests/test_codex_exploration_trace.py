"""Synthetic-only checks for the research trace; never launch Codex."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from middle_man.experiments import codex_exploration_trace as trace
from middle_man.gateway.codex_runner.events import parse_production_events


def _repo(tmp_path: Path) -> Path:
    folder = tmp_path / "app"
    folder.mkdir()
    (folder / "a.py").write_text("SYNTHETIC_SOURCE_CONTENT\n", encoding="utf-8")
    (folder / "b.py").write_text("other\n", encoding="utf-8")
    (tmp_path / ".env").write_text("NOT_A_REAL_SECRET\n", encoding="utf-8")
    return tmp_path


def _events(*commands: object) -> str:
    rows = [{"type": "thread.started", "thread_id": "synthetic"}]
    rows.extend({"type": "item.completed", "item": {
        "type": "command_execution", "command": command,
        "aggregated_output": "SYNTHETIC_SOURCE_CONTENT",
    }} for command in commands)
    rows.append({"type": "turn.completed", "usage": {
        "input_tokens": 20, "cached_input_tokens": 3, "output_tokens": 5,
    }})
    return "\n".join(json.dumps(row) for row in rows)


def test_ordered_reads_multiple_files_and_production_parity(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    payload = _events("Get-Content app/a.py", "Get-Content app/b.py", "Get-Content app/a.py")
    result = trace.analyze_exploration_trace(payload, root)
    steps = result["steps"]
    assert [step["command_position"] for step in steps] == [1, 2, 3]
    assert [step["target_paths"] for step in steps] == [("app/a.py",), ("app/b.py",), ("app/a.py",)]
    assert [step["previously_read_paths"] for step in steps] == [(), (), ("app/a.py",)]
    assert result["summary"]["possible_repeated_read_commands"] == 1
    assert (result["summary"]["explicit_reads"], result["summary"]["unique_files"],
            result["summary"]["rereads"]) == (3, 2, 1)
    production = parse_production_events(payload, root).parsed.native
    assert (result["summary"]["native_tool_calls"], result["summary"]["explicit_reads"],
            result["summary"]["unique_files"], result["summary"]["rereads"]) == (
            production.tool_calls, production.file_reads, len(production.unique_files), production.rereads)
    assert result == trace.analyze_exploration_trace(payload.splitlines(), root)
    serialized = json.dumps(result)
    for forbidden in ("Get-Content", "SYNTHETIC_SOURCE_CONTENT", "synthetic\"", "aggregated_output"):
        assert forbidden not in serialized


def test_repeated_search_target_is_not_duplicate_query_claim(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = trace.analyze_exploration_trace(_events(
        "rg -n first app/a.py", "rg -n different app/a.py", "rg -n third app/b.py"), root)
    steps = result["steps"]
    assert [step["operation_type"] for step in steps] == ["search"] * 3
    assert [step["revisited_search_target_paths"] for step in steps] == [(), ("app/a.py",), ()]
    assert result["summary"]["revisited_search_target_commands"] == 1
    assert result["summary"]["searches"] == 3
    assert "different" not in json.dumps(result)


def test_mixed_unsupported_listing_git_and_unknown_targets(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    payload = _events("Get-Content app/a.py | Select-String foo", "rg --files",
                      "git status --porcelain", "unrecognized-tool --opaque",
                      "rg -n foo app/*.py")
    result = trace.analyze_exploration_trace(payload, root)
    steps = result["steps"]
    assert [step["operation_type"] for step in steps] == [
        "explicit_read", "listing", "git_inspection", "unclassified", "search"]
    assert steps[0]["operation_details_unknown"] and steps[0]["explicit_file_read_count"] == 1
    assert steps[3]["unclassified"] and steps[3]["paths_unknown"]
    assert steps[4]["paths_unknown"] and not steps[4]["target_paths"]
    native = parse_production_events(payload, root).parsed.native
    assert (result["summary"]["native_tool_calls"], result["summary"]["explicit_reads"],
            result["summary"]["searches"], result["summary"]["listings"],
            result["summary"]["unclassified_commands"]) == (
            native.tool_calls, native.file_reads, native.search_calls,
            native.listing_calls, native.unclassified_commands)


def test_malformed_events_and_nonstring_command_are_bounded_unknown(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    payload = "{broken\n" + _events(["Get-Content", "app/a.py"])
    result = trace.analyze_exploration_trace(payload, root)
    assert result["summary"]["malformed_event_lines"] == (1,)
    assert result["steps"][0]["operation_details_unknown"]
    assert result["summary"]["native_tool_calls"] == 1
    assert result["summary"]["external_inference_calls"] == 0
    assert "broken" not in json.dumps(result)


def test_secret_unsafe_and_external_paths_never_leave_analyzer(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    outside = tmp_path.parent / "external.py"
    outside.write_text("outside\n", encoding="utf-8")
    secret = "Bearer abcdefghijklmnop"
    payload = _events("Get-Content .env", f'Get-Content "{outside}"',
                      "Get-Content app/../app/a.py", f"rg -n {secret} app/a.py")
    result = trace.analyze_exploration_trace(payload, root)
    assert result["steps"][0]["target_paths"] == ()
    assert result["steps"][0]["paths_unknown"]
    assert result["steps"][1]["target_paths"] == ()
    assert result["steps"][2]["target_paths"] == ("app/a.py",)
    serialized = json.dumps(result)
    assert str(outside) not in serialized and ".env" not in serialized
    assert secret not in serialized and "abcdefghijklmnop" not in serialized


def test_windows_powershell_and_explicit_fixture_input(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fixture = tmp_path / "synthetic-events.jsonl"
    fixture.write_text(_events('Get-Content -LiteralPath "app/a.py"',
                               'Select-String -Path app/a.py -Pattern foo'), encoding="utf-8")
    result = trace.analyze_exploration_trace(fixture.read_text(encoding="utf-8"), root)
    assert result["steps"][0]["target_paths"] == ("app/a.py",)
    assert result["steps"][1]["operation_type"] == "search"
    assert result["steps"][1]["target_paths"] == ("app/a.py",)


def test_input_and_command_bounds_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setattr(trace, "MAX_COMMANDS", 1)
    with pytest.raises(ValueError, match="command count"):
        trace.analyze_exploration_trace(_events("Get-Content app/a.py", "Get-Content app/b.py"), root)
    monkeypatch.setattr(trace, "MAX_INPUT_BYTES", 8)
    with pytest.raises(ValueError, match="input exceeds"):
        trace.analyze_exploration_trace(_events("Get-Content app/a.py"), root)


def test_malformed_line_metadata_is_bounded(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = trace.analyze_exploration_trace("{broken\n" * 40 + _events("Get-Content app/a.py"), root)
    assert result["summary"]["malformed_event_count"] == 40
    assert result["summary"]["malformed_event_lines"] == tuple(range(1, 33))
