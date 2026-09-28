from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.handoff import HandoffService
from middle_man.gateway.project_memory import ProjectMemoryService
from middle_man.mcp.gateway import MCPGateway


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("Git unavailable")
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".middle_man_cache/\n", encoding="utf-8")
    (tmp_path / "auth.py").write_text("class AuthService:\n    def login(self):\n        return True\n", encoding="utf-8")
    (tmp_path / "test_auth.py").write_text("from auth import AuthService\ndef test_login():\n    assert AuthService().login()\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                    "commit", "-q", "-m", "initial"], check=True, capture_output=True)
    (tmp_path / "auth.py").write_text(
        'class AuthService:\n    def login(self):\n        PASSWORD="fixture-secret-895731"\n        return False\n',
        encoding="utf-8",
    )
    return tmp_path


def test_all_direct_tools_quality_safety_and_usage(repo: Path) -> None:
    config = GatewayConfig(repo)
    memory = ProjectMemoryService(config)
    memory.add_decision("Keep auth API stable")
    memory.add_issue("Login fixture fails")
    result = OutputCompactor().compact("pytest", "FAILED test_auth.py::test_login\n1 failed\n")
    HandoffService(config).create("Fix login", tool_results=(result,), next_steps=("Check auth state",))
    before = _git(repo, "status", "--porcelain")
    gateway = MCPGateway(config)

    state = gateway.project_state()
    assert state["decisions"][0]["text"] == "Keep auth API stable"
    assert state["open_issues"][0]["text"] == "Login fixture fails"
    assert "return False" not in json.dumps(state)
    handoff = gateway.session_handoff()
    assert handoff["task"] == "Fix login"
    assert handoff["status"] == "current"
    assert handoff["next_steps"] == ["Check auth state"]
    assert "test_login" in handoff["tool_results"][0]["compacted_text"]

    found = gateway.find_context("AuthService.login", top_k=5)
    assert found["ranked_files"][0]["path"] == "auth.py"
    assert found["ranked_files"][0]["role"] == "PRIMARY"
    assert found["source_included"] is False
    pack = gateway.context_pack("AuthService.login", max_context_tokens=600)
    assert "auth.py" in pack["selected_paths"]
    assert "AuthService.login" in pack["selected_symbols"]
    assert "fixture-secret-895731" not in json.dumps(pack)
    assert "MIDDLE_MAN_REDACTED_SECRET" in json.dumps(pack)
    assert pack["metrics"]["estimated_selected_tokens"] <= 600
    expanded = gateway.expand_context(pack["fingerprint"], "full_file", target="auth.py")
    assert expanded["generation"] == 1
    assert "fixture-secret-895731" not in json.dumps(expanded)
    stats = gateway.context_stats(fingerprint=pack["fingerprint"])
    assert stats["estimated_selected_tokens"] == pack["metrics"]["estimated_selected_tokens"]

    changes = gateway.changed_context()
    changed = next(item for item in changes["changed_files"] if item["path"] == "auth.py")
    assert changed["status"] == "modified"
    assert "AuthService.login" in changed["affected_symbols"]
    assert changes["raw_diff_included"] is False
    assert not any(item["path"].startswith(".middle_man_cache/") for item in changes["changed_files"])
    compacted = gateway.compact_output("pytest", "Authorization: Bearer fake-token-123456789012\nFAILED test_login\n")
    assert "fake-token-123456789012" not in json.dumps(compacted)
    assert "bearer token" in compacted["redaction_categories"]
    explained = gateway.explain_selection("AuthService.login", path="auth.py")
    assert any("exact symbol" in reason for reason in explained["selections"][0]["reasons"])
    mapped = gateway.repo_map()
    assert mapped["indexed_files"] >= 2 and mapped["source_included"] is False

    assert gateway.find_context("AuthService.login", top_k=5) == found
    usage = gateway.usage.summary()
    assert usage["total_calls"] == 11
    assert usage["context_packs_built"] == 1 and usage["expansions"] == 1
    assert usage["estimated_context_tokens"]["index_cache_hits"] > 0
    log = (config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8")
    for secret in ("fixture-secret-895731", "fake-token-123456789012", "Keep auth API stable", "AuthService.login"):
        assert secret not in log
    assert "return False" not in log and '"query_fingerprint"' in log
    assert _git(repo, "status", "--porcelain") == before


def test_invalid_paths_and_missing_pack_do_not_escape_root(repo: Path) -> None:
    gateway = MCPGateway(GatewayConfig(repo))
    with pytest.raises(ValueError, match="escapes repository root"):
        gateway.find_context("auth", paths=["../outside.py"])
    with pytest.raises(ValueError, match="unknown Context Pack"):
        gateway.expand_context("a" * 64, "full_file", target="auth.py")
    with pytest.raises(ValueError, match="escapes repository root"):
        gateway.changed_context("../outside.py")
    usage = gateway.usage.summary()
    assert usage["errors"] == 3
    assert usage["expansions"] == 0
    assert "../outside.py" not in (gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8")


def test_context_pack_matches_direct_gateway(repo: Path) -> None:
    from middle_man.gateway.context_builder import ContextBuilder

    config = GatewayConfig(repo)
    expected = ContextBuilder(config).build("AuthService.login", max_context_tokens=600)
    actual = MCPGateway(config).context_pack("AuthService.login", max_context_tokens=600)
    assert actual["fingerprint"] == expected.fingerprint
    assert actual["metrics"]["estimated_selected_tokens"] == expected.metrics.estimated_selected_tokens
    assert actual["metrics"]["estimated_raw_candidate_tokens"] == expected.metrics.estimated_raw_candidate_tokens
    assert "AuthService.login" in actual["selected_symbols"]
