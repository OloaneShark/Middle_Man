from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from middle_man.gateway import GatewayConfig, RepositoryIndexer, RelevanceEngine
from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.context_output import context_pack_dict
from middle_man.gateway.git_diff import DiffHunk, DiffLine, FileDiff, GitDiff
from middle_man.gateway.quality import quality_cases


def test_misleading_filename_loses_to_exact_symbol(tmp_path: Path) -> None:
    case = quality_cases()[0]
    for relative, source in case.files:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    config = GatewayConfig(tmp_path)
    matches = RelevanceEngine(RepositoryIndexer(config).index(), config).find(case.query, top_k=10)
    paths = [item.path for item in matches]
    assert paths.index("app/session.py") < paths.index("app/auth_old.py")


def test_three_modes_and_query_redaction(tmp_path: Path) -> None:
    filler = "".join(f"def filler_{number}():\n    return {number}\n\n" for number in range(100))
    (tmp_path / "service.py").write_text(filler + "def critical():\n    return True\n", encoding="utf-8")
    builder = ContextBuilder(GatewayConfig(tmp_path))
    safe = builder.build("critical", mode="safe")
    balanced = builder.build("critical", mode="balanced")
    aggressive = builder.build("critical", mode="aggressive")
    assert safe.metrics.estimated_selected_tokens >= balanced.metrics.estimated_selected_tokens >= aggressive.metrics.estimated_selected_tokens
    assert all("return True" in next(item for item in pack.excerpts if item.path == "service.py").text
               for pack in (safe, balanced, aggressive))
    secret_query = builder.build("service.py PASSWORD='do-not-export-me'")
    assert "REDACTIONS_APPLIED" in secret_query.warnings
    assert "do-not-export-me" not in str(context_pack_dict(secret_query))


def test_diff_inside_large_function_keeps_complete_unit_not_file(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("Git unavailable")
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "tests").mkdir()
    filler = "".join(f"def filler_{number}(): return {number}\n" for number in range(200))
    function = "def process_state(value):\n" + "".join(f"    part_{number} = value + {number}\n" for number in range(30)) + "    return part_29\n"
    source = tmp_path / "session.py"
    source.write_text(filler + function, encoding="utf-8")
    (tmp_path / "tests" / "test_session.py").write_text("from session import process_state\ndef test_state(): assert process_state(1)\n", encoding="utf-8")
    git("add", ".")
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                    "commit", "-q", "-m", "initial"], check=True, capture_output=True)
    source.write_text(source.read_text(encoding="utf-8").replace("part_15 = value + 15", "part_15 = value + 16"), encoding="utf-8")
    pack = ContextBuilder(GatewayConfig(tmp_path)).build("process_state", top_k=8)
    excerpt = next(item for item in pack.excerpts if item.path == "session.py" and "def process_state" in item.text)
    assert "part_15 = value + 16" in excerpt.text
    assert "return part_29" in excerpt.text
    assert not excerpt.complete_file
    assert any(item.path == "tests/test_session.py" for item in pack.excerpts)
    assert next(item for item in pack.changed_files if item.path == "session.py").affected_symbols == ("process_state",)


def test_structured_diff_budget_never_hides_paths() -> None:
    diff = GitDiff(True, (FileDiff("auth.py", None, "modified", 1, 0,
                                (DiffHunk(1, 0, 1, 1, (DiffLine("+", "PASSWORD='secret-value'", None, 1),)),),
                                False, ("login",)),))
    result = OutputCompactor().compact_git_diff(diff, max_tokens=1)
    assert "auth.py" in result.compacted_text
    assert "secret-value" not in result.compacted_text
    assert "BUDGET_EXCEEDED_FOR_REQUIRED_OUTPUT" in result.warnings
