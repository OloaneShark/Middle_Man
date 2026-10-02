"""Local-only edit-navigation prototype; never used by AUTO or the runner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from middle_man.gateway.codex_benchmark.offline_locator import _SYMBOL
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_models import ContextPack
from middle_man.gateway.relevance import terms
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator


@dataclass(frozen=True, slots=True)
class NavigationAnchor:
    path: str
    symbol: str
    phase: str
    relevance_score: float
    matched_query_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfflineAnchors:
    text: str
    estimated_tokens: int
    anchors: tuple[NavigationAnchor, ...]


def render_offline_anchors(pack: ContextPack, config: GatewayConfig, *,
                           max_paths: int = 4) -> OfflineAnchors:
    """Rank selected symbol locations by direct filename and query affinity."""
    if not 1 <= max_paths <= 4:
        raise ValueError("max_paths must be between 1 and 4")
    query_terms = terms(pack.query.task) | terms(pack.query.error_text)
    redactor = SecretRedactor()
    selected: dict[str, set[str]] = {}
    for excerpt in pack.excerpts:
        selected.setdefault(excerpt.path, set()).update(excerpt.symbols)

    ranked: list[tuple[tuple[int, int, float, str], NavigationAnchor]] = []
    for diagnostic in pack.selection_diagnostics:
        path = diagnostic.candidate_path
        if not diagnostic.selected or path not in selected:
            continue
        phases = {item.phase for item in diagnostic.selected_range_phases}
        phase = "REQUIRED" if "REQUIRED" in phases else "COVERAGE" if "COVERAGE" in phases else None
        if phase is None or not (terms(PurePosixPath(path).stem) & query_terms):
            continue
        if config.relative_path(path) != path or any(ord(char) < 32 for char in path):
            raise ValueError("unsafe anchor path")
        if redactor.redact(path).text != path:
            raise ValueError("sensitive anchor path")
        symbols = [name for name in diagnostic.matched_symbols if name in selected[path]
                   and _SYMBOL.fullmatch(name) and redactor.redact(name).text == name]
        if not symbols:
            continue
        symbol = min(symbols, key=lambda name: (
            -len(terms(name) & query_terms), -int("." in name), len(name), name))
        overlap = tuple(sorted(terms(symbol) & query_terms))
        anchor = NavigationAnchor(path, symbol, phase, diagnostic.candidate_score, overlap)
        ranked.append(((-int(phase == "REQUIRED"), -len(overlap),
                        -diagnostic.candidate_score, path), anchor))

    anchors = tuple(item for _, item in sorted(ranked, key=lambda pair: pair[0])[:max_paths])
    text = "Relevant entry points:\n" + "\n".join(
        f"- {item.path}: {item.symbol}" for item in anchors)
    return OfflineAnchors(text, HeuristicTokenEstimator().estimate(text), anchors)
