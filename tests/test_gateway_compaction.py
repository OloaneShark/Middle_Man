from __future__ import annotations

import io
import json
from pathlib import Path

from middle_man.cli.main import main
from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.git_diff import DiffHunk, DiffLine, FileDiff, GitDiff
from middle_man.gateway.secrets import MARKER, SecretRedactor


def pytest_failure_output() -> str:
    passes = "\n".join(f"tests/test_bulk.py::test_{number} PASSED" for number in range(250))
    return (passes + "\n" +
            "tests/test_auth.py::test_oauth_state FAILED\n"
            "Traceback (most recent call last):\n"
            "  File \"tests/test_auth.py\", line 42, in test_oauth_state\n"
            "    assert callback_state == expected_state\n"
            "AssertionError: OAuth state mismatch\n" +
            "DeprecationWarning: auth setting\n" * 5 +
            "================ 1 failed, 250 passed in 0.7s ================\n")


def test_pytest_failure_traceback_and_summary_survive() -> None:
    original = pytest_failure_output()
    result = OutputCompactor().compact("pytest", original, max_tokens=150)
    assert "test_oauth_state FAILED" in result.compacted_text
    assert 'File "tests/test_auth.py", line 42' in result.compacted_text
    assert "AssertionError: OAuth state mismatch" in result.compacted_text
    assert "1 failed, 250 passed" in result.compacted_text
    assert "250 passing test lines" in result.compacted_text
    assert result.estimated_compacted_tokens < result.estimated_original_tokens
    assert result.repeated_lines_removed >= 250


def test_exact_duplicate_logs_and_budget_omissions() -> None:
    text = "\n".join(["starting"] * 20 + ["ERROR database unavailable"] + [f"detail {number}" for number in range(200)] +
                     ["Traceback (most recent call last):", '  File "app.py", line 9', "RuntimeError: connection failed"])
    result = OutputCompactor().compact("docker", text, max_tokens=80)
    assert "starting [repeated 20x]" in result.compacted_text
    assert "ERROR database unavailable" in result.compacted_text
    assert "Traceback (most recent call last):" in result.compacted_text
    assert 'File "app.py", line 9' in result.compacted_text
    assert "RuntimeError: connection failed" in result.compacted_text
    assert result.truncated and result.omitted_lines > 0
    assert "Middle_Man omitted" in result.compacted_text
    distinct = OutputCompactor().compact("log", "2025-01-01 ERROR x\n2025-01-02 ERROR x\n")
    assert distinct.repeated_lines_removed == 0


def test_git_status_keeps_every_path() -> None:
    raw = " M app/auth.py\nA  app/new.py\n D app/old.py\nR  app/legacy.py -> app/current.py\n?? tests/test_auth.py\n"
    result = OutputCompactor().compact("git-status", raw, max_tokens=1)
    for path in ("app/auth.py", "app/new.py", "app/old.py", "app/legacy.py", "tests/test_auth.py"):
        assert path in result.compacted_text
    assert "Modified (1)" in result.compacted_text
    assert "BUDGET_EXCEEDED_FOR_REQUIRED_OUTPUT" in result.warnings


def test_structured_git_diff_compaction() -> None:
    diff = GitDiff(True, (FileDiff("app/auth.py", None, "modified", 1, 1,
                                (DiffHunk(10, 1, 10, 1, (DiffLine("-", "return old", 10, None),
                                                             DiffLine("+", "return new", None, 10))),),
                                False, ("AuthService.login",)),))
    result = OutputCompactor().compact_git_diff(diff)
    assert result.output_type == "git-diff"
    assert "app/auth.py" in result.compacted_text
    assert "AuthService.login" in result.compacted_text
    assert "@@ -10,1 +10,1 @@" in result.compacted_text
    assert "+return new" in result.compacted_text


def test_secret_redaction_categories_and_benign_code() -> None:
    raw = ("PASSWORD=\"actual-secret-value\"\n"
           "Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n"
           "postgres://user:password@localhost/db\n"
           "-----BEGIN PRIVATE KEY-----\nabc123\ndef456\n-----END PRIVATE KEY-----\n"
           "token_count = 3\npassword_hash = hash_password(value)\n")
    result = SecretRedactor().redact(raw)
    for secret in ("actual-secret-value", "abcdefghijklmnopqrstuvwxyz", "abc123", "def456", "user:password"):
        assert secret not in result.text
    assert MARKER in result.text
    assert result.text.count("\n") == raw.count("\n")
    assert "token_count = 3" in result.text
    assert "password_hash = hash_password(value)" in result.text
    assert set(result.categories) == {"assigned secret", "bearer token", "credential URL", "private key"}
    compacted = OutputCompactor().compact("log", raw)
    assert "actual-secret-value" not in compacted.compacted_text
    assert "REDACTIONS_APPLIED" in compacted.warnings


def test_compact_cli_file_stdin_and_json(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "pytest.txt"
    source.write_text(pytest_failure_output(), encoding="utf-8")
    export = tmp_path / "compact.json"
    main(["compact", "pytest", str(source), "--json", str(export)])
    assert "test_oauth_state FAILED" in capsys.readouterr().out
    assert json.loads(export.read_text(encoding="utf-8"))["output_type"] == "pytest"
    monkeypatch.setattr("sys.stdin", io.StringIO("hello\nhello\n"))
    main(["compact", "log"])
    assert "hello [repeated 2x]" in capsys.readouterr().out
