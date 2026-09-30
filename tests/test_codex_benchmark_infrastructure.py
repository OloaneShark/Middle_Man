from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark import infrastructure, runner
from middle_man.gateway.codex_benchmark.tasks import TASKS


def test_invocations_share_explicit_elevated_sandbox_and_preserve_path(tmp_path: Path) -> None:
    root = tmp_path / "Dennis O'Loane" / "benchmark copy"
    root.mkdir(parents=True)
    baseline = runner.build_invocation("codex", TASKS[0], "baseline", root, model="gpt-6-sol", effort="high")
    optimized = runner.build_invocation("codex", TASKS[0], "optimized", root, model="gpt-6-sol", effort="high")
    for invocation in (baseline, optimized):
        assert "--ignore-user-config" in invocation
        assert 'windows.sandbox="elevated"' in invocation
        assert invocation[invocation.index("-C") + 1] == str(root.resolve())
        assert "danger-full-access" not in invocation and "--dangerously-bypass-approvals-and-sandbox" not in invocation
    assert not any("mcp_servers." in arg for arg in baseline)
    settings = {optimized[index + 1].split("=", 1)[0]: optimized[index + 1].split("=", 1)[1]
                for index, arg in enumerate(optimized[:-1]) if arg == "-c" and "mcp_servers." in optimized[index + 1]}
    args = json.loads(settings["mcp_servers.middle-man.args"])
    assert args[args.index("--repo") + 1] == str(root.resolve())
    assert args[0] == "-I" and args[-1] == "codex-core"
    assert settings["mcp_servers.middle-man.required"] == "true"


def test_primary_usage_signature_detects_changes(tmp_path: Path) -> None:
    assert infrastructure.primary_usage_signature(tmp_path) is None
    path = tmp_path / ".middle_man_cache" / "mcp_usage.jsonl"
    path.parent.mkdir()
    path.write_text("one\n", encoding="utf-8")
    before = infrastructure.primary_usage_signature(tmp_path)
    path.write_text("one\ntwo\n", encoding="utf-8")
    assert before != infrastructure.primary_usage_signature(tmp_path)


def test_local_probe_uses_argv_and_elevated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observed = []
    monkeypatch.setattr(infrastructure.shutil, "which", lambda name: "C:/Windows/powershell.exe")

    def fake_run(argv, **kwargs):
        observed.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "original", "")

    monkeypatch.setattr(infrastructure.subprocess, "run", fake_run)
    root = tmp_path / "Dennis O'Loane"
    root.mkdir()
    read_script, readonly_script, write_script = infrastructure._marker_scripts(root)
    infrastructure._probe("codex", root, ":read-only", read_script)
    argv, kwargs = observed[0]
    assert argv[1:3] == ["-c", 'windows.sandbox="elevated"']
    assert argv[argv.index("-C") + 1] == str(root)
    assert kwargs["cwd"] == root
    literal = "'" + str((root / "marker.txt").resolve()).replace("'", "''") + "'"
    assert argv[-1] == f"Get-Content -LiteralPath {literal}"
    assert literal in readonly_script and literal in write_script
    assert "-LiteralPath marker.txt" not in " ".join((read_script, readonly_script, write_script))


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell Windows cwd regression")
def test_marker_read_is_independent_of_powershell_cwd(tmp_path: Path) -> None:
    root = tmp_path / "probe O'Loane"
    root.mkdir()
    (root / "marker.txt").write_text("original\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    read_script, _, _ = infrastructure._marker_scripts(root)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", read_script], cwd=elsewhere,
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "original"


def test_marker_script_rejects_resolved_path_outside_root(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "disposable root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    original_resolve = Path.resolve

    def displaced_marker(path: Path, *args: object, **kwargs: object) -> Path:
        return outside if path.name == "marker.txt" else original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", displaced_marker)
    with pytest.raises(ValueError, match="must stay inside"):
        infrastructure._marker_scripts(root)


def test_failed_preflight_prevents_artifact_and_codex_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    failed = infrastructure.CodexInfrastructurePreflight(
        "codex-cli test", "native-windows", "elevated", "system-temp", True, True, True,
        1, False, False, None, False, False, False, ("sandbox read failed",))
    monkeypatch.setattr(runner, "_codex_executable", lambda: "codex")
    monkeypatch.setattr(infrastructure, "run_local_preflight", lambda *args, **kwargs: failed)
    artifacts = tmp_path / "artifacts"
    with pytest.raises(RuntimeError, match="preflight failed"):
        runner.run_suite(("preemption",), repository_root=tmp_path, artifact_base=artifacts)
    assert not artifacts.exists()
    with pytest.raises(dataclasses.FrozenInstanceError):
        failed.passed = True
