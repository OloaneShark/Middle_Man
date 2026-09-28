"""Budgeted, source-verified Context Pack construction and expansion."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_models import (ChangedContext, ContextMetrics, ContextMode, ContextPack,
                                               ExpansionRequest, SourceExcerpt)
from middle_man.gateway.git_diff import GitDiff, GitDiffReader
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.models import IndexedFile, RepositoryIndex, Symbol
from middle_man.gateway.relevance import ContextQuery, RelevanceCandidate, RelevanceEngine
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.source import SourceFile, SourceReader, StaleSourceError, UnsafeSourceError
from middle_man.gateway.tokens import HeuristicTokenEstimator, TokenEstimator


@dataclass(frozen=True, slots=True)
class ContextSettings:
    max_context_tokens: int = 8000
    context_lines: int = 3
    merge_gap_lines: int = 2
    safe_full_file_lines: int = 80
    balanced_full_file_lines: int = 40
    aggressive_full_file_lines: int = 20
    max_symbols_per_file: int = 4

    def __post_init__(self) -> None:
        if self.max_context_tokens < 1 or min(self.context_lines, self.merge_gap_lines, self.safe_full_file_lines,
                                               self.balanced_full_file_lines, self.aggressive_full_file_lines) < 0 or self.max_symbols_per_file < 1:
            raise ValueError("invalid context settings")


@dataclass(frozen=True, slots=True)
class _Range:
    start: int
    end: int
    kind: str
    symbols: tuple[str, ...]
    required: bool = False


def _merge(ranges: list[_Range], gap: int) -> tuple[_Range, ...]:
    merged: list[_Range] = []
    for item in sorted(ranges, key=lambda part: (part.start, part.end)):
        if merged and item.start <= merged[-1].end + gap + 1:
            previous = merged.pop()
            merged.append(_Range(previous.start, max(previous.end, item.end),
                                 "full_file" if previous.kind == "full_file" or item.kind == "full_file" else "merged",
                                 tuple(sorted(set(previous.symbols + item.symbols))), previous.required or item.required))
        else:
            merged.append(item)
    return tuple(merged)


def _excerpt_text(source: SourceFile, start: int, end: int) -> str:
    return "".join(source.lines[start - 1:end])


def _matching_symbol(record: IndexedFile, qualified: str) -> Symbol | None:
    return next((symbol for symbol in record.symbols if symbol.qualified_name == qualified), None)


class ContextBuilder:
    def __init__(self, config: GatewayConfig, *, settings: ContextSettings | None = None,
                 estimator: TokenEstimator | None = None, redactor: SecretRedactor | None = None,
                 indexer: RepositoryIndexer | None = None) -> None:
        self.config = config
        self.settings = settings or ContextSettings()
        self.estimator = estimator or HeuristicTokenEstimator()
        self.redactor = redactor or SecretRedactor()
        self.indexer = indexer or RepositoryIndexer(config)

    def build(self, query: ContextQuery | str, *, mode: ContextMode | str = ContextMode.SAFE,
              max_context_tokens: int | None = None, top_k: int | None = None) -> ContextPack:
        if isinstance(query, str):
            query = ContextQuery(query)
        mode = ContextMode(mode)
        budget = self.settings.max_context_tokens if max_context_tokens is None else max_context_tokens
        if budget < 1:
            raise ValueError("max_context_tokens must be positive")
        task_redaction = self.redactor.redact(query.task)
        error_redaction = self.redactor.redact(query.error_text)
        safe_query = ContextQuery(task_redaction.text, query.paths, query.symbols,
                                  error_redaction.text, query.changed_files)
        pack = self._build(safe_query, mode, budget, top_k, 0, ())
        query_categories = task_redaction.categories + error_redaction.categories
        if query_categories:
            pack = replace(pack, warnings=tuple(dict.fromkeys((*pack.warnings, "REDACTIONS_APPLIED"))),
                           redaction_categories=pack.redaction_categories + query_categories)
        return pack

    def expand(self, pack: ContextPack, request: ExpansionRequest, *, max_context_tokens: int | None = None) -> ContextPack:
        if pack.repository.root != str(self.config.repository_root):
            raise ValueError("Context Pack belongs to a different repository")
        budget = pack.max_context_tokens * 2 if max_context_tokens is None else max_context_tokens
        if budget < 1:
            raise ValueError("max_context_tokens must be positive")
        return self._build(pack.query, pack.mode, budget, max(len(pack.candidates) + 3, self.config.max_search_results),
                           pack.generation + 1, pack.excerpts, request)

    def _build(self, query: ContextQuery, mode: ContextMode, budget: int, top_k: int | None,
               generation: int, previous: tuple[SourceExcerpt, ...], expansion: ExpansionRequest | None = None) -> ContextPack:
        stale_during_build = False
        for attempt in range(2):
            index = self.indexer.index()
            diff = GitDiffReader(self.config).read(index)
            changed = tuple(item.path for item in diff.files if index.get_file(item.path))
            effective_query = ContextQuery(query.task, query.paths, query.symbols, query.error_text,
                                           query.changed_files or changed)
            candidates = RelevanceEngine(index, self.config).find(effective_query, top_k=top_k)
            try:
                return self._assemble(index, diff, effective_query, candidates, mode, budget, generation, previous, expansion, stale_during_build)
            except StaleSourceError:
                stale_during_build = True
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def _assemble(self, index: RepositoryIndex, diff: GitDiff, query: ContextQuery,
                  candidates: tuple[RelevanceCandidate, ...], mode: ContextMode, budget: int,
                  generation: int, previous: tuple[SourceExcerpt, ...], expansion: ExpansionRequest | None,
                  stale_during_build: bool) -> ContextPack:
        reader = SourceReader(self.config, index)
        by_path = {item.path: item for item in candidates}
        forced: dict[str, list[_Range]] = {}
        warnings: list[str] = ["SOURCE_CHANGED_DURING_SELECTION"] if stale_during_build else []
        for prior in previous:
            current = index.get_file(prior.path)
            if current and current.sha256 == prior.content_hash:
                forced.setdefault(prior.path, []).append(_Range(prior.start_line, prior.end_line, prior.kind, prior.symbols, True))
            elif current:
                warnings.append(f"SOURCE_CHANGED_DURING_SELECTION:{prior.path}")
            else:
                warnings.append(f"SOURCE_REMOVED_SINCE_EXPANSION:{prior.path}")
        if expansion:
            self._expansion_ranges(expansion, index, candidates, previous, forced, by_path)
        selected_paths = list(dict.fromkeys([*by_path, *forced]))
        sources: dict[str, SourceFile] = {}
        raw_bytes = 0
        raw_tokens = 0
        ranges: dict[str, tuple[_Range, ...]] = {}
        duplicate_bytes = 0
        for path in selected_paths:
            record = index.get_file(path)
            if record is None:
                continue
            if record.parse_status == "oversized":
                warnings.append(f"OVERSIZED_RELEVANT_FILE:{path}")
                continue
            if not record.is_text:
                continue
            try:
                source = reader.read(path)
            except UnsafeSourceError:
                warnings.append(f"UNSAFE_OR_UNREADABLE_SOURCE:{path}")
                continue
            sources[path] = source
            raw_bytes += source.size_bytes
            raw_tokens += self.estimator.estimate(source.text)
            candidate = by_path.get(path)
            proposed = self._select_ranges(record, source, candidate, diff.get_file(path), mode)
            proposed.extend(forced.get(path, ()))
            proposed = [_Range(max(1, part.start), min(len(source.lines), part.end), part.kind, part.symbols, part.required)
                        for part in proposed if source.lines and part.start <= len(source.lines)]
            merged = _merge(proposed, self.settings.merge_gap_lines)
            if merged and sum(part.end - part.start + 1 for part in merged) >= len(source.lines) * 0.75:
                merged = (_Range(1, len(source.lines), "full_file", tuple(sorted({name for item in merged for name in item.symbols})),
                                 any(item.required for item in merged)),)
            duplicate_bytes += max(0, sum(len(_excerpt_text(source, part.start, part.end).encode("utf-8")) for part in proposed)
                                   - sum(len(_excerpt_text(source, part.start, part.end).encode("utf-8")) for part in merged))
            ranges[path] = merged
        planned: list[tuple[float, str, _Range]] = []
        for path, items in ranges.items():
            candidate = by_path.get(path)
            score = candidate.score if candidate else 0
            for item in items:
                priority = score + (1000 if item.required else 0) + (30 if candidate and candidate.role == "PRIMARY" else 0)
                planned.append((priority, path, item))
        planned.sort(key=lambda entry: (-entry[0], entry[1], entry[2].start))
        excerpts: list[SourceExcerpt] = []
        redactions: list[str] = []
        used_tokens = 0
        for _, path, item in planned:
            source = sources[path]
            raw_excerpt = _excerpt_text(source, item.start, item.end)
            sanitized = self.redactor.redact(raw_excerpt)
            cost = self.estimator.estimate(sanitized.text)
            if used_tokens + cost > budget and not item.required:
                warnings.append(f"CONTEXT_BUDGET_OMISSION:{path}:{item.start}-{item.end}")
                continue
            if used_tokens + cost > budget:
                warnings.append(f"BUDGET_EXCEEDED_FOR_REQUIRED_SYMBOL:{path}")
            used_tokens += cost
            redactions.extend(sanitized.categories)
            candidate = by_path.get(path)
            excerpts.append(SourceExcerpt(path, item.start, item.end, sanitized.text, item.kind, item.symbols,
                                          candidate.reasons if candidate else ("explicit expansion",),
                                          candidate.score if candidate else 0.0,
                                          item.start == 1 and item.end == len(source.lines),
                                          item.kind in {"file_opening", "file_expansion", "candidate_expansion", "changed_hunk"}
                                          and not (item.start == 1 and item.end == len(source.lines)), source.sha256))
        excerpts.sort(key=lambda item: (next((n for n, path, _ in planned if path == item.path), 0) * -1,
                                        item.path, item.start_line))
        if redactions:
            warnings.append("REDACTIONS_APPLIED")
        if not excerpts or not candidates:
            warnings.append("LOW_RELEVANCE_CONFIDENCE")
        if mode == ContextMode.AGGRESSIVE and any(not item.complete_file for item in excerpts):
            warnings.append("CONTEXT_REDUCED_AGGRESSIVE")
        selected_bytes = sum(len(item.text.encode("utf-8")) for item in excerpts)
        selected_tokens = sum(self.estimator.estimate(item.text) for item in excerpts)
        selected_paths_set = {item.path for item in excerpts}
        metrics = ContextMetrics(len(index.files), len(candidates), len(selected_paths_set),
                                 sum(item.complete_file for item in excerpts), len(excerpts),
                                 sum(item.end_line - item.start_line + 1 for item in excerpts), raw_bytes,
                                 selected_bytes, raw_tokens, selected_tokens, max(0, raw_tokens - selected_tokens),
                                 round(100 * max(0, raw_tokens - selected_tokens) / raw_tokens, 2) if raw_tokens else 0.0,
                                 duplicate_bytes)
        changed_context = tuple(ChangedContext(item.path, item.status, item.old_path, item.affected_symbols,
                                               tuple((hunk.new_start, hunk.new_start + max(hunk.new_count, 1) - 1) for hunk in item.hunks))
                                for item in diff.files if item.path in selected_paths_set)
        related_tests = tuple(sorted(path for path in selected_paths_set if index.get_file(path).is_test))
        fingerprint_query = {**asdict(query), "changed_files": tuple(path for path in query.changed_files if path in selected_paths_set)}
        fingerprint_data = {"query": fingerprint_query, "root": index.identity.root, "mode": mode.value, "budget": budget,
                            "generation": generation,
                            "source": [(item.path, item.content_hash, item.start_line, item.end_line, item.text) for item in excerpts]}
        fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode("utf-8")).hexdigest()
        return ContextPack(fingerprint, query, index.identity, mode, budget, generation, candidates, tuple(excerpts),
                           related_tests, changed_context, metrics, tuple(dict.fromkeys(warnings)), tuple(redactions))

    def _select_ranges(self, record: IndexedFile, source: SourceFile, candidate: RelevanceCandidate | None,
                       diff_file: object, mode: ContextMode) -> list[_Range]:
        if candidate is None or not source.lines:
            return []
        lines = len(source.lines)
        full_limit = {ContextMode.SAFE: self.settings.safe_full_file_lines,
                      ContextMode.BALANCED: self.settings.balanced_full_file_lines,
                      ContextMode.AGGRESSIVE: self.settings.aggressive_full_file_lines}[mode]
        file_required = any(reason.startswith(("explicit path", "trace path")) for reason in candidate.reasons)
        exact_names = {reason.removeprefix("exact symbol: ") for reason in candidate.reasons if reason.startswith("exact symbol: ")}
        affected = getattr(diff_file, "affected_symbols", ())
        names = list(dict.fromkeys([*sorted(exact_names), *affected, *candidate.matched_symbols]))[:self.settings.max_symbols_per_file]
        chosen = [_matching_symbol(record, name) for name in names]
        chosen = [symbol for symbol in chosen if symbol and not any(exact.startswith(symbol.qualified_name + ".")
                  for exact in exact_names if symbol.qualified_name not in exact_names)]
        if lines <= full_limit and mode == ContextMode.SAFE or lines <= full_limit and not chosen:
            return [_Range(1, lines, "full_file", tuple(names), file_required or bool(exact_names))]
        ranges: list[_Range] = []
        context = self.settings.context_lines if mode == ContextMode.SAFE else max(1, self.settings.context_lines // 2) if mode == ContextMode.BALANCED else 0
        for symbol in chosen:
            required = file_required or symbol.qualified_name in exact_names
            end = symbol.end_line or symbol.start_line
            start = symbol.start_line
            while start > 1 and source.lines[start - 2].lstrip().startswith("@"):
                start -= 1
            ranges.append(_Range(max(1, start - context), min(lines, end + context), "symbol", (symbol.qualified_name,), required))
            if symbol.parent:
                parent = _matching_symbol(record, symbol.parent)
                if parent:
                    ranges.append(_Range(parent.start_line, parent.start_line, "class_header", (parent.qualified_name,), required))
            body = _excerpt_text(source, symbol.start_line, end)
            for imported in record.imports:
                if imported.name and re.search(r"\b" + re.escape(imported.name) + r"\b", body) or not imported.name and re.search(r"\b" + re.escape(imported.module.split(".")[0]) + r"\b", body):
                    ranges.append(_Range(imported.line, imported.line, "import", (), False))
            for constant in record.symbols:
                if constant.kind == "constant" and re.search(r"\b" + re.escape(constant.name) + r"\b", body):
                    ranges.append(_Range(constant.start_line, constant.end_line or constant.start_line, "constant", (constant.name,), False))
        if not ranges and diff_file and getattr(diff_file, "hunks", ()):
            for hunk in diff_file.hunks[:3]:
                start = max(1, hunk.new_start - context)
                end = min(lines, hunk.new_start + max(hunk.new_count, 1) - 1 + context)
                ranges.append(_Range(start, end, "changed_hunk", (), file_required))
        if not ranges:
            fallback = min(lines, 100 if mode == ContextMode.SAFE else 50 if mode == ContextMode.BALANCED else 25)
            ranges.append(_Range(1, fallback, "file_opening", (), file_required))
        return ranges

    def _expansion_ranges(self, request: ExpansionRequest, index: RepositoryIndex,
                          candidates: tuple[RelevanceCandidate, ...], previous: tuple[SourceExcerpt, ...],
                          forced: dict[str, list[_Range]], by_path: dict[str, RelevanceCandidate]) -> None:
        if request.kind == "next_candidates":
            for candidate in candidates:
                if candidate.path not in {item.path for item in previous}:
                    forced.setdefault(candidate.path, []).append(_Range(1, 1, "candidate_expansion", (), True))
                    break
            return
        target = request.target or (previous[0].path if previous else None)
        if target is None:
            return
        if request.kind == "symbol":
            for symbol in index.find_symbol(target):
                forced.setdefault(symbol.path, []).append(_Range(symbol.start_line, symbol.end_line or symbol.start_line,
                                                                  "symbol", (symbol.qualified_name,), True))
            return
        if request.kind in {"related_imports", "related_tests"}:
            paths = index.imports_for(target) if request.kind == "related_imports" else index.tests_for(target)
            for path in paths:
                record = index.get_file(path)
                if record:
                    forced.setdefault(path, []).append(_Range(1, record.line_count or 1, "related_expansion", (), True))
            return
        record = index.get_file(target)
        if record is None:
            raise ValueError(f"file is not indexed: {target}")
        if request.kind == "full_file":
            forced.setdefault(target, []).append(_Range(1, record.line_count or 1, "full_file", (), True))
        elif request.kind == "surrounding_lines":
            for item in previous:
                if item.path == target:
                    forced.setdefault(target, []).append(_Range(max(1, item.start_line - request.context_lines),
                                                                  item.end_line + request.context_lines, "expanded_surroundings", item.symbols, True))
        elif request.kind == "file":
            forced.setdefault(target, []).append(_Range(1, min(record.line_count or 1, self.settings.safe_full_file_lines),
                                                          "file_expansion", (), True))
