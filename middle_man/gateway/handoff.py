"""Provider-neutral, factual session handoffs and continuation checks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from middle_man.gateway.compact import CompactionResult, OutputCompactor
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_models import ContextPack
from middle_man.gateway.git_diff import GitDiffReader
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.models import RepositoryIndex
from middle_man.gateway.project_memory import ProjectMemoryService
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.source import SourceReader, StaleSourceError, UnsafeSourceError
from middle_man.gateway.state_store import AtomicJsonStore, StateStoreError
from middle_man.gateway.tokens import HeuristicTokenEstimator, TokenEstimator

HANDOFF_SCHEMA_VERSION = 1
_ID = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class HandoffChange:
    path: str
    status: str
    old_path: str | None
    affected_symbols: tuple[str, ...]
    source_hash: str | None


@dataclass(frozen=True, slots=True)
class HandoffFileReference:
    path: str
    source_hash: str | None


@dataclass(frozen=True, slots=True)
class ContextReference:
    fingerprint: str
    mode: str
    query: str
    selected_paths: tuple[str, ...]
    estimated_selected_tokens: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HandoffToolResult:
    output_type: str
    compacted_text: str
    original_estimated_tokens: int
    compacted_estimated_tokens: int
    fingerprint: str
    warnings: tuple[str, ...]
    redaction_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HandoffIssue:
    text: str
    provenance: str
    reference_id: str | None = None


@dataclass(frozen=True, slots=True)
class HandoffMetrics:
    handoff_bytes: int
    estimated_handoff_tokens: int
    estimated_reconstruction_tokens: int
    estimated_tokens_avoided: int
    estimated_reduction_percent: float


@dataclass(frozen=True, slots=True)
class SessionHandoff:
    schema_version: int
    repository_root: str
    repository_name: str
    branch: str | None
    head: str | None
    task: str
    created_at: str
    changes: tuple[HandoffChange, ...]
    file_references: tuple[HandoffFileReference, ...]
    context: ContextReference | None
    tool_results: tuple[HandoffToolResult, ...]
    unresolved_issues: tuple[HandoffIssue, ...]
    next_steps: tuple[str, ...]
    warnings: tuple[str, ...]
    redaction_categories: tuple[str, ...]
    project_memory_fingerprint: str
    fingerprint: str
    metrics: HandoffMetrics


@dataclass(frozen=True, slots=True)
class HandoffView:
    handoff: SessionHandoff
    stale_reasons: tuple[str, ...]

    @property
    def is_stale(self) -> bool:
        return bool(self.stale_reasons)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(handoff: SessionHandoff) -> str:
    semantic = {
        "repository_root": handoff.repository_root, "branch": handoff.branch, "head": handoff.head,
        "task": handoff.task, "changes": [asdict(v) for v in handoff.changes],
        "file_references": [asdict(v) for v in handoff.file_references],
        "context": asdict(handoff.context) if handoff.context else None,
        "tool_results": [asdict(v) for v in handoff.tool_results],
        "unresolved_issues": [{"text": v.text, "provenance": v.provenance} for v in handoff.unresolved_issues],
        "next_steps": handoff.next_steps, "redaction_categories": handoff.redaction_categories,
        "project_memory_fingerprint": handoff.project_memory_fingerprint,
    }
    return hashlib.sha256(_canonical(semantic).encode("utf-8")).hexdigest()


def context_reference(pack: ContextPack) -> ContextReference:
    return ContextReference(pack.fingerprint, pack.mode.value, pack.query.task, pack.selected_files,
                            pack.metrics.estimated_selected_tokens, pack.warnings)


def context_reference_from_json(data: dict[str, Any], config: GatewayConfig) -> ContextReference:
    try:
        if Path(data["repository"]["root"]).resolve() != config.repository_root:
            raise ValueError("Context Pack belongs to a different repository")
        selected = tuple(data["selected_files"])
        if not all(isinstance(p, str) and config.relative_path(p) == p for p in selected):
            raise ValueError("invalid Context Pack paths")
        return ContextReference(data["fingerprint"], data["mode"], data["query"]["task"], selected,
                                data["metrics"]["estimated_selected_tokens"], tuple(data["warnings"]))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid Context Pack metadata: {exc}") from exc


def _decode_handoff(data: dict[str, Any]) -> SessionHandoff:
    try:
        context = ContextReference(**{**data["context"], "selected_paths": tuple(data["context"]["selected_paths"]),
                                      "warnings": tuple(data["context"]["warnings"])}) if data["context"] else None
        handoff = SessionHandoff(
            data["schema_version"], data["repository_root"], data["repository_name"], data["branch"], data["head"],
            data["task"], data["created_at"],
            tuple(HandoffChange(**{**v, "affected_symbols": tuple(v["affected_symbols"])}) for v in data["changes"]),
            tuple(HandoffFileReference(**v) for v in data["file_references"]),
            context,
            tuple(HandoffToolResult(**{**v, "warnings": tuple(v["warnings"]),
                                       "redaction_categories": tuple(v["redaction_categories"])}) for v in data["tool_results"]),
            tuple(HandoffIssue(**v) for v in data["unresolved_issues"]), tuple(data["next_steps"]),
            tuple(data["warnings"]), tuple(data["redaction_categories"]), data["project_memory_fingerprint"],
            data["fingerprint"], HandoffMetrics(**data["metrics"]),
        )
        if handoff.fingerprint != _fingerprint(handoff):
            raise ValueError("fingerprint mismatch")
        return handoff
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise StateStoreError(f"corrupt handoff; preserved existing data: {exc}") from exc


class HandoffService:
    def __init__(self, config: GatewayConfig, *, estimator: TokenEstimator | None = None,
                 redactor: SecretRedactor | None = None, soft_limit_tokens: int = 4000) -> None:
        if soft_limit_tokens < 1:
            raise ValueError("soft limit must be positive")
        self.config = config
        self.estimator = estimator or HeuristicTokenEstimator()
        self.redactor = redactor or SecretRedactor()
        self.soft_limit_tokens = soft_limit_tokens
        self.memory = ProjectMemoryService(config, estimator=self.estimator, redactor=self.redactor)
        self.pointer = AtomicJsonStore(config.repository_root, config.cache_dir / "latest_handoff.json",
                                       HANDOFF_SCHEMA_VERSION, "latest handoff pointer")

    def _record_store(self, identifier: str) -> AtomicJsonStore:
        if not _ID.fullmatch(identifier):
            raise ValueError("handoff ID must be a 64-character hex fingerprint")
        return AtomicJsonStore(self.config.repository_root, self.config.cache_dir / "handoffs" / f"{identifier}.json",
                               HANDOFF_SCHEMA_VERSION, "handoff")

    def _clean(self, text: str, categories: set[str]) -> str:
        result = self.redactor.redact(text)
        categories.update(result.categories)
        return result.text

    def _metrics(self, handoff: SessionHandoff, baseline: int) -> SessionHandoff:
        for _ in range(8):
            serialized = _canonical(asdict(handoff))
            tokens = self.estimator.estimate(serialized)
            avoided = baseline - tokens
            metrics = HandoffMetrics(len(serialized.encode("utf-8")), tokens, baseline, avoided,
                                     round(100 * avoided / baseline, 2) if baseline else 0.0)
            warnings = tuple(sorted(set(handoff.warnings) | ({"HANDOFF_SOFT_LIMIT_EXCEEDED"} if tokens > self.soft_limit_tokens else set())))
            updated = replace(handoff, metrics=metrics, warnings=warnings)
            if updated == handoff:
                break
            handoff = updated
        return handoff

    def create(self, task: str, *, context: ContextPack | ContextReference | None = None,
               tool_results: tuple[CompactionResult, ...] = (), issues: tuple[str, ...] = (),
               next_steps: tuple[str, ...] = ()) -> SessionHandoff:
        categories: set[str] = set()
        task = self._clean(task.strip(), categories)
        if not task:
            raise ValueError("explicit task text is required")
        memory = self.memory.refresh()
        index = RepositoryIndexer(self.config).index()
        diff = GitDiffReader(self.config).read(index)
        cache_prefix = self.config.cache_dir.relative_to(self.config.repository_root).as_posix() + "/"
        changes = tuple(HandoffChange(f.path, f.status, f.old_path, f.affected_symbols,
                                      index.get_file(f.path).sha256 if index.get_file(f.path) else None)
                        for f in diff.files if not f.path.startswith(cache_prefix))
        if isinstance(context, ContextPack) and Path(context.repository.root).resolve() != self.config.repository_root:
            raise ValueError("Context Pack belongs to a different repository")
        reference = context_reference(context) if isinstance(context, ContextPack) else context
        if reference:
            if not isinstance(reference, ContextReference):
                raise TypeError("context must be a Context Pack or ContextReference")
            reference = replace(reference, query=self._clean(reference.query, categories),
                                warnings=tuple(self._clean(w, categories) for w in reference.warnings))
            for path in reference.selected_paths:
                if self.config.relative_path(path) != path:
                    raise ValueError(f"unsafe Context Pack path: {path}")
        summaries = []
        for result in tool_results:
            cleaned = self._clean(result.compacted_text, categories)
            summaries.append(HandoffToolResult(result.output_type, cleaned, result.estimated_original_tokens,
                                               self.estimator.estimate(cleaned),
                                               hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
                                               tuple(self._clean(w, categories) for w in result.warnings),
                                               result.redaction_categories))
            categories.update(result.redaction_categories)
        unresolved = [HandoffIssue(n.text, "USER", n.id) for n in memory.issues if not n.resolved]
        unresolved.extend(HandoffIssue(self._clean(issue, categories), "USER") for issue in issues)
        steps = tuple(self._clean(step, categories) for step in next_steps)
        paths = {f.path for f in changes if f.source_hash}
        if reference:
            paths.update(reference.selected_paths)
        file_references = tuple(HandoffFileReference(path, index.get_file(path).sha256 if index.get_file(path) else None)
                                for path in sorted(paths))
        reader = SourceReader(self.config, index)
        baseline = 0
        for path in sorted(paths):
            try:
                baseline += self.estimator.estimate(reader.read(path).text)
            except (StaleSourceError, UnsafeSourceError, UnicodeError, OSError):
                pass
        baseline += sum(result.estimated_original_tokens for result in tool_results)
        handoff = SessionHandoff(HANDOFF_SCHEMA_VERSION, str(self.config.repository_root), index.identity.name,
                                 index.identity.branch, index.identity.head, task, datetime.now(timezone.utc).isoformat(),
                                 changes, file_references, reference, tuple(summaries), tuple(unresolved), steps, (),
                                 tuple(sorted(categories)), memory.fingerprint, "", HandoffMetrics(0, 0, baseline, 0, 0.0))
        handoff = replace(handoff, fingerprint=_fingerprint(handoff))
        handoff = self._metrics(handoff, baseline)
        existing = self._record_store(handoff.fingerprint).load()
        if existing is not None:
            _decode_handoff(existing)
        else:
            self._record_store(handoff.fingerprint).save(asdict(handoff))
        self.pointer.save({"schema_version": HANDOFF_SCHEMA_VERSION,
                           "repository_root": str(self.config.repository_root), "handoff_id": handoff.fingerprint})
        return handoff

    def load(self, identifier: str) -> SessionHandoff:
        if not _ID.fullmatch(identifier):
            if not re.fullmatch(r"[0-9a-f]{8,63}", identifier):
                raise ValueError("handoff ID must be a hex fingerprint or unique prefix")
            directory = self.config.cache_dir / "handoffs"
            if directory.is_symlink():
                raise StateStoreError("unsafe symlink in handoff directory")
            matches = [path.stem for path in directory.iterdir() if path.is_file() and
                       path.suffix == ".json" and _ID.fullmatch(path.stem) and path.stem.startswith(identifier)] if directory.exists() else []
            if len(matches) != 1:
                raise ValueError(f"unknown or ambiguous handoff prefix: {identifier}")
            identifier = matches[0]
        data = self._record_store(identifier).load()
        if data is None:
            raise ValueError(f"unknown handoff: {identifier}")
        handoff = _decode_handoff(data)
        if handoff.fingerprint != identifier:
            raise StateStoreError("handoff ID mismatch; preserved existing data")
        return handoff

    def latest(self) -> SessionHandoff:
        data = self.pointer.load()
        if data is None:
            raise ValueError("no latest handoff")
        identifier = data.get("handoff_id")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise StateStoreError("invalid latest handoff pointer; preserved existing data")
        return self.load(identifier)

    def list(self) -> tuple[SessionHandoff, ...]:
        directory = self.config.cache_dir / "handoffs"
        if directory.is_symlink():
            raise StateStoreError("unsafe symlink in handoff directory")
        if not directory.exists():
            return ()
        records = [self.load(path.stem) for path in directory.iterdir()
                   if path.is_file() and _ID.fullmatch(path.stem) and path.suffix == ".json"]
        return tuple(sorted(records, key=lambda h: (h.created_at, h.fingerprint), reverse=True))

    def view(self, handoff: SessionHandoff) -> HandoffView:
        current = self.memory.refresh()
        reasons: set[str] = set()
        if handoff.head != current.head:
            reasons.add("HEAD_CHANGED")
        if handoff.branch != current.branch:
            reasons.add("BRANCH_CHANGED")
        if handoff.project_memory_fingerprint != current.fingerprint:
            reasons.add("PROJECT_MEMORY_CHANGED")
        index = RepositoryIndexer(self.config).index()
        for reference in handoff.file_references:
            path, digest = reference.path, reference.source_hash
            file = index.get_file(path)
            if file is None:
                reasons.add("FILE_REMOVED")
            elif digest is not None and file.sha256 != digest:
                reasons.add("FILE_CHANGED")
        return HandoffView(handoff, tuple(sorted(reasons)))


def handoff_view_dict(view: HandoffView) -> dict[str, Any]:
    data = asdict(view.handoff)
    data["stale_reasons"] = view.stale_reasons
    data["status"] = "stale" if view.is_stale else "current"
    data["reconstruction_baseline"] = "full current readable changed/selected files (deduplicated paths) plus raw supplied tool output; heuristic tokens, not provider billing"
    return data


def format_handoff(view: HandoffView) -> str:
    h = view.handoff
    lines = ["MIDDLE_MAN SESSION HANDOFF", "", "TASK", h.task, "", "REPOSITORY", h.repository_name,
             f"branch: {h.branch or '(none)'}", f"HEAD: {h.head or '(none)'}", "", "CHANGED"]
    lines.extend(f"- {c.path} [{c.status}]" + (f" affected: {', '.join(c.affected_symbols)}" if c.affected_symbols else "") for c in h.changes)
    if not h.changes:
        lines.append("None")
    if h.tool_results:
        lines.extend(["", "TOOL RESULTS"])
        for result in h.tool_results:
            lines.extend([f"{result.output_type}:", result.compacted_text.rstrip()])
    if h.context:
        lines.extend(["", "CONTEXT", f"fingerprint: {h.context.fingerprint}",
                      f"mode: {h.context.mode}", f"selected files: {len(h.context.selected_paths)}",
                      f"estimated selected tokens: {h.context.estimated_selected_tokens}"])
    lines.extend(["", "UNRESOLVED"])
    lines.extend(f"- {issue.text} ({issue.provenance.lower()} supplied)" for issue in h.unresolved_issues)
    if not h.unresolved_issues:
        lines.append("None")
    lines.extend(["", "NEXT"])
    lines.extend(f"- {step}" for step in h.next_steps)
    if not h.next_steps:
        lines.append("None supplied")
    lines.extend(["", "STATUS", "Stale: " + ", ".join(view.stale_reasons) if view.is_stale else "Current",
                  "", "ESTIMATED CONTEXT (not provider billing)",
                  f"Reconstruction baseline: {h.metrics.estimated_reconstruction_tokens} tokens",
                  f"Handoff payload: {h.metrics.estimated_handoff_tokens} tokens ({h.metrics.handoff_bytes} bytes)",
                  f"Difference: {h.metrics.estimated_tokens_avoided} tokens ({h.metrics.estimated_reduction_percent:.1f}%)"])
    if h.warnings:
        lines.extend(["", "WARNINGS", *(f"- {w}" for w in h.warnings)])
    return "\n".join(lines) + "\n"
