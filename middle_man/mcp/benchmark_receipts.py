"""Source-free, explicitly enabled benchmark diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_models import ContextPack
from middle_man.gateway.relevance import terms
from middle_man.gateway.secrets import MARKER, SecretRedactor
from middle_man.gateway.state_store import StateStoreError


@dataclass(frozen=True, slots=True)
class BenchmarkIdentity:
    run_id: str
    task_id: str
    mode: str
    source_commit: str

    def __post_init__(self) -> None:
        for value in (self.run_id, self.task_id, self.mode, self.source_commit):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
                raise ValueError("invalid benchmark identity")


@lru_cache(maxsize=1)
def selector_implementation_fingerprint() -> str:
    package = Path(__file__).resolve().parents[1] / "gateway"
    digest = hashlib.sha256()
    for name in ("context_builder.py", "relevance.py", "selection.py", "indexer.py"):
        digest.update(name.encode("ascii") + b"\0" + (package / name).read_bytes() + b"\0")
    return digest.hexdigest()


class BenchmarkReceipts:
    def __init__(self, config: GatewayConfig, identity: BenchmarkIdentity) -> None:
        self.config = config
        self.identity = identity
        self.redactor = SecretRedactor()
        self.path = config.cache_dir / "benchmark_receipts.jsonl"

    def _safe(self, value: str) -> str:
        return self.redactor.redact(value).text

    def _write(self, record: dict[str, Any]) -> None:
        for target in (self.config.cache_dir, self.path):
            if target.is_symlink() or not target.resolve().is_relative_to(self.config.repository_root):
                raise StateStoreError("unsafe benchmark receipt path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=False) as stream:
                stream.write((json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
                stream.flush()
        finally:
            os.close(descriptor)

    def record(self, inputs: dict[str, Any], pack: ContextPack) -> None:
        from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
        from middle_man.mcp.usage import server_implementation_identity

        query_signature = hashlib.sha256(json.dumps(
            inputs, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()
        task = self._safe(str(inputs["task"])).replace(MARKER, " ")
        error = self._safe(str(inputs.get("error_text") or "")).replace(MARKER, " ")
        identifiers = re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", task)
        safe = lambda values: [self._safe(str(value)) for value in values]
        self._write({
            "schema_version": 1,
            "run_id": self.identity.run_id,
            "task_id": self.identity.task_id,
            "benchmark_mode": self.identity.mode,
            "source_commit": self.identity.source_commit,
            "source_tree_fingerprint": source_fingerprint(self.config.repository_root),
            "repository": {"name": self._safe(pack.repository.name), "head": pack.repository.head},
            "server_implementation": server_implementation_identity(),
            "selector_implementation_fingerprint": selector_implementation_fingerprint(),
            "query": {
                "signature": query_signature,
                "mode": pack.mode.value,
                "budget": pack.max_context_tokens,
                "top_k": inputs.get("top_k"),
                "terms": sorted(terms(task))[:80],
                "identifiers": sorted(set(identifiers))[:80],
                "paths": safe(inputs.get("paths") or ()),
                "symbols": safe(inputs.get("symbols") or ()),
                "error_terms": sorted(terms(error))[:80],
            },
            "selection": {
                "candidates": [{"path": self._safe(item.path), "score": item.score}
                               for item in pack.candidates],
                "selected_paths": safe(pack.selected_files),
                "omitted": [{"path": self._safe(item.candidate_path), "reason": item.omission_reason,
                             "estimated_cost": item.estimated_source_cost}
                            for item in pack.selection_diagnostics if item.omission_reason],
                "ranges": [{"path": self._safe(item.path), "start": item.start_line,
                            "end": item.end_line} for item in pack.excerpts],
                "candidate_tokens": pack.metrics.estimated_raw_candidate_tokens,
                "selected_tokens": pack.metrics.estimated_selected_tokens,
                "pack_fingerprint": pack.fingerprint,
            },
        })
