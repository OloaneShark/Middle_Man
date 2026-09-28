from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.handoff import HANDOFF_SCHEMA_VERSION, ContextReference, HandoffService
from middle_man.gateway.project_memory import ProjectMemoryService
from middle_man.gateway.state_store import StateStoreError


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("Git unavailable")
    _git(tmp_path, "init", "-q")
    (tmp_path / "auth.py").write_text("class AuthService:\n    def login(self):\n        return True\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                    "commit", "-q", "-m", "initial"], check=True, capture_output=True)
    return tmp_path


def _modify_auth(repo: Path) -> None:
    (repo / "auth.py").write_text("class AuthService:\n    def login(self):\n        return False\n", encoding="utf-8")


def test_session_continuation_and_quality(repo: Path) -> None:
    _modify_auth(repo)
    service = HandoffService(GatewayConfig(repo))
    ProjectMemoryService(GatewayConfig(repo)).add_issue("Login remains broken")
    result = OutputCompactor().compact("pytest", "FAILED tests/test_auth.py::test_login - AssertionError\n1 failed, 4 passed\n")
    reference = ContextReference("a" * 64, "safe", "fix login", ("auth.py",), 250, ())
    created = service.create("Fix login", context=reference, tool_results=(result,), next_steps=("Investigate login state",))
    latest = service.latest()
    view = service.view(latest)
    assert latest == created and not view.is_stale
    assert latest.schema_version == HANDOFF_SCHEMA_VERSION
    assert latest.task == "Fix login"
    assert latest.changes[0].path == "auth.py"
    assert latest.changes[0].affected_symbols == ("AuthService.login",)
    assert "test_login" in latest.tool_results[0].compacted_text
    assert latest.next_steps == ("Investigate login state",)
    assert any(i.text == "Login remains broken" for i in latest.unresolved_issues)
    assert latest.context and latest.context.fingerprint == "a" * 64
    assert latest.metrics.estimated_reconstruction_tokens > 0
    stored = repo / ".middle_man_cache" / "handoffs" / f"{latest.fingerprint}.json"
    assert latest.metrics.handoff_bytes == len(stored.read_bytes())
    assert service.create("Fix login", context=reference, tool_results=(result,), next_steps=("Investigate login state",)).fingerprint == latest.fingerprint
    assert len(service.list()) == 1


def test_stale_changes_head_branch_and_preserves_old_handoff(repo: Path) -> None:
    _modify_auth(repo)
    service = HandoffService(GatewayConfig(repo))
    handoff = service.create("Fix auth")
    (repo / "auth.py").write_text("class AuthService:\n    def login(self):\n        raise RuntimeError()\n", encoding="utf-8")
    assert {"FILE_CHANGED", "PROJECT_MEMORY_CHANGED"}.issubset(service.view(handoff).stale_reasons)
    _git(repo, "add", "auth.py")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                    "commit", "-q", "-m", "changed"], check=True, capture_output=True)
    _git(repo, "switch", "-q", "-c", "other-branch")
    reasons = service.view(handoff).stale_reasons
    assert "HEAD_CHANGED" in reasons and "BRANCH_CHANGED" in reasons
    (repo / "auth.py").unlink()
    assert "FILE_REMOVED" in service.view(handoff).stale_reasons
    assert service.load(handoff.fingerprint) == handoff


def test_secret_and_no_source_duplication(repo: Path) -> None:
    source_only = "source_marker_9f217"
    (repo / "auth.py").write_text(f"class AuthService:\n    marker = '{source_only}'\n", encoding="utf-8")
    service = HandoffService(GatewayConfig(repo))
    result = OutputCompactor().compact("pytest", "FAILED test_login Authorization: Bearer fake-secret-123456789\n")
    handoff = service.create('PASSWORD="fake-secret-8382"', tool_results=(result,),
                             issues=("Authorization: Bearer fake-secret-223456789",),
                             next_steps=('PASSWORD="fake-secret-9382"',))
    raw = (repo / ".middle_man_cache" / "handoffs" / f"{handoff.fingerprint}.json").read_text(encoding="utf-8")
    assert source_only not in raw
    for secret in ("fake-secret-8382", "fake-secret-123456789", "fake-secret-223456789", "fake-secret-9382"):
        assert secret not in raw
    assert "assigned secret" in raw and "bearer token" in raw
    assert "MIDDLE_MAN_REDACTED_SECRET" in raw


def test_context_metadata_only_and_pointer_traversal_rejected(repo: Path) -> None:
    service = HandoffService(GatewayConfig(repo))
    reference = ContextReference("a" * 64, "safe", "auth", ("auth.py",), 50, ())
    handoff = service.create("Fix auth", context=reference)
    path = repo / ".middle_man_cache" / "handoffs" / f"{handoff.fingerprint}.json"
    raw = path.read_text(encoding="utf-8")
    assert "excerpts" not in raw and "return True" not in raw
    _modify_auth(repo)
    assert "FILE_CHANGED" in service.view(handoff).stale_reasons
    pointer = repo / ".middle_man_cache/latest_handoff.json"
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["handoff_id"] = "../auth.py"
    pointer.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StateStoreError, match="invalid latest handoff pointer"):
        service.latest()


def test_handoff_soft_limit_warns_without_truncation(repo: Path) -> None:
    service = HandoffService(GatewayConfig(repo), soft_limit_tokens=5)
    handoff = service.create("Long explicit task about auth", next_steps=("Keep every step",))
    assert "HANDOFF_SOFT_LIMIT_EXCEEDED" in handoff.warnings
    assert handoff.next_steps == ("Keep every step",)
    assert service.load(handoff.fingerprint).next_steps == handoff.next_steps

def test_cli_compacts_large_supplied_log_before_persistence(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = repo / "build-output.txt"
    output.write_text("".join(f"noise line {n} unique payload\n" for n in range(2000)) + "ERROR build failed\n", encoding="utf-8")
    main(["handoff", "create", "--task", "Inspect build", "--tool-output", str(output), "--repo", str(repo)])
    capsys.readouterr()
    handoff = HandoffService(GatewayConfig(repo)).latest()
    stored = (repo / ".middle_man_cache" / "handoffs" / f"{handoff.fingerprint}.json").read_text(encoding="utf-8")
    assert "ERROR build failed" in stored
    assert "LOW_PRIORITY_LINES_OMITTED" in stored
    assert "noise line 1000 unique payload" not in stored
    assert len(stored.encode("utf-8")) < len(output.read_bytes())

def test_handoff_corruption_and_cli_smoke(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _modify_auth(repo)
    root = str(repo)
    pytest_output = repo / "pytest-output.txt"
    pytest_output.write_text("FAILED tests/test_auth.py::test_login\n1 failed\n", encoding="utf-8")
    main(["handoff", "create", "--task", "Fix login", "--pytest-output", str(pytest_output),
          "--next-step", "Check state", "--repo", root])
    assert "Fix login" in capsys.readouterr().out
    main(["handoff", "latest", "--repo", root])
    assert "test_login" in capsys.readouterr().out
    main(["handoff", "list", "--repo", root])
    assert "Fix login" in capsys.readouterr().out
    service = HandoffService(GatewayConfig(repo))
    handoff = service.latest()
    main(["handoff", "show", handoff.fingerprint[:12], "--repo", root])
    assert "Fix login" in capsys.readouterr().out
    main(["handoff", "show", handoff.fingerprint, "--json", "--repo", root])
    assert json.loads(capsys.readouterr().out)["task"] == "Fix login"
    path = repo / ".middle_man_cache" / "handoffs" / f"{handoff.fingerprint}.json"
    path.write_text("not JSON", encoding="utf-8")
    with pytest.raises(StateStoreError, match="preserved existing data"):
        service.load(handoff.fingerprint)
    assert path.read_text(encoding="utf-8") == "not JSON"
