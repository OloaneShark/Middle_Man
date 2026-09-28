from __future__ import annotations

import os
from pathlib import Path

from middle_man.gateway import GatewayConfig, RepositoryIndexer
from middle_man.gateway.parsers import ParserRegistry, PythonParser


class CountingParser(PythonParser):
    def __init__(self) -> None:
        self.count = 0

    def parse(self, path: str, source: str):
        self.count += 1
        return super().parse(path, source)


def test_timestamp_only_change_keeps_parsed_record(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def useful(): pass\n", encoding="utf-8")
    parser = CountingParser()
    indexer = RepositoryIndexer(GatewayConfig(tmp_path), ParserRegistry(parser))
    first = indexer.index()
    original = source.stat().st_mtime_ns
    os.utime(source, ns=(original + 1_000_000_000, original + 1_000_000_000))
    second = indexer.index()
    assert parser.count == 1
    assert second.stats.files_unchanged == 1
    assert second.stats.files_reparsed == 0
    assert second.get_file("module.py").sha256 == first.get_file("module.py").sha256
