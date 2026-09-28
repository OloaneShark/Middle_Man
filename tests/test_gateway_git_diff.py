from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.git_diff import GitDiffReader
from middle_man.gateway.indexer import RepositoryIndexer


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("Git unavailable")
    git(tmp_path, "init", "-q")
    source = ("def first():\n    value = 1\n    return value\n\n" + "\n" * 8 +
              "def second():\n    value = 2\n    return value\n")
    (tmp_path / "module.py").write_text(source, encoding="utf-8")
    (tmp_path / "old.py").write_text("def old(): pass\n", encoding="utf-8")
    (tmp_path / "deleted.py").write_text("def removed(): pass\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\0OLD")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_module.py").write_text("from module import first\ndef test_first(): assert first()\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                    "commit", "-q", "-m", "initial"], check=True, capture_output=True)
    return tmp_path


def test_staged_unstaged_hunks_symbols_and_determinism(repo: Path) -> None:
    source = repo / "module.py"
    source.write_text(source.read_text(encoding="utf-8").replace("value = 1", "value = 11"), encoding="utf-8")
    git(repo, "add", "module.py")
    source.write_text(source.read_text(encoding="utf-8").replace("value = 2", "value = 22"), encoding="utf-8")
    config = GatewayConfig(repo)
    index = RepositoryIndexer(config).index()
    diff = GitDiffReader(config).read(index)
    module = diff.get_file("module.py")
    assert module.status == "modified"
    assert len(module.hunks) == 2
    assert module.additions == 2 and module.deletions == 2
    assert module.affected_symbols == ("first", "second")
    assert module.hunks[0].new_start == 2
    assert any(line.text == "    value = 11" and line.new_line == 2 for line in module.hunks[0].lines)
    assert diff == GitDiffReader(config).read(index)


def test_rename_delete_untracked_binary_and_no_git(repo: Path, tmp_path: Path) -> None:
    git(repo, "mv", "old.py", "new.py")
    (repo / "deleted.py").unlink()
    (repo / "new_untracked.py").write_text("def new(): pass\n", encoding="utf-8")
    (repo / "image.png").write_bytes(b"\x89PNG\0NEW")
    config = GatewayConfig(repo)
    diff = GitDiffReader(config).read(RepositoryIndexer(config).index())
    assert diff.get_file("new.py").status == "renamed"
    assert diff.get_file("new.py").old_path == "old.py"
    assert diff.get_file("deleted.py").status == "deleted"
    assert diff.get_file("new_untracked.py").status == "untracked"
    assert diff.get_file("image.png").binary_changed
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not GitDiffReader(GatewayConfig(plain)).read().has_git


def test_diff_aware_pack_keeps_enclosing_function_and_test(repo: Path) -> None:
    source = repo / "module.py"
    source.write_text(source.read_text(encoding="utf-8").replace("value = 1", "value = 100"), encoding="utf-8")
    pack = ContextBuilder(GatewayConfig(repo)).build("first", top_k=8)
    module = next(item for item in pack.excerpts if item.path == "module.py" and "def first" in item.text)
    assert "return value" in module.text
    assert any(item.path == "tests/test_module.py" for item in pack.excerpts)
    changed = next(item for item in pack.changed_files if item.path == "module.py")
    assert "first" in changed.affected_symbols
    assert changed.hunk_ranges
