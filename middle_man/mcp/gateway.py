"""Bounded, provider-neutral MCP-facing Gateway operations."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any, Callable

from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.context_models import ContextPack, ExpansionRequest
from middle_man.gateway.git_diff import GitDiff, GitDiffReader
from middle_man.gateway.handoff import HandoffService
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.models import RepositoryIndex
from middle_man.gateway.project_memory import ProjectMemoryService
from middle_man.gateway.relevance import ContextQuery, RelevanceEngine
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.usage import MCPUsageLog

MAX_CONTEXT_TOKENS = 12_000
MAX_TOP_K = 20
MAX_PACKS = 16


class _TrackingIndexer(RepositoryIndexer):
    last_index: RepositoryIndex | None = None

    def index(self, *, rebuild: bool = False) -> RepositoryIndex:
        self.last_index = super().index(rebuild=rebuild)
        return self.last_index


@dataclass(frozen=True, slots=True)
class _Payload:
    data: dict[str, Any]
    metrics: dict[str, int]
    pack_fingerprint: str | None = None
    generation: int | None = None


class MCPGateway:
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.estimator = HeuristicTokenEstimator()
        self.redactor = SecretRedactor()
        self.indexer = _TrackingIndexer(config)
        self.builder = ContextBuilder(config, indexer=self.indexer)
        self.memory = ProjectMemoryService(config)
        self.handoffs = HandoffService(config)
        self.compactor = OutputCompactor()
        self.usage = MCPUsageLog(config)
        self._packs: OrderedDict[str, ContextPack] = OrderedDict()

    def _sanitize(self, value: Any, categories: set[str]) -> Any:
        if isinstance(value, str):
            result = self.redactor.redact(value)
            categories.update(result.categories)
            return result.text
        if isinstance(value, dict):
            return {key: self._sanitize(item, categories) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item, categories) for item in value]
        return value

    def _execute(self, name: str, inputs: object, operation: Callable[[], _Payload]) -> dict[str, Any]:
        self.indexer.last_index = None
        try:
            payload = operation()
            categories: set[str] = set()
            data = self._sanitize(payload.data, categories)
            if categories:
                data["redaction_categories"] = sorted(set(data.get("redaction_categories", ())) | categories)
            metrics = {**payload.metrics, "result_tokens": self.estimator.estimate(json.dumps(data, ensure_ascii=False))}
            delivery = None
            if name in {"middleman_context_pack", "middleman_expand_context"}:
                delivery = []
                for excerpt in data["excerpts"]:
                    lines = excerpt["text"].splitlines(keepends=True)
                    delivery.append({"path": excerpt["path"], "content_hash": excerpt["content_hash"],
                                     "start_line": excerpt["start_line"], "end_line": excerpt["end_line"],
                                     "line_bytes": [len(line.encode("utf-8")) for line in lines]})
            self.usage.record(name, inputs, metrics, pack_fingerprint=payload.pack_fingerprint,
                              generation=payload.generation, delivery=delivery)
            return data
        except Exception as exc:
            self.usage.record(name, inputs, {}, error=type(exc).__name__)
            raise

    def _paths(self, paths: list[str] | None) -> tuple[str, ...]:
        if paths is None:
            return ()
        if len(paths) > 10:
            raise ValueError("at most 10 explicit paths are allowed")
        return tuple(self.config.relative_path(path) for path in paths)

    @staticmethod
    def _symbols(symbols: list[str] | None) -> tuple[str, ...]:
        if symbols is None:
            return ()
        if len(symbols) > 10 or any(not symbol or len(symbol) > 200 for symbol in symbols):
            raise ValueError("at most 10 nonempty symbols of up to 200 characters are allowed")
        return tuple(symbols)

    @staticmethod
    def _limits(top_k: int | None, budget: int | None) -> None:
        if top_k is not None and not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
        if budget is not None and not 1 <= budget <= MAX_CONTEXT_TOKENS:
            raise ValueError(f"max_context_tokens must be between 1 and {MAX_CONTEXT_TOKENS}")

    def _query(self, task: str, paths: list[str] | None, symbols: list[str] | None, error_text: str) -> ContextQuery:
        if not task.strip() or len(task) > 4096 or len(error_text) > 8192:
            raise ValueError("a nonempty bounded task and error text are required")
        return ContextQuery(task, self._paths(paths), self._symbols(symbols), error_text)

    def _diff(self, index: RepositoryIndex) -> GitDiff:
        diff = GitDiffReader(self.config).read(index)
        cache_prefix = self.config.cache_dir.relative_to(self.config.repository_root).as_posix() + "/"
        return GitDiff(diff.has_git, tuple(item for item in diff.files if not item.path.startswith(cache_prefix)))

    def _cache_stats(self) -> dict[str, int]:
        index = self.indexer.last_index
        return {"index_cache_hits": index.stats.cache_hits, "index_cache_misses": index.stats.cache_misses} if index else {}

    def _remember(self, pack: ContextPack) -> None:
        self._packs[pack.fingerprint] = pack
        self._packs.move_to_end(pack.fingerprint)
        if len(self._packs) > MAX_PACKS:
            self._packs.popitem(last=False)

    def _pack_payload(self, pack: ContextPack) -> _Payload:
        if pack.metrics.estimated_selected_tokens > MAX_CONTEXT_TOKENS:
            raise ValueError("required source exceeds the MCP Context Pack limit; use a narrower query or native read")
        metrics = pack.metrics
        data = {
            "fingerprint": pack.fingerprint, "query": pack.query.task, "mode": pack.mode.value,
            "generation": pack.generation, "selected_paths": list(pack.selected_files),
            "selected_symbols": list(pack.selected_symbols),
            "candidates": [asdict(item) for item in pack.candidates],
            "excerpts": [asdict(item) for item in pack.excerpts],
            "related_tests": list(pack.related_tests),
            "changed_files": [asdict(item) for item in pack.changed_files],
            "metrics": asdict(metrics), "warnings": list(pack.warnings),
            "redaction_categories": list(pack.redaction_categories),
            "estimate_basis": "ceil(UTF-8 bytes / 4); not provider billing or Codex quota",
        }
        return _Payload(data, {**self._cache_stats(), "raw_candidate_tokens": metrics.estimated_raw_candidate_tokens,
                               "selected_tokens": metrics.estimated_selected_tokens,
                               "tokens_avoided": metrics.estimated_tokens_avoided},
                        pack.fingerprint, pack.generation)

    def project_state(self) -> dict[str, Any]:
        def produce() -> _Payload:
            memory = self.memory.refresh()
            return _Payload({
                "repository": memory.repository_name, "branch": memory.branch, "head": memory.head,
                "technologies": [asdict(fact) for fact in memory.facts if fact.category == "technology"],
                "language_counts": [asdict(fact) for fact in memory.facts if fact.category == "language_count"],
                "components": [asdict(item) for item in memory.components],
                "changed_files": [asdict(item) for item in memory.changes],
                "decisions": [asdict(item) for item in memory.decisions],
                "open_issues": [asdict(item) for item in memory.issues if not item.resolved],
                "metrics": asdict(memory.metrics), "fingerprint": memory.fingerprint,
                "fact_basis": "derived from current index/Git; decisions and issues are explicitly user supplied",
            }, {})
        return self._execute("middleman_project_state", {}, produce)

    def session_handoff(self) -> dict[str, Any]:
        def produce() -> _Payload:
            view = self.handoffs.view(self.handoffs.latest())
            handoff = view.handoff
            summaries = []
            for item in handoff.tool_results:
                text = item.compacted_text[:4000]
                summaries.append({"output_type": item.output_type, "compacted_text": text,
                                  "truncated_for_mcp": len(text) < len(item.compacted_text),
                                  "original_estimated_tokens": item.original_estimated_tokens,
                                  "compacted_estimated_tokens": item.compacted_estimated_tokens,
                                  "fingerprint": item.fingerprint, "warnings": list(item.warnings),
                                  "redaction_categories": list(item.redaction_categories)})
            return _Payload({
                "fingerprint": handoff.fingerprint, "task": handoff.task,
                "repository": handoff.repository_name, "branch": handoff.branch, "head": handoff.head,
                "status": "stale" if view.is_stale else "current", "stale_reasons": list(view.stale_reasons),
                "changed_files": [asdict(item) for item in handoff.changes],
                "tool_results": summaries, "context": asdict(handoff.context) if handoff.context else None,
                "unresolved_issues": [asdict(item) for item in handoff.unresolved_issues],
                "next_steps": list(handoff.next_steps), "warnings": list(handoff.warnings),
                "redaction_categories": list(handoff.redaction_categories),
                "metrics": asdict(handoff.metrics), "project_memory_fingerprint": handoff.project_memory_fingerprint,
                "estimate_basis": "deduplicated full changed/selected files plus supplied raw tool output; not provider billing",
            }, {})
        return self._execute("middleman_session_handoff", {}, produce)

    def find_context(self, task: str, *, top_k: int | None = None, error_text: str = "",
                     paths: list[str] | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
        def produce() -> _Payload:
            self._limits(top_k, None)
            query = self._query(task, paths, symbols, error_text)
            index = self.indexer.index()
            candidates = RelevanceEngine(index, self.config).find(query, top_k=top_k)
            return _Payload({"ranked_files": [asdict(item) for item in candidates],
                             "count": len(candidates), "source_included": False}, self._cache_stats())
        return self._execute("middleman_find_context", {"task": task, "top_k": top_k, "error_text": error_text,
                                                         "paths": paths, "symbols": symbols}, produce)

    def context_pack(self, task: str, *, mode: str = "safe", max_context_tokens: int = 6000,
                     top_k: int | None = None, error_text: str = "", paths: list[str] | None = None,
                     symbols: list[str] | None = None) -> dict[str, Any]:
        def produce() -> _Payload:
            self._limits(top_k, max_context_tokens)
            query = self._query(task, paths, symbols, error_text)
            pack = self.builder.build(query, mode=mode, max_context_tokens=max_context_tokens, top_k=top_k)
            payload = self._pack_payload(pack)
            self._remember(pack)
            return payload
        return self._execute("middleman_context_pack", {"task": task, "mode": mode, "budget": max_context_tokens,
                                                       "top_k": top_k, "error_text": error_text, "paths": paths,
                                                       "symbols": symbols}, produce)

    def expand_context(self, fingerprint: str, kind: str, *, target: str | None = None,
                       context_lines: int = 3, max_context_tokens: int | None = None) -> dict[str, Any]:
        def produce() -> _Payload:
            self._limits(None, max_context_tokens)
            pack = self._packs.get(fingerprint)
            if pack is None:
                raise ValueError("unknown Context Pack fingerprint; build a fresh pack in this server session")
            if kind in {"file", "full_file", "related_imports", "related_tests", "surrounding_lines"} and target:
                safe_target = self.config.relative_path(target)
            else:
                safe_target = target
            request = ExpansionRequest(kind, safe_target, context_lines)
            budget = min(MAX_CONTEXT_TOKENS, pack.max_context_tokens * 2) if max_context_tokens is None else max_context_tokens
            expanded = self.builder.expand(pack, request, max_context_tokens=budget)
            payload = self._pack_payload(expanded)
            self._remember(expanded)
            return payload
        return self._execute("middleman_expand_context", {"fingerprint": fingerprint, "kind": kind,
                                                         "target": target, "context_lines": context_lines,
                                                         "budget": max_context_tokens}, produce)

    def changed_context(self, path: str | None = None) -> dict[str, Any]:
        def produce() -> _Payload:
            selected = self.config.relative_path(path) if path else None
            index = self.indexer.index()
            diff = self._diff(index)
            if not diff.has_git:
                raise ValueError("this repository has no Git diff state")
            files = [item for item in diff.files if selected is None or item.path == selected]
            if selected and not files:
                raise ValueError(f"no current change for indexed path: {selected}")
            return _Payload({"changed_files": [{"path": item.path, "status": item.status,
                                                 "old_path": item.old_path, "additions": item.additions,
                                                 "deletions": item.deletions, "binary_changed": item.binary_changed,
                                                 "affected_symbols": list(item.affected_symbols),
                                                 "hunk_ranges": [[h.new_start, h.new_start + max(1, h.new_count) - 1]
                                                                 for h in item.hunks]} for item in files],
                             "has_git": True, "raw_diff_included": False}, self._cache_stats())
        return self._execute("middleman_changed_context", {"path": path}, produce)

    def compact_output(self, output_type: str, text: str, *, max_tokens: int = 1200) -> dict[str, Any]:
        def produce() -> _Payload:
            if len(text.encode("utf-8")) > 1_000_000 or not 1 <= max_tokens <= 4000:
                raise ValueError("output input exceeds 1 MiB or max_tokens is outside 1..4000")
            if output_type == "git-diff":
                diff = self._diff(self.indexer.index())
                if not diff.has_git:
                    raise ValueError("this repository has no Git diff state")
                result = self.compactor.compact_git_diff(diff, max_tokens=max_tokens)
            else:
                result = self.compactor.compact(output_type, text, max_tokens=max_tokens)
            if result.compacted_bytes > 64_000:
                raise ValueError("required compacted output exceeds MCP result limit; inspect it with native tools")
            return _Payload({"output_type": result.output_type, "compacted_text": result.compacted_text,
                             "estimated_original_tokens": result.estimated_original_tokens,
                             "estimated_compacted_tokens": result.estimated_compacted_tokens,
                             "estimated_tokens_avoided": result.estimated_tokens_avoided,
                             "estimated_reduction_percent": result.estimated_reduction_percent,
                             "original_lines": result.original_lines, "compacted_lines": result.compacted_lines,
                             "warnings": list(result.warnings), "redaction_categories": list(result.redaction_categories),
                             "fingerprint": result.fingerprint,
                             "estimate_basis": "ceil(UTF-8 bytes / 4); not provider billing"},
                            {"compaction_original_tokens": result.estimated_original_tokens,
                             "compaction_result_tokens": result.estimated_compacted_tokens})
        return self._execute("middleman_compact_output", {"output_type": output_type,
                                                        "text": text, "max_tokens": max_tokens}, produce)

    def context_stats(self, *, fingerprint: str | None = None, task: str | None = None,
                      mode: str = "safe", max_context_tokens: int = 6000) -> dict[str, Any]:
        def produce() -> _Payload:
            if fingerprint:
                pack = self._packs.get(fingerprint)
                if pack is None:
                    raise ValueError("unknown Context Pack fingerprint; build a fresh pack in this server session")
            elif task:
                self._limits(None, max_context_tokens)
                pack = self.builder.build(self._query(task, None, None, ""), mode=mode,
                                          max_context_tokens=max_context_tokens)
                self._remember(pack)
            else:
                raise ValueError("provide a Context Pack fingerprint or a task")
            m = pack.metrics
            return _Payload({"fingerprint": pack.fingerprint, "generation": pack.generation,
                             "candidates_considered": m.candidates_considered, "files_selected": m.files_selected,
                             "excerpts_selected": m.excerpts_selected,
                             "estimated_raw_candidate_tokens": m.estimated_raw_candidate_tokens,
                             "estimated_selected_tokens": m.estimated_selected_tokens,
                             "estimated_tokens_avoided": m.estimated_tokens_avoided,
                             "estimated_reduction_percent": m.estimated_reduction_percent,
                             "warnings": list(pack.warnings),
                             "estimate_basis": "Middle_Man heuristic context tokens; not Codex quota or billing"},
                            {**self._cache_stats(), "raw_candidate_tokens": m.estimated_raw_candidate_tokens,
                             "selected_tokens": m.estimated_selected_tokens, "tokens_avoided": m.estimated_tokens_avoided},
                            pack.fingerprint, pack.generation)
        return self._execute("middleman_context_stats", {"fingerprint": fingerprint, "task": task, "mode": mode,
                                                        "budget": max_context_tokens}, produce)

    def explain_selection(self, task: str, *, path: str | None = None, top_k: int = 10) -> dict[str, Any]:
        def produce() -> _Payload:
            self._limits(top_k, None)
            safe_path = self.config.relative_path(path) if path else None
            query = self._query(task, [safe_path] if safe_path else None, None, "")
            index = self.indexer.index()
            candidates = RelevanceEngine(index, self.config).find(query, top_k=top_k)
            if safe_path:
                candidates = tuple(item for item in candidates if item.path == safe_path)
            return _Payload({"selections": [asdict(item) for item in candidates],
                             "method": "deterministic RelevanceEngine scores and reasons; no LLM"}, self._cache_stats())
        return self._execute("middleman_explain_selection", {"task": task, "path": path, "top_k": top_k}, produce)

    def repo_map(self) -> dict[str, Any]:
        def produce() -> _Payload:
            memory = self.memory.refresh()
            index = self.indexer.index()
            return _Payload({"repository": index.identity.name,
                             "language_counts": dict(index.language_counts),
                             "important_components": [asdict(item) for item in memory.components],
                             "indexed_files": len(index.files),
                             "symbol_count": sum(len(item.symbols) for item in index.files),
                             "relationship_count": len(index.relationships),
                             "source_included": False}, self._cache_stats())
        return self._execute("middleman_repo_map", {}, produce)
