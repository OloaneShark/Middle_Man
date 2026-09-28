from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from middle_man.gateway import GatewayConfig, RepositoryIndexer


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    root = tmp_path / "sample_repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "auth.py").write_text(
        "from .database import connect\n"
        "TOKEN_LIMIT = 3\n"
        "class AuthService:\n"
        "    @staticmethod\n"
        "    async def login():\n"
        "        return connect()\n", encoding="utf-8")
    (root / "app" / "database.py").write_text("def connect():\n    return True\n", encoding="utf-8")
    (root / "tests" / "test_auth.py").write_text("from app.auth import AuthService\n\ndef test_login():\n    pass\n", encoding="utf-8")
    (root / "README.md").write_text("Sample\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    return root


def test_config_paths_and_safety(sample_repo: Path, tmp_path: Path) -> None:
    config = GatewayConfig(sample_repo)
    assert config.relative_path("app/auth.py") == "app/auth.py"
    with pytest.raises(ValueError):
        config.resolve_path("../../secret.txt")
    with pytest.raises(ValueError):
        GatewayConfig(sample_repo, cache_dir=tmp_path / "outside")
    assert GatewayConfig(sample_repo, cache_dir=Path("custom_cache")).cache_dir == sample_repo / "custom_cache"


def test_index_structure_imports_and_ast(sample_repo: Path) -> None:
    index = RepositoryIndexer(GatewayConfig(sample_repo)).index()
    assert tuple(file.path for file in index.files) == tuple(sorted(file.path for file in index.files))
    auth = index.get_file("app/auth.py")
    assert auth.sha256 == hashlib.sha256((sample_repo / "app/auth.py").read_bytes()).hexdigest()
    assert auth.language == "Python" and auth.parse_status == "parsed"
    assert {symbol.qualified_name for symbol in auth.symbols} == {"TOKEN_LIMIT", "AuthService", "AuthService.login"}
    assert next(symbol for symbol in auth.symbols if symbol.name == "login").is_async
    assert index.find_symbol("AuthService.login")
    assert index.imports_for("app/auth.py") == ("app/database.py",)
    assert index.importers_of("app/auth.py") == ("tests/test_auth.py",)
    assert index.tests_for("app/auth.py") == ("tests/test_auth.py",)
    assert index.get_file("tests/test_auth.py").is_test
    assert any(edge.kind == "CONTAINS_SYMBOL" for edge in index.relationships)
    assert index.identity.has_git is False


def test_ignore_binary_oversized_errors_and_languages(sample_repo: Path) -> None:
    (sample_repo / ".middlemanignore").write_text("local.py\n", encoding="utf-8")
    for name in ("ignored.py", "local.py", ".env", "id_rsa", "private.pem"):
        (sample_repo / name).write_text("SECRET=real-secret\n", encoding="utf-8")
    (sample_repo / "node_modules").mkdir()
    (sample_repo / "node_modules" / "bad.py").write_text("SECRET\n", encoding="utf-8")
    (sample_repo / "image.png").write_bytes(b"\x89PNG\0somebytes")
    (sample_repo / "large.ts").write_text("A" * 100, encoding="utf-8")
    (sample_repo / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (sample_repo / "view.tsx").write_text("export const View = 1;\n", encoding="utf-8")
    index = RepositoryIndexer(GatewayConfig(sample_repo, max_file_size_bytes=50)).index()
    for name in ("ignored.py", "local.py", ".env", "id_rsa", "private.pem", "node_modules/bad.py"):
        assert index.get_file(name) is None
    assert index.get_file("image.png").parse_status == "binary"
    assert index.get_file("large.ts").parse_status == "oversized"
    assert index.get_file("large.ts").sha256
    assert index.get_file("broken.py").parse_status == "error"
    assert "line 1" in index.get_file("broken.py").parse_error
    assert index.get_file("view.tsx").language == "TSX"
    assert index.stats.parse_errors == 1
    assert index.stats.ignored >= 6


@pytest.mark.parametrize("suffix,language", [
    (".js", "JavaScript"), (".ts", "TypeScript"), (".jsx", "JSX"), (".html", "HTML"),
    (".css", "CSS"), (".json", "JSON"), (".toml", "TOML"), (".yaml", "YAML"),
    (".md", "Markdown"), (".sh", "Shell"), (".ps1", "PowerShell"),
])
def test_language_detection(sample_repo: Path, suffix: str, language: str) -> None:
    (sample_repo / f"example{suffix}").write_text("text\n", encoding="utf-8")
    item = RepositoryIndexer(GatewayConfig(sample_repo)).index().get_file(f"example{suffix}")
    assert item.language == language


def test_symlink_escape_is_not_indexed(sample_repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "secret.py"
    outside.write_text("SECRET = 'outside'\n", encoding="utf-8")
    try:
        (sample_repo / "link.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert RepositoryIndexer(GatewayConfig(sample_repo, follow_symlinks=True)).index().get_file("link.py") is None
