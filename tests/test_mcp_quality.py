from __future__ import annotations

from pathlib import Path

import pytest

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.quality import quality_cases
from middle_man.mcp.gateway import MCPGateway


@pytest.mark.parametrize("case", quality_cases(), ids=lambda case: case.name)
def test_existing_quality_fixture_recall_through_mcp(case, tmp_path: Path) -> None:
    for relative, source in case.files:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")

    config = GatewayConfig(tmp_path)
    pack = MCPGateway(config).context_pack(case.query, max_context_tokens=8000, top_k=10)
    selected = set(pack["selected_paths"])
    assert set(case.required_files) <= selected
    index = RepositoryIndexer(config).index()
    for name in case.required_symbols:
        assert any(
            excerpt["path"] == symbol.path
            and excerpt["start_line"] <= symbol.start_line
            and excerpt["end_line"] >= (symbol.end_line or symbol.start_line)
            for symbol in index.find_symbol(name)
            for excerpt in pack["excerpts"]
        ), name
    assert pack["metrics"]["estimated_selected_tokens"] < pack["metrics"]["estimated_raw_candidate_tokens"]
