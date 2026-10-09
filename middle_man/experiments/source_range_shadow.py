"""Research-only symbol-centered replacement of oversized full-file proposals."""

from __future__ import annotations

import re

from middle_man.gateway.context_builder import ContextBuilder, _Range, _excerpt_text, _matching_symbol, _merge
from middle_man.gateway.context_models import ContextMode
from middle_man.gateway.models import IndexedFile
from middle_man.gateway.relevance import RelevanceCandidate, terms
from middle_man.gateway.source import SourceFile


MIN_FULL_FILE_TOKENS = 1000
SIGNAL_KINDS = frozenset({"symbol_term", "source_term", "import_term"})


class SymbolRangeShadowBuilder(ContextBuilder):
    """Only `_select_ranges` differs; production candidate and allocation code is inherited."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.proposal_changes: list[dict[str, object]] = []

    def _select_ranges(self, record: IndexedFile, source: SourceFile,
                       candidate: RelevanceCandidate | None, diff_file: object,
                       mode: ContextMode) -> list[_Range]:
        original = super()._select_ranges(record, source, candidate, diff_file, mode)
        if (mode != ContextMode.BALANCED or candidate is None or record.is_test
                or not source.lines or not original):
            return original
        if any(part.required for part in original) or any(
                signal.kind in {"explicit_path", "trace_path", "exact_symbol"}
                for signal in candidate.signals):
            return original
        merged_original = _merge(original, self.settings.merge_gap_lines)
        line_count = len(source.lines)
        original_coverage = sum(part.end - part.start + 1 for part in merged_original)
        full_proposal = (len(merged_original) == 1 and merged_original[0].kind == "full_file"
                         and merged_original[0].start == 1 and merged_original[0].end == line_count)
        if not full_proposal and original_coverage < line_count * 0.75:
            return original
        original_cost = self.estimator.estimate(self.redactor.redact(source.text).text)
        if original_cost < MIN_FULL_FILE_TOKENS:
            return original

        evidence_terms = {signal.term for signal in candidate.signals
                          if signal.kind in SIGNAL_KINDS and len(signal.term) >= 6}
        if len(evidence_terms) < 2:
            return original
        ranked = []
        for symbol in record.symbols:
            if symbol.kind not in {"function", "method"}:
                continue
            end = symbol.end_line or symbol.start_line
            body = _excerpt_text(source, symbol.start_line, end)
            hits = evidence_terms & terms(symbol.qualified_name + "\n" + body)
            if hits:
                ranked.append((len(hits), symbol.qualified_name, symbol, body, hits))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        if not ranked or ranked[0][0] < 2 or len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return original

        _, _, symbol, body, hits = ranked[0]
        context = max(1, self.settings.context_lines // 2)
        start = symbol.start_line
        while start > 1 and source.lines[start - 2].lstrip().startswith("@"):
            start -= 1
        proposed = [_Range(max(1, start - context), min(line_count, (symbol.end_line or start) + context),
                           "symbol", (symbol.qualified_name,))]
        if symbol.parent:
            parent = _matching_symbol(record, symbol.parent)
            if parent is not None:
                proposed.append(_Range(parent.start_line, parent.start_line, "class_header",
                                       (parent.qualified_name,)))
        for imported in record.imports:
            needle = imported.name or imported.module.split(".")[0]
            if needle and re.search(r"\b" + re.escape(needle) + r"\b", body):
                proposed.append(_Range(imported.line, imported.line, "import", ()))
        merged = _merge(proposed, self.settings.merge_gap_lines)
        if sum(part.end - part.start + 1 for part in merged) >= line_count * 0.75:
            return original
        narrow_cost = sum(self.estimator.estimate(self.redactor.redact(
            _excerpt_text(source, part.start, part.end)).text) for part in merged)
        if narrow_cost >= original_cost:
            return original

        self.proposal_changes.append({
            "path": record.path, "symbol": symbol.qualified_name,
            "evidence_terms": sorted(hits), "original_source_tokens": original_cost,
            "proposed_source_tokens": narrow_cost,
            "original_ranges": [[1, line_count]],
            "proposed_ranges": [[part.start, part.end] for part in merged],
        })
        return list(merged)
