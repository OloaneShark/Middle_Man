from __future__ import annotations

import json
from pathlib import Path

from middle_man.gateway import GatewayConfig, RepositoryIndexer
from middle_man.gateway.parsers import ParserRegistry, PythonParser


class SpyParser(PythonParser):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def parse(self, path: str, source: str):
        self.calls.append(path)
        return super().parse(path, source)


def test_incremental_reparse_and_relationship_refresh(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    source = root / "app" / "auth.py"
    source.write_text("from .helper import use\ndef login(): pass\n", encoding="utf-8")
    helper = root / "app" / "helper.py"
    helper.write_text("def use(): pass\n", encoding="utf-8")
    spy = SpyParser()
    indexer = RepositoryIndexer(GatewayConfig(root), ParserRegistry(spy))
    first = indexer.index()
    assert first.stats.cache_misses == 3 and first.stats.cache_hits == 0
    assert set(spy.calls) == {"app/__init__.py", "app/auth.py", "app/helper.py"}
    spy.calls.clear()
    second = indexer.index()
    assert second.stats.cache_hits == 3 and second.stats.files_reparsed == 0 and not spy.calls
    source.write_text("def authenticate(): pass\n", encoding="utf-8")
    third = indexer.index()
    assert spy.calls == ["app/auth.py"]
    assert third.stats.files_modified == 1 and third.stats.cache_hits == 2
    assert not third.find_symbol("login") and third.find_symbol("authenticate")
    assert not third.imports_for("app/auth.py")
    spy.calls.clear()
    helper.unlink()
    (root / "app" / "new.py").write_text("def created(): pass\n", encoding="utf-8")
    fourth = indexer.index()
    assert fourth.stats.files_created == 1 and fourth.stats.files_deleted == 1
    assert spy.calls == ["app/new.py"]
    assert fourth.get_file("app/helper.py") is None and fourth.find_symbol("created")


def test_corruption_schema_mismatch_and_cache_clear(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def active(): pass\n", encoding="utf-8")
    indexer = RepositoryIndexer(GatewayConfig(root))
    indexer.index()
    cache_file = root / ".middle_man_cache" / "index.json"
    cache_file.write_text("{oops", encoding="utf-8")
    assert indexer.index().stats.files_reparsed == 1
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    assert indexer.index().stats.files_reparsed == 1
    (root / ".middle_man_cache" / "notes.txt").write_text("keep", encoding="utf-8")
    assert indexer.cache.clear()
    assert source.exists() and (root / ".middle_man_cache" / "notes.txt").exists()
    assert not cache_file.exists()
