"""Deterministic, explainable ranking over indexed repository structure."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import RepositoryIndex

STOP_WORDS = frozenset({"a", "an", "and", "are", "at", "be", "by", "do", "does", "for", "from", "how", "in", "is", "it", "of", "on", "or", "the", "this", "to", "was", "where", "why", "with", "file", "code", "handled", "handle", "fix", "bug"})
WEIGHTS = {
    "explicit_path": 120.0,
    "trace_path": 105.0,
    "exact_symbol": 95.0,
    "filename_term": 28.0,
    "symbol_term": 17.0,
    "path_term": 8.0,
    "import_term": 5.0,
    "import_neighbor": 13.0,
    "reverse_import_neighbor": 10.0,
    "related_test": 12.0,
    "tested_source": 12.0,
    "changed_relevant": 9.0,
}


def terms(value: str) -> frozenset[str]:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    split = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", split)
    return frozenset(part.lower() for part in re.findall(r"[A-Za-z0-9]+", split) if len(part) > 1 and part.lower() not in STOP_WORDS)


@dataclass(frozen=True, slots=True)
class ContextQuery:
    task: str
    paths: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    error_text: str = ""
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RelevanceCandidate:
    path: str
    score: float
    role: str
    matched_symbols: tuple[str, ...]
    reasons: tuple[str, ...]


class RelevanceEngine:
    def __init__(self, index: RepositoryIndex, config: GatewayConfig) -> None:
        self.index = index
        self.config = config

    def find(self, query: ContextQuery | str, *, top_k: int | None = None, minimum_score: float | None = None) -> tuple[RelevanceCandidate, ...]:
        if isinstance(query, str):
            query = ContextQuery(query)
        limit = self.config.max_search_results if top_k is None else top_k
        floor = self.config.minimum_score if minimum_score is None else minimum_score
        if limit < 1 or floor < 0:
            raise ValueError("top_k must be positive and minimum_score nonnegative")
        task_terms = terms(query.task)
        trace_terms = terms(query.error_text)
        identifiers = set(re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", query.task + " " + query.error_text))
        identifiers.update(query.symbols)
        named_paths = {value.replace("\\", "/").lstrip("./") for value in query.paths}
        changed = {value.replace("\\", "/").lstrip("./") for value in (query.changed_files or self.index.changed_paths)}
        primary: dict[str, list[tuple[float, str]]] = {}
        matching_symbols: dict[str, set[str]] = {}
        for item in self.index.files:
            signals: list[tuple[float, str]] = []
            path = item.path
            if path in named_paths or re.search(r"(?<![\w/])" + re.escape(path) + r"(?![\w/])", query.task.replace("\\", "/")):
                signals.append((WEIGHTS["explicit_path"], f"explicit path: {path}"))
            if path in query.error_text.replace("\\", "/"):
                signals.append((WEIGHTS["trace_path"], f"trace path: {path}"))
            filename_terms = terms(PurePosixPath(path).stem)
            for term in sorted(task_terms & filename_terms):
                signals.append((WEIGHTS["filename_term"], f"filename term: {term}"))
            for term in sorted((task_terms | trace_terms) & (terms(path) - filename_terms)):
                signals.append((WEIGHTS["path_term"], f"path term: {term}"))
            seen_symbol_terms: set[str] = set()
            for symbol in item.symbols:
                if symbol.name in identifiers or symbol.qualified_name in identifiers:
                    signals.append((WEIGHTS["exact_symbol"], f"exact symbol: {symbol.qualified_name}"))
                    matching_symbols.setdefault(path, set()).add(symbol.qualified_name)
                else:
                    for term in sorted(((task_terms | trace_terms) & terms(symbol.name)) - seen_symbol_terms):
                        seen_symbol_terms.add(term)
                        signals.append((WEIGHTS["symbol_term"], f"symbol term: {symbol.qualified_name} ({term})"))
                        matching_symbols.setdefault(path, set()).add(symbol.qualified_name)
            import_names = {term for record in item.imports for term in terms(record.module + "." + (record.name or ""))}
            for term in sorted(task_terms & import_names - filename_terms):
                signals.append((WEIGHTS["import_term"], f"import term: {term}"))
            if signals:
                primary[path] = signals
        reasons: dict[str, list[tuple[float, str]]] = {path: list(signals) for path, signals in primary.items()}
        # One hop only: graph context should not outrank explicit or exact matches.
        for path, signals in primary.items():
            if sum(value for value, _ in signals) < WEIGHTS["filename_term"]:
                continue
            for target in self.index.imports_for(path):
                reasons.setdefault(target, []).append((WEIGHTS["import_neighbor"], f"imported by relevant file: {path}"))
            for source in self.index.importers_of(path):
                reasons.setdefault(source, []).append((WEIGHTS["reverse_import_neighbor"], f"imports relevant file: {path}"))
            for test in self.index.tests_for(path):
                reasons.setdefault(test, []).append((WEIGHTS["related_test"], f"tests relevant file: {path}"))
            for target in self.index.imports_for(path):
                if self.index.get_file(path) and self.index.get_file(path).is_test:
                    reasons.setdefault(target, []).append((WEIGHTS["tested_source"], f"tested by relevant file: {path}"))
        candidates = []
        for path, signals in reasons.items():
            if path in changed:
                signals.append((WEIGHTS["changed_relevant"], "relevant changed file"))
            score = round(sum(value for value, _ in signals), 2)
            if score >= floor:
                candidates.append(RelevanceCandidate(path, score, "PRIMARY" if path in primary else "RELATED",
                                                     tuple(sorted(matching_symbols.get(path, ()))),
                                                     tuple(dict.fromkeys(reason for _, reason in signals))))
        return tuple(sorted(candidates, key=lambda item: (-item.score, item.path))[:limit])
