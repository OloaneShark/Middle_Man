"""Deterministic, explainable ranking over indexed repository structure."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import RepositoryIndex
from middle_man.gateway.source import SourceReader, UnsafeSourceError

STOP_WORDS = frozenset({"a", "an", "and", "are", "at", "be", "by", "do", "does", "for", "from", "how", "in", "is", "it", "of", "on", "or", "the", "this", "to", "was", "where", "why", "with", "file", "code", "handled", "handle", "fix", "bug", "repository", "symbol", "component", "concrete", "concise", "explain", "explanation", "implementation", "modify", "proving", "name", "used", "already", "works", "give", "not", "required"})
WEIGHTS = {"explicit_path": 120.0, "trace_path": 105.0, "exact_symbol": 95.0,
           "filename_term": 28.0, "symbol_term": 17.0, "path_term": 8.0,
           "import_term": 5.0, "source_term": 5.0, "family_term": 3.0,
           "import_neighbor": 13.0, "reverse_import_neighbor": 10.0,
           "related_test": 12.0, "tested_source": 12.0, "changed_relevant": 9.0}


def terms(value: str) -> frozenset[str]:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    split = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", split)
    return frozenset(part.lower() for part in re.findall(r"[A-Za-z0-9]+", split)
                     if len(part) > 1 and part.lower() not in STOP_WORDS)


def lexical_family(left: str, right: str) -> bool:
    if min(len(left), len(right)) < 6 or left == right:
        return False
    common = 0
    for a, b in zip(left, right):
        if a != b:
            break
        common += 1
    return common >= 6 and common / min(len(left), len(right)) >= 0.7


@dataclass(frozen=True, slots=True)
class ContextQuery:
    task: str
    paths: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    error_text: str = ""
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchSignal:
    kind: str
    key: str
    weight: float
    reason: str
    term: str = ""


@dataclass(frozen=True, slots=True)
class RelevanceCandidate:
    path: str
    score: float
    role: str
    matched_symbols: tuple[str, ...]
    reasons: tuple[str, ...]
    matched_terms: tuple[str, ...] = ()
    signals: tuple[MatchSignal, ...] = ()


class RelevanceEngine:
    def __init__(self, index: RepositoryIndex, config: GatewayConfig) -> None:
        self.index = index
        self.config = config

    def find(self, query: ContextQuery | str, *, top_k: int | None = None,
             minimum_score: float | None = None) -> tuple[RelevanceCandidate, ...]:
        if isinstance(query, str):
            query = ContextQuery(query)
        limit = self.config.max_search_results if top_k is None else top_k
        floor = self.config.minimum_score if minimum_score is None else minimum_score
        if limit < 1 or floor < 0:
            raise ValueError("top_k must be positive and minimum_score nonnegative")
        query_terms = terms(query.task) | terms(query.error_text)
        identifiers = set(re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", query.task + " " + query.error_text))
        identifiers = {value for value in identifiers if value.casefold() not in STOP_WORDS or value != value.lower()}
        identifiers.update(query.symbols)
        named_paths = {value.replace("\\", "/").lstrip("./") for value in query.paths}
        changed = {value.replace("\\", "/").lstrip("./") for value in (query.changed_files or self.index.changed_paths)}
        metadata = {item.path: terms(item.path) | frozenset(
            term for symbol in item.symbols for term in terms(symbol.name)) for item in self.index.files}
        frequency = Counter(term for values in metadata.values() for term in values)
        useful = {term for term in query_terms if frequency[term] <= max(3, int(len(self.index.files) * 0.3))}
        signals: dict[str, dict[str, MatchSignal]] = {}
        matched_symbols: dict[str, set[str]] = {}
        primary: set[str] = set()

        def add(path: str, kind: str, key: str, reason: str, *, term: str = "", weight: float | None = None) -> None:
            signal = MatchSignal(kind, key, WEIGHTS[kind] if weight is None else weight, reason, term)
            bucket = signals.setdefault(path, {})
            old = bucket.get(key)
            if old is None or signal.weight > old.weight:
                bucket[key] = signal

        for item in self.index.files:
            path = item.path
            if path in named_paths or re.search(r"(?<![\w/])" + re.escape(path) + r"(?![\w/])", query.task.replace("\\", "/")):
                add(path, "explicit_path", f"path:{path}", f"explicit path: {path}")
            if path in query.error_text.replace("\\", "/"):
                add(path, "trace_path", f"trace:{path}", f"trace path: {path}")
            filename = terms(PurePosixPath(path).stem)
            for term in sorted(useful & filename):
                add(path, "filename_term", f"term:{term}", f"filename term: {term}", term=term)
            for term in sorted(useful & (terms(path) - filename)):
                add(path, "path_term", f"term:{term}", f"path term: {term}", term=term)
            for symbol in item.symbols:
                if symbol.name in identifiers or symbol.qualified_name in identifiers:
                    add(path, "exact_symbol", f"symbol:{symbol.qualified_name}",
                        f"exact symbol: {symbol.qualified_name}")
                    matched_symbols.setdefault(path, set()).add(symbol.qualified_name)
                for term in sorted(useful & terms(symbol.name)):
                    add(path, "symbol_term", f"term:{term}", f"symbol term: {symbol.qualified_name} ({term})", term=term)
                    matched_symbols.setdefault(path, set()).add(symbol.qualified_name)
            imports = {term for record in item.imports for term in terms(record.module + "." + (record.name or ""))}
            for term in sorted(useful & imports - filename):
                add(path, "import_term", f"term:{term}", f"import term: {term}", term=term)
            for term in sorted(useful - filename):
                if any(lexical_family(term, value) for value in filename):
                    add(path, "family_term", f"term:{term}", f"lexical family filename: {term}", term=term, weight=8.0)
                elif any(lexical_family(term, value) for value in metadata[path]):
                    add(path, "family_term", f"term:{term}", f"lexical family symbol/path: {term}", term=term)
            if path in signals:
                primary.add(path)

        # A graph relationship contributes once per kind, even for busy shared modules.
        for path in sorted(primary):
            if sum(signal.weight for signal in signals[path].values()) < WEIGHTS["filename_term"]:
                continue
            for target in self.index.imports_for(path):
                add(target, "import_neighbor", "graph:import", f"imported by relevant file: {path}")
            for source in self.index.importers_of(path):
                add(source, "reverse_import_neighbor", "graph:reverse", f"imports relevant file: {path}")
            for test in self.index.tests_for(path):
                add(test, "related_test", "graph:test", f"tests relevant file: {path}")
            if self.index.get_file(path).is_test:
                for target in self.index.imports_for(path):
                    add(target, "tested_source", "graph:tested", f"tested by relevant file: {path}")

        # Verified source terms distinguish directly related modules with generic filenames.
        reader = SourceReader(self.config, self.index)
        for path in sorted(signals):
            item = self.index.get_file(path)
            if not item or not item.is_text or item.language in {"Markdown", "Other"} or item.size_bytes > 100_000:
                continue
            try:
                source_terms = terms(reader.read(path).text)
            except UnsafeSourceError:
                continue
            content_hits = 0
            for term in sorted(useful, key=lambda value: (frequency[value], -len(value), value)):
                if content_hits >= 2:
                    break
                if len(term) < 6 or f"term:{term}" in signals[path]:
                    continue
                if term in source_terms:
                    add(path, "source_term", f"term:{term}", f"source term: {term}", term=term,
                        weight=12.0 if frequency[term] <= 2 else WEIGHTS["source_term"])
                    content_hits += 1
                elif any(lexical_family(term, value) for value in source_terms):
                    add(path, "family_term", f"term:{term}", f"lexical family source: {term}", term=term,
                        weight=10.0 if frequency[term] <= 2 else WEIGHTS["family_term"])
                    content_hits += 1
        candidates = []
        for path in signals:
            if path in changed:
                add(path, "changed_relevant", "changed", "relevant changed file")
            ordered = tuple(sorted(signals[path].values(), key=lambda item: (-item.weight, item.key)))
            score = round(sum(item.weight for item in ordered), 2)
            if score >= floor:
                candidates.append(RelevanceCandidate(
                    path, score, "PRIMARY" if path in primary else "RELATED",
                    tuple(sorted(matched_symbols.get(path, ()))), tuple(item.reason for item in ordered),
                    tuple(sorted({item.term for item in ordered if item.term})), ordered))
        return tuple(sorted(candidates, key=lambda item: (-item.score, item.path))[:limit])
