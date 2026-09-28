"""Metadata-only local MCP invocation accounting."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.state_store import StateStoreError

MCP_USAGE_SCHEMA_VERSION = 1
_COUNTERS = ("raw_candidate_tokens", "selected_tokens", "tokens_avoided", "compaction_original_tokens",
             "compaction_result_tokens", "result_tokens", "index_cache_hits", "index_cache_misses")


class MCPUsageLog:
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.path = config.cache_dir / "mcp_usage.jsonl"

    def _check(self) -> None:
        for path in (self.config.cache_dir, self.path):
            if path.is_symlink() or not path.resolve().is_relative_to(self.config.repository_root):
                raise StateStoreError("unsafe MCP usage log path")

    def record(self, tool: str, inputs: object, metrics: dict[str, int], error: str | None = None,
               pack_fingerprint: str | None = None, generation: int | None = None) -> None:
        self._check()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check()
        query_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()
        entry: dict[str, Any] = {
            "schema_version": MCP_USAGE_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "query_fingerprint": query_hash,
            "pack_fingerprint": pack_fingerprint,
            "generation": generation,
            "success": error is None,
            "error_type": error,
            "metrics": {key: int(value) for key, value in metrics.items() if key in _COUNTERS},
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=False) as stream:
                stream.write((json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
                stream.flush()
        finally:
            os.close(descriptor)

    def summary(self) -> dict[str, Any]:
        self._check()
        calls: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        completed: Counter[str] = Counter()
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        entry = json.loads(line)
                        if entry["schema_version"] != MCP_USAGE_SCHEMA_VERSION:
                            raise ValueError("incompatible usage log schema")
                        calls[entry["tool"]] += 1
                        totals["errors"] += not entry["success"]
                        if entry["success"]:
                            completed[entry["tool"]] += 1
                        for key, value in entry["metrics"].items():
                            if key in _COUNTERS:
                                totals[key] += int(value)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise StateStoreError(f"invalid MCP usage log: {exc}") from exc
        return {"total_calls": sum(calls.values()), "calls_by_tool": dict(sorted(calls.items())),
                "context_packs_built": completed["middleman_context_pack"],
                "expansions": completed["middleman_expand_context"], "errors": totals["errors"],
                "estimated_context_tokens": {key: totals[key] for key in _COUNTERS},
                "basis": "Middle_Man heuristic estimates; not Codex or provider usage"}
