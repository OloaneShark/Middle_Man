from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark.events import parse_codex_events
from middle_man.gateway.codex_benchmark.overlap import measure_delivery
from middle_man.gateway.codex_benchmark.runner import _evaluate, build_invocation, isolation_warnings
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint


def test_documented_event_fields_and_native_read_accounting(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "state.py").write_text("pass\n", encoding="utf-8")
    fixture = (Path(__file__).parent / "fixtures" / "codex_events.jsonl").read_text(encoding="utf-8")
    result = parse_codex_events(fixture.splitlines(), tmp_path)
    assert result.thread_id == "fixture-thread"
    assert result.native.tool_calls == 5
    assert result.native.file_reads == 2
    assert result.native.unique_files == ("app/state.py",)
    assert result.native.rereads == 1
    assert (result.native.search_calls, result.native.listing_calls, result.native.git_inspections) == (1, 1, 1)
    assert result.mcp_calls == (("middle-man", "middleman_context_pack"),)
    assert result.file_change_events == 1
    assert result.usage.input_tokens == 1000 and result.usage.cached_input_tokens == 200
    assert result.usage.output_tokens == 300 and result.usage.total_tokens is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.usage.input_tokens = 0
    assert all("result" not in event for event in result.sanitized_events)


def _pack(path: str, digest: str, start: int, end: int, *, size: int = 4) -> dict:
    return {"tool": "middleman_context_pack", "success": True, "pack_fingerprint": f"{path}-{start}-{end}",
            "metrics": {"raw_candidate_tokens": 20, "selected_tokens": end - start + 1, "result_tokens": 15},
            "delivery": [{"path": path, "content_hash": digest, "start_line": start,
                          "end_line": end, "line_bytes": [size] * (end - start + 1)}]}


@pytest.mark.parametrize(("packs", "unique", "repeated"), [
    ((("a", "h", 1, 3), ("a", "h", 1, 3)), 12, 12),
    ((("a", "h", 1, 3), ("a", "h", 3, 5)), 20, 4),
    ((("a", "h", 1, 5), ("a", "h", 2, 3)), 20, 8),
    ((("a", "h", 1, 3), ("a", "h", 4, 6)), 24, 0),
    ((("a", "h", 1, 3), ("b", "h", 1, 3)), 24, 0),
    ((("a", "h1", 1, 3), ("a", "h2", 1, 3)), 24, 0),
    ((("a", "h", 1, 3), ("a", "h", 2, 4), ("a", "h", 3, 5)), 20, 16),
])
def test_line_identity_overlap(packs: tuple, unique: int, repeated: int) -> None:
    result = measure_delivery(_pack(*values) for values in packs)
    assert result.overlap_available
    assert result.unique_source_bytes == unique
    assert result.repeated_source_bytes == repeated
    assert result.overlap_ratio == repeated / (unique + repeated)
    assert result.non_source_pack_overhead_estimate == 15 * len(packs) - sum(
        values[3] - values[2] + 1 for values in packs)


def test_missing_delivery_is_unavailable_not_zero() -> None:
    item = _pack("a.py", "h", 1, 2)
    item.pop("delivery")
    result = measure_delivery([item])
    assert not result.overlap_available and result.overlap_ratio is None


def test_snapshot_isolation_and_fixture_preconditions(tmp_path: Path) -> None:
    for task in (task for task in TASKS if not task.read_only):
        pair = tmp_path / task.id
        baseline, optimized, fingerprint = prepare_pair(task, pair, "Use Middle_Man for broad context.\n")
        assert source_fingerprint(baseline) == source_fingerprint(optimized) == fingerprint
        assert not (baseline / "AGENTS.md").exists()
        assert (optimized / "AGENTS.md").exists()
        assert subprocess.run(["git", "-C", str(baseline), "status", "--porcelain"],
                              capture_output=True, text=True, check=True).stdout == ""
        fixture_file = "middle_man/lab/config.py" if task.id == "large-edit-v1" else "app/config.py"
        original = (optimized / fixture_file).read_bytes()
        (baseline / fixture_file).write_text("changed\n", encoding="utf-8")
        assert (optimized / fixture_file).read_bytes() == original
        code = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=optimized,
                              capture_output=True, text=True).returncode
        assert (code != 0) == (task.id == "oauth-bug")


def test_invocation_isolation_and_windows_path() -> None:
    root = Path(r"C:\Users\Dennis O'Loane\OneDrive\Desktop\Middle_Man\fixture")
    task = TASKS[0]
    baseline = build_invocation("codex", task, "baseline", root, model="gpt-6-sol", effort="high")
    optimized = build_invocation("codex", task, "optimized", root, model="gpt-6-sol", effort="high")
    assert "--ignore-user-config" in baseline and not any("mcp_servers.middle-man" in part for part in baseline)
    assert "mcp_servers.middle-man.enabled=true" in optimized
    assert any(part.startswith("mcp_servers.middle-man.command=") for part in optimized)
    assert "--json" in baseline and "--ephemeral" in baseline
    assert 'model_reasoning_effort="high"' in baseline
    override = next(part for part in optimized if part.startswith("mcp_servers.middle-man.args="))
    args = json.loads(override.split("=", 1)[1])
    assert args[args.index("--repo") + 1] == str(root.resolve())
    assert args[-1] == "codex-core" and args[0] == "-I"


def test_baseline_contamination_and_read_only_mutation_are_failures(tmp_path: Path) -> None:
    task = TASKS[0]
    passed, notes, _, _ = _evaluate(task, tmp_path, " ".join(task.required_facts), (), (), (), 0, 0)
    assert passed and not notes
    passed, notes, _, _ = _evaluate(task, tmp_path, " ".join(task.required_facts), ("file.py",),
                                    (), (" M file.py",), 0, 1)
    assert not passed and "read-only repository was modified" in notes


def test_dry_run_never_creates_artifacts_or_calls_codex(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner._codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("Codex must not run")))
    main(["codex", "benchmark", "run-all", "--repo", str(tmp_path), "--dry-run"])
    output = capsys.readouterr().out
    assert "DRY RUN" in output and "--ignore-user-config" in output
    assert "mcp_servers.middle-man.enabled=true" in output
    assert not (tmp_path / ".middle_man_cache").exists()


def test_mcp_contamination_and_wrong_root_are_explicit() -> None:
    assert 'baseline contaminated by an MCP call' in isolation_warnings(
        'baseline', (), (('node_repl', 'js'),))
    warnings = isolation_warnings('optimized', (), (('middle-man', 'middleman_context_pack'),))
    assert any('snapshot usage records' in item for item in warnings)
    assert not isolation_warnings('optimized', ({'tool': 'middleman_context_pack'},),
                                  (('middle-man', 'middleman_context_pack'),))
