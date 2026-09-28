from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.project_memory import PROJECT_MEMORY_SCHEMA_VERSION, MemorySettings, ProjectMemoryService
from middle_man.gateway.state_store import StateStoreError


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("Git unavailable")
    _git(tmp_path, "init", "-q")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fixture"\ndependencies = ["pytest"]\n', encoding="utf-8")
    (tmp_path / "auth.py").write_text("class AuthService:\n    def login(self):\n        return True\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                    "commit", "-q", "-m", "initial"], check=True, capture_output=True)
    return tmp_path


def test_refresh_preserves_user_notes_and_replaces_derived(repo: Path) -> None:
    service = ProjectMemoryService(GatewayConfig(repo))
    initial = service.refresh()
    assert initial.schema_version == PROJECT_MEMORY_SCHEMA_VERSION
    assert initial.head
    assert any(f.value == "Python" and f.source_path for f in initial.facts)
    assert any(f.value == "pytest" and f.source_path == "pyproject.toml" for f in initial.facts)
    assert any(c.path == "auth.py" for c in initial.components)
    assert service.refresh().fingerprint == initial.fingerprint
    with_decision = service.add_decision("Keep auth stable", category="architecture")
    assert with_decision.fingerprint != initial.fingerprint
    with_issue = service.add_issue("Login fixture failing")
    issue_id = with_issue.issues[0].id
    service.resolve_issue(issue_id)
    service.add_issue("Other open issue")
    (repo / "auth.py").unlink()
    (repo / "engine.py").write_text("class Engine:\n    pass\n", encoding="utf-8")
    refreshed = service.refresh()
    assert all(c.path != "auth.py" for c in refreshed.components)
    assert any(c.path == "engine.py" for c in refreshed.components)
    assert refreshed.decisions[0].text == "Keep auth stable"
    assert refreshed.issues[0].resolved and not refreshed.issues[1].resolved
    assert refreshed.fingerprint != with_issue.fingerprint
    assert refreshed.metrics.serialized_bytes == len((repo / ".middle_man_cache/project_memory.json").read_bytes())


def test_memory_corruption_preserves_existing_file_and_source(repo: Path) -> None:
    service = ProjectMemoryService(GatewayConfig(repo))
    service.add_decision("Keep existing decision")
    path = repo / ".middle_man_cache/project_memory.json"
    path.write_text('{"schema_version":1,"repository_root":', encoding="utf-8")
    with pytest.raises(StateStoreError, match="preserved existing data"):
        service.refresh()
    assert path.read_text(encoding="utf-8").endswith(":")
    assert (repo / "auth.py").exists()


def test_memory_rejects_wrong_root_and_symlink(repo: Path, tmp_path: Path) -> None:
    service = ProjectMemoryService(GatewayConfig(repo))
    service.refresh()
    path = repo / ".middle_man_cache/project_memory.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["repository_root"] = str(tmp_path / "other")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StateStoreError, match="different repository"):
        service.refresh()
    path.unlink()
    target = tmp_path / "outside.json"
    target.write_text("outside", encoding="utf-8")
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises((StateStoreError, ValueError)):
        service.refresh()
    assert target.read_text(encoding="utf-8") == "outside"


def test_memory_redacts_before_persistence_and_contains_no_source(repo: Path) -> None:
    source_only = "source_only_marker_783105"
    (repo / "auth.py").write_text(f"class AuthService:\n    marker = '{source_only}'\n", encoding="utf-8")
    service = ProjectMemoryService(GatewayConfig(repo))
    service.add_decision('PASSWORD="fake-secret-8382"')
    service.add_issue("Authorization: Bearer fake-secret-token-123456789")
    raw = (repo / ".middle_man_cache/project_memory.json").read_text(encoding="utf-8")
    assert "fake-secret-8382" not in raw
    assert "fake-secret-token-123456789" not in raw
    assert source_only not in raw
    assert "assigned secret" in raw and "bearer token" in raw


def test_bounded_components_and_conservative_technology(repo: Path) -> None:
    (repo / "package.json").write_text('{"dependencies":{"react":"18","next":"14"},"devDependencies":{"typescript":"5"}}', encoding="utf-8")
    (repo / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")
    service = ProjectMemoryService(GatewayConfig(repo), settings=MemorySettings(max_components=1, max_symbols=1))
    memory = service.refresh()
    assert len(memory.components) <= 1
    assert sum(len(c.symbols) for c in memory.components) <= 1
    technologies = {fact.value: fact.source_path for fact in memory.facts if fact.category == "technology"}
    assert technologies["React"] == "package.json"
    assert technologies["Next.js"] == "package.json"
    assert technologies["TypeScript"] == "package.json"
    assert technologies["Docker"] == "Dockerfile"
    assert technologies["pytest"] == "pyproject.toml"
    assert "Flask" not in technologies and "FastAPI" not in technologies

def test_memory_cli_smoke(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(repo)
    main(["memory", "refresh", "--repo", root])
    assert "MIDDLE_MAN PROJECT MEMORY" in capsys.readouterr().out
    main(["memory", "show", "--repo", root])
    assert "Technologies:" in capsys.readouterr().out
    main(["memory", "status", "--repo", root])
    assert "Fingerprint:" in capsys.readouterr().out
    main(["memory", "decision", "add", "Keep Lab isolated", "--repo", root])
    assert "Keep Lab isolated" in capsys.readouterr().out
    main(["memory", "decision", "list", "--repo", root])
    assert "Keep Lab isolated" in capsys.readouterr().out
    main(["memory", "issue", "add", "Known fixture issue", "--repo", root])
    capsys.readouterr()
    main(["memory", "issue", "list", "--repo", root])
    assert "Known fixture issue" in capsys.readouterr().out
    memory = ProjectMemoryService(GatewayConfig(repo)).load()
    assert memory is not None
    main(["memory", "issue", "resolve", memory.issues[0].id, "--repo", root])
    assert "resolved" in capsys.readouterr().out
    main(["memory", "decision", "remove", memory.decisions[0].id, "--repo", root])
    assert "Keep Lab isolated" not in capsys.readouterr().out
