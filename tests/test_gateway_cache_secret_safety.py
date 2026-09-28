from __future__ import annotations

import json
from pathlib import Path

from middle_man.gateway import GatewayConfig, RepositoryIndexer
from middle_man.gateway.models import INDEX_SCHEMA_VERSION


def test_decorator_arguments_never_persist_in_index_cache(tmp_path: Path) -> None:
    marker = "literal-secret-in-decorator-48291"
    (tmp_path / "module.py").write_text(
        f"def protect(value): return lambda function: function\n@protect('{marker}')\ndef handler(): pass\n",
        encoding="utf-8")
    index = RepositoryIndexer(GatewayConfig(tmp_path)).index()
    symbol = index.find_symbol("handler")[0]
    assert symbol.decorators == ("protect",)
    cache = (tmp_path / ".middle_man_cache" / "index.json").read_text(encoding="utf-8")
    assert marker not in cache
    assert json.loads(cache)["schema_version"] == INDEX_SCHEMA_VERSION == 2
