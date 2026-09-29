from __future__ import annotations

import json
from pathlib import Path

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.codex_benchmark.overlap import measure_delivery
from middle_man.mcp.gateway import MCPGateway


def test_pack_delivery_log_has_range_identity_and_sizes_but_no_source(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def target():\n    PASSWORD='fixture-secret-987654'\n    return 1\n", encoding="utf-8",
    )
    gateway = MCPGateway(GatewayConfig(tmp_path))
    pack = gateway.context_pack("target", max_context_tokens=500)
    raw_log = (gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8")
    assert "fixture-secret-987654" not in raw_log
    assert "return 1" not in raw_log
    entry = json.loads(raw_log)
    assert entry["delivery"]
    excerpt = pack["excerpts"][0]
    delivery = entry["delivery"][0]
    assert delivery["path"] == excerpt["path"]
    assert delivery["content_hash"] == excerpt["content_hash"]
    assert sum(delivery["line_bytes"]) == len(excerpt["text"].encode("utf-8"))
    result = measure_delivery([entry])
    assert result.overlap_available and result.repeated_source_bytes == 0
