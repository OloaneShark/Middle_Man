"""Source-free navigation hints prepared before a benchmark Codex run."""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
LOCATOR_HEADING = "MIDDLE_MAN LOCAL LOCATOR"


@dataclass(frozen=True, slots=True)
class OfflineLocator:
    text: str
    sha256: str
    estimated_tokens: int
    pack_fingerprint: str
    selector_fingerprint: str
    selected_source_tokens: int
    selected_paths: tuple[str, ...]
    selected_ranges: tuple[tuple[str, int, int], ...]


def build_offline_locator(config: GatewayConfig, query: ContextQuery) -> OfflineLocator:
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    redactor = SecretRedactor()
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    seen_symbols: dict[str, set[str]] = {}
    for excerpt in pack.excerpts:
        path = excerpt.path
        if config.relative_path(path) != path or any(ord(char) < 32 for char in path):
            raise ValueError("unsafe locator path")
        if redactor.redact(path).text != path:
            raise ValueError("sensitive locator path")
        if excerpt.start_line < 1 or excerpt.end_line < excerpt.start_line:
            raise ValueError("invalid locator range")
        label = f"{excerpt.start_line}-{excerpt.end_line}"
        if excerpt.symbols:
            symbol = excerpt.symbols[0]
            if _SYMBOL.fullmatch(symbol) and redactor.redact(symbol).text == symbol:
                seen = seen_symbols.setdefault(path, set())
                if symbol not in seen:
                    label += f" ({symbol})"
                    seen.add(symbol)
        grouped.setdefault(path, []).append(label)
    text = "\n".join(f"- {path}:{'; '.join(ranges)}" for path, ranges in grouped.items())
    if not text:
        text = "- No selected locations; use native repository search."
    return OfflineLocator(
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        estimated_tokens=HeuristicTokenEstimator().estimate(text),
        pack_fingerprint=pack.fingerprint,
        selector_fingerprint=selector_implementation_fingerprint(),
        selected_source_tokens=pack.metrics.estimated_selected_tokens,
        selected_paths=pack.selected_files,
        selected_ranges=tuple((item.path, item.start_line, item.end_line) for item in pack.excerpts),
    )


def append_offline_locator(prompt: str, locator: str) -> str:
    if not locator.strip():
        raise ValueError("offline locator must be nonempty")
    return (prompt + "\n\n" + LOCATOR_HEADING + "\n"
            "Relevant repository locations identified locally before execution:\n"
            + locator + "\n\n"
            "Use these only as navigation hints. Verify exact behavior from repository source using native tools.")
