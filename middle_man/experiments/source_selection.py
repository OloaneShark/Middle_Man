"""Offline-only ranking that distinguishes code anchors from ordinary prose."""

from __future__ import annotations

import re

from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.context_models import ContextMode, ExpansionRequest, SourceExcerpt
from middle_man.gateway.git_diff import GitDiffReader
from middle_man.gateway.models import RepositoryIndex
from middle_man.gateway.relevance import ContextQuery, RelevanceCandidate, RelevanceEngine
from middle_man.gateway.source import StaleSourceError


_IDENTIFIER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def _code_identifiers(query: ContextQuery) -> set[str]:
    values = set(query.symbols)
    for match in _IDENTIFIER.finditer(query.task + " " + query.error_text):
        value = match.group()
        if "." in value or "_" in value or re.search(r"[a-z][A-Z]", value):
            values.add(value)
    return values


def code_anchor_candidates(
        index: RepositoryIndex, engine: RelevanceEngine, query: ContextQuery, limit: int
        ) -> tuple[RelevanceCandidate, ...]:
    """Rerank before the cap; prose-only symbol coincidences are not exact anchors."""
    ranked = engine.find(query, top_k=len(index.files))
    code_identifiers = _code_identifiers(query)
    adjusted = []
    for candidate in ranked:
        anchored = any(signal.kind in {"explicit_path", "trace_path"}
                       for signal in candidate.signals)
        discarded = {signal.key for signal in candidate.signals
                     if signal.kind == "exact_symbol"
                     and signal.key.removeprefix("symbol:") not in code_identifiers
                     and not anchored}
        if not discarded:
            adjusted.append(candidate)
            continue
        signals = tuple(signal for signal in candidate.signals if signal.key not in discarded)
        if not signals:
            continue
        symbol_terms = {signal.reason.removeprefix("symbol term: ").split(" (", 1)[0]
                        for signal in signals if signal.kind == "symbol_term"}
        matched_symbols = tuple(symbol for symbol in candidate.matched_symbols
                                if f"symbol:{symbol}" not in discarded or symbol in symbol_terms)
        adjusted.append(RelevanceCandidate(
            candidate.path, round(sum(signal.weight for signal in signals), 2),
            candidate.role, matched_symbols, tuple(signal.reason for signal in signals),
            tuple(sorted({signal.term for signal in signals if signal.term})), signals))
    return tuple(sorted(adjusted, key=lambda item: (-item.score, item.path))[:limit])


class CodeAnchorContextBuilder(ContextBuilder):
    """Run the production allocator on an experimental code-anchor candidate order."""

    def _build(self, query: ContextQuery, mode: ContextMode, budget: int, top_k: int | None,
               generation: int, previous: tuple[SourceExcerpt, ...],
               expansion: ExpansionRequest | None = None,
               depth_token_limit: int | None = None):
        stale_during_build = False
        for attempt in range(2):
            index = self.indexer.index()
            diff = GitDiffReader(self.config).read(index)
            changed = tuple(item.path for item in diff.files if index.get_file(item.path))
            effective_query = ContextQuery(query.task, query.paths, query.symbols, query.error_text,
                                           query.changed_files or changed)
            try:
                candidates = code_anchor_candidates(
                    index, RelevanceEngine(index, self.config), effective_query,
                    top_k if top_k is not None else max(50, self.config.max_search_results))
                return self._assemble(index, diff, effective_query, candidates, mode, budget,
                                      generation, previous, expansion, stale_during_build,
                                      depth_token_limit)
            except StaleSourceError:
                stale_during_build = True
                if attempt:
                    raise
        raise AssertionError("unreachable")
