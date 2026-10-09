"""Research-only navigation hints selected independently of source allocation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import IndexedFile, RepositoryIndex, Symbol
from middle_man.gateway.relevance import ContextQuery, RelevanceCandidate, RelevanceEngine
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator


_SAFE_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_EMPTY_LOCATOR = "- No selected locations; use native repository search."


@dataclass(frozen=True, slots=True)
class ShadowLocator:
    text: str
    sha256: str
    estimated_tokens: int
    appendix_estimated_tokens: int
    candidate_paths: tuple[str, ...]
    selected_paths: tuple[str, ...]
    budget_prevented_paths: tuple[str, ...]
    symbol_hints: int
    file_fallback_hints: int


def _location(record: IndexedFile, candidate: RelevanceCandidate,
              redactor: SecretRedactor) -> tuple[int, int, str | None]:
    if record.line_count is None or record.line_count < 1:
        raise ValueError("indexed file lacks a positive line count")
    symbols: dict[str, Symbol] = {symbol.qualified_name: symbol for symbol in record.symbols}
    exact = [signal.key.removeprefix("symbol:") for signal in candidate.signals
             if signal.kind == "exact_symbol" and signal.key.startswith("symbol:")]
    for name in dict.fromkeys([*exact, *candidate.matched_symbols]):
        symbol = symbols.get(name)
        if symbol is None or _SAFE_SYMBOL.fullmatch(name) is None or redactor.redact(name).text != name:
            continue
        end = symbol.end_line or symbol.start_line
        if 1 <= symbol.start_line <= end <= record.line_count:
            return symbol.start_line, end, name
    return 1, record.line_count, None


def build_navigation_shadow(config: GatewayConfig, index: RepositoryIndex,
                            query: ContextQuery, *, max_appendix_tokens: int) -> ShadowLocator:
    """Walk unchanged top-50 relevance order; never consult source allocation."""
    if max_appendix_tokens < 1:
        raise ValueError("appendix budget must be positive")
    candidates = RelevanceEngine(index, config).find(query, top_k=50)
    redactor = SecretRedactor()
    estimator = HeuristicTokenEstimator()
    lines: list[str] = []
    selected: list[str] = []
    prevented: list[str] = []
    symbol_hints = fallback_hints = 0
    seen: set[str] = set()
    for candidate in candidates:
        path = candidate.path
        if path in seen:
            continue
        seen.add(path)
        if (config.relative_path(path) != path or any(ord(char) < 32 for char in path)
                or redactor.redact(path).text != path):
            raise ValueError("unsafe or sensitive navigation path")
        if not config.resolve_path(path).is_file():
            raise ValueError("indexed navigation path is missing or unsafe")
        record = index.get_file(path)
        if record is None or not record.is_text or not record.line_count or record.line_count < 1:
            continue
        start, end, symbol = _location(record, candidate, redactor)
        label = f"- {path}:{start}-{end}" + (f" ({symbol})" if symbol else "")
        proposed = "\n".join([*lines, label])
        if estimator.estimate(append_offline_locator("", proposed)) > max_appendix_tokens:
            prevented.append(path)
            continue
        lines.append(label)
        selected.append(path)
        symbol_hints += symbol is not None
        fallback_hints += symbol is None
    text = "\n".join(lines) if lines else _EMPTY_LOCATOR
    appendix_tokens = estimator.estimate(append_offline_locator("", text))
    if appendix_tokens > max_appendix_tokens:
        raise ValueError("no source-free locator fits the appendix budget")
    return ShadowLocator(text, hashlib.sha256(text.encode("utf-8")).hexdigest(),
                         estimator.estimate(text), appendix_tokens,
                         tuple(item.path for item in candidates), tuple(selected),
                         tuple(prevented), symbol_hints, fallback_hints)
