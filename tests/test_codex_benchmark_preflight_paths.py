from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark import infrastructure, runner
from middle_man.gateway.codex_benchmark.tasks import TASKS


def test_rejects_snapshot_root_inheriting_agents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("instructions\n", encoding="utf-8")
    child = tmp_path / "cache"
    child.mkdir()
    monkeypatch.setattr(runner, "_codex_version", lambda command: "codex-cli test")
    with pytest.raises(ValueError, match="inherits AGENTS.md"):
        infrastructure.run_local_preflight("codex", model="test", effort="high",
                                           windows_sandbox="unelevated", snapshot_root=child,
                                           repository_root=tmp_path)


def test_explicit_unelevated_still_uses_same_sandbox_for_both_sides(tmp_path: Path) -> None:
    commands = [runner.build_invocation("codex", TASKS[0], mode, tmp_path,
                                        model="gpt-6-sol", effort="high", windows_sandbox="unelevated")
                for mode in ("baseline", "optimized")]
    assert all('windows.sandbox="unelevated"' in command for command in commands)
    assert all("--no-daemon" in command and "--ignore-user-config" in command for command in commands)
    assert all("danger-full-access" not in command for command in commands)
    with pytest.raises(ValueError, match="unsupported Windows sandbox"):
        runner.build_invocation("codex", TASKS[0], "baseline", tmp_path,
                                model="gpt-6-sol", effort="high", windows_sandbox="danger-full-access")
