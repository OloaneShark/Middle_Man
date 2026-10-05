"""Production-only native search observations never become explicit reads."""

from __future__ import annotations

import json
from pathlib import Path

from middle_man.gateway.codex_runner.events import parse_production_events
from middle_man.gateway.codex_runner.search_telemetry import classify_search_command


def _files(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    app.mkdir()
    for name in ("a.py", "b.py", "c.py", "d.py"):
        (app / name).write_text("foo = True\n", encoding="utf-8")
    return app


def test_command_classification_and_safe_targets(tmp_path: Path) -> None:
    _files(tmp_path)
    cases = [
        ('rg -n "foo" app/a.py', True, ("app/a.py",), True, False),
        ('rg -n "foo" app/', True, ("app/",), False, False),
        ('rg -n "foo" .', True, (), False, True),
        ('grep -n "foo" app/a.py', True, ("app/a.py",), True, False),
        ('git grep foo -- app/a.py', True, ("app/a.py",), True, False),
        ('Select-String -Path app/a.py -Pattern foo', True, ("app/a.py",), True, False),
    ]
    for command, content, targets, file_targeted, wide in cases:
        observed = classify_search_command(command, tmp_path)
        assert observed is not None
        assert (observed.content_producing, observed.target_paths,
                observed.file_targeted, observed.repository_wide) == (content, targets, file_targeted, wide)
    listing = classify_search_command("rg --files", tmp_path)
    assert listing is not None and listing.kind == "file_listing_search"
    assert not listing.content_producing and not listing.target_paths
    assert classify_search_command("Get-Content app/a.py", tmp_path) is None


def test_ambiguous_or_external_targets_are_omitted(tmp_path: Path) -> None:
    _files(tmp_path)
    outside = tmp_path.parent / "outside.py"
    outside.write_text("foo\n", encoding="utf-8")
    for command in ('rg -n foo app/a.py | Select-String foo',
                    'rg -n foo app/a.py > result.txt',
                    'rg -n foo app/a.py; Get-Content app/a.py'):
        assert classify_search_command(command, tmp_path) is None
    for target in (str(outside), "app/../app/a.py", "app/*.py"):
        observed = classify_search_command(f'rg -n foo "{target}"', tmp_path)
        assert observed is not None and observed.target_paths == ()
    absolute = tmp_path / "app" / "a.py"
    observed = classify_search_command(f'rg -n "foo" "{absolute}"', tmp_path)
    assert observed is not None and observed.target_paths == ("app/a.py",)
    no_lines = classify_search_command("rg -l -n foo app/a.py", tmp_path)
    assert no_lines is not None and not no_lines.content_producing


def test_production_framing_adds_telemetry_without_reclassifying_reads(tmp_path: Path) -> None:
    _files(tmp_path)
    commands = ["Get-Content app/a.py", 'rg -n "foo" app/b.py', 'rg -n "foo" app/',
                'rg -n "foo" .', "rg --files", "git grep foo -- app/d.py"]
    events = [json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": command}}) for command in commands]
    parsed = parse_production_events("\n".join(events), tmp_path)
    assert parsed.parsed.native.tool_calls == 6
    assert parsed.parsed.native.file_reads == 1
    assert parsed.parsed.native.unique_files == ("app/a.py",)
    assert parsed.parsed.native.search_calls == 4
    assert parsed.parsed.native.listing_calls == 1
    telemetry = parsed.search_telemetry
    assert telemetry.content_search_calls == 4
    assert telemetry.file_targeted_searches == 2
    assert telemetry.repository_wide_searches == 1
    assert telemetry.file_listing_searches == 1
    assert telemetry.searched_paths == ("app/", "app/b.py", "app/d.py")
