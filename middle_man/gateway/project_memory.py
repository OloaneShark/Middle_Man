"""Factual, local project state with explicit user-authored notes."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.git_diff import GitDiffReader
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.models import RepositoryIndex
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.source import SourceReader, StaleSourceError, UnsafeSourceError
from middle_man.gateway.state_store import AtomicJsonStore, StateStoreError
from middle_man.gateway.tokens import HeuristicTokenEstimator, TokenEstimator

PROJECT_MEMORY_SCHEMA_VERSION = 1


class FactProvenance(str, Enum):
    INDEX = "INDEX"
    GIT = "GIT"
    DIFF = "DIFF"
    USER = "USER"
    HANDOFF = "HANDOFF"
    TOOL_RESULT = "TOOL_RESULT"


@dataclass(frozen=True, slots=True)
class MemoryFact:
    category: str
    value: str
    provenance: FactProvenance
    source_path: str | None = None
    source_hash: str | None = None
    user_supplied: bool = False


@dataclass(frozen=True, slots=True)
class MemoryComponent:
    path: str
    symbols: tuple[str, ...]
    source_hash: str | None
    provenance: FactProvenance = FactProvenance.INDEX


@dataclass(frozen=True, slots=True)
class MemoryChange:
    path: str
    status: str
    old_path: str | None
    affected_symbols: tuple[str, ...]
    source_hash: str | None
    provenance: FactProvenance = FactProvenance.DIFF


@dataclass(frozen=True, slots=True)
class MemoryNote:
    id: str
    text: str
    category: str | None
    created_at: str
    provenance: FactProvenance = FactProvenance.USER
    resolved: bool = False
    resolved_at: str | None = None
    supersedes: str | None = None
    redaction_categories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryMetrics:
    serialized_bytes: int
    estimated_tokens: int
    component_count: int
    decision_count: int
    issue_count: int


@dataclass(frozen=True, slots=True)
class ProjectMemory:
    schema_version: int
    repository_root: str
    repository_name: str
    branch: str | None
    head: str | None
    facts: tuple[MemoryFact, ...]
    components: tuple[MemoryComponent, ...]
    changes: tuple[MemoryChange, ...]
    decisions: tuple[MemoryNote, ...]
    issues: tuple[MemoryNote, ...]
    updated_at: str
    fingerprint: str
    metrics: MemoryMetrics


@dataclass(frozen=True, slots=True)
class MemorySettings:
    max_components: int = 20
    max_symbols: int = 40

    def __post_init__(self) -> None:
        if self.max_components < 1 or self.max_symbols < 0:
            raise ValueError("invalid Project Memory limits")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(memory: ProjectMemory) -> str:
    semantic = {
        "repository_root": memory.repository_root, "repository_name": memory.repository_name,
        "branch": memory.branch, "head": memory.head,
        "facts": [asdict(item) for item in memory.facts],
        "components": [asdict(item) for item in memory.components],
        "changes": [asdict(item) for item in memory.changes],
        "decisions": [{"text": n.text, "category": n.category, "supersedes": n.supersedes,
                       "redaction_categories": n.redaction_categories} for n in memory.decisions],
        "issues": [{"text": n.text, "category": n.category, "resolved": n.resolved,
                    "redaction_categories": n.redaction_categories} for n in memory.issues],
    }
    return hashlib.sha256(_canonical(semantic).encode("utf-8")).hexdigest()


def _technology_facts(index: RepositoryIndex, config: GatewayConfig) -> tuple[MemoryFact, ...]:
    files = {item.path: item for item in index.files}
    evidence: dict[str, tuple[str, str | None]] = {}

    def add(name: str, path: str) -> None:
        evidence.setdefault(name, (path, files[path].sha256))

    def prefer(name: str, path: str) -> None:
        evidence[name] = (path, files[path].sha256)

    def declares(values: list[object], name: str) -> bool:
        return any(re.match(rf"(?i)^{re.escape(name)}(?:\[|[<>=!~;\s]|$)", str(value).strip()) for value in values)

    python = next((f for f in index.files if f.extension == ".py"), None)
    if python:
        add("Python", python.path)
    for path in sorted(files):
        name = Path(path).name.lower()
        if name in {"dockerfile", "compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"}:
            add("Docker", path)
        if path.endswith((".ts", ".tsx")):
            add("TypeScript", path)
    for file in index.files:
        for imported in file.imports:
            root = imported.module.split(".", 1)[0]
            for module, technology in (("pytest", "pytest"), ("flask", "Flask"), ("fastapi", "FastAPI")):
                if root == module:
                    add(technology, file.path)

    reader = SourceReader(config, index)
    if "pyproject.toml" in files:
        try:
            project = tomllib.loads(reader.read("pyproject.toml").text)
            build = project.get("build-system", {})
            dependencies = project.get("project", {}).get("dependencies", [])
            optional = project.get("project", {}).get("optional-dependencies", {})
            groups = project.get("dependency-groups", {})
            values = [*dependencies, *(v for group in optional.values() if isinstance(group, list) for v in group),
                      *(v for group in groups.values() if isinstance(group, list) for v in group)]
            if "pytest" in project.get("tool", {}) or declares(values, "pytest"):
                prefer("pytest", "pyproject.toml")
            for technology, needle in (("Flask", "flask"), ("FastAPI", "fastapi")):
                if declares(values, needle):
                    prefer(technology, "pyproject.toml")
            if build or project.get("project"):
                prefer("Python", "pyproject.toml")
        except (OSError, ValueError, TypeError, KeyError, AttributeError, StaleSourceError, UnsafeSourceError):
            pass
    if "requirements.txt" in files:
        try:
            dependencies = reader.read("requirements.txt").text.lower().splitlines()
            for technology, needle in (("pytest", "pytest"), ("Flask", "flask"), ("FastAPI", "fastapi")):
                if declares(dependencies, needle):
                    prefer(technology, "requirements.txt")
        except (OSError, UnicodeError, StaleSourceError, UnsafeSourceError):
            pass
    if "package.json" in files:
        try:
            package = json.loads(reader.read("package.json").text)
            dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
            if "react" in dependencies:
                prefer("React", "package.json")
            if "next" in dependencies:
                prefer("Next.js", "package.json")
            if "typescript" in dependencies:
                prefer("TypeScript", "package.json")
        except (OSError, ValueError, TypeError, AttributeError, StaleSourceError, UnsafeSourceError):
            pass
    return tuple(MemoryFact("technology", name, FactProvenance.INDEX, path, digest)
                 for name, (path, digest) in sorted(evidence.items()))


def _components(index: RepositoryIndex, settings: MemorySettings) -> tuple[MemoryComponent, ...]:
    connections = Counter(r.target for r in index.relationships if r.kind == "IMPORTS")
    result = []
    for file in index.files:
        if file.is_test or not file.is_text or file.language in {"Markdown", "JSON", "TOML", "YAML"}:
            continue
        classes = tuple(s.qualified_name for s in file.symbols if s.kind == "class" and s.parent is None and not s.name.startswith("_"))
        functions = tuple(s.qualified_name for s in file.symbols if s.kind == "function" and s.parent is None and not s.name.startswith("_"))
        public = classes + functions
        role = 3 if Path(file.path).stem in {"main", "app", "config", "engine", "indexer"} else 0
        score = connections[file.path] * 3 + len(classes) * 2 + min(len(public), 3) + role
        if score:
            result.append((-score, file.path, file, public))
    result.sort()
    ranked = result[:settings.max_components]
    chosen: dict[str, list[str]] = {path: [] for _, path, _, _ in ranked}
    remaining = settings.max_symbols
    for rank in range(max((len(symbols) for _, _, _, symbols in ranked), default=0)):
        for _, path, _, symbols in ranked:
            if remaining and rank < len(symbols):
                chosen[path].append(symbols[rank])
                remaining -= 1
    return tuple(MemoryComponent(file.path, tuple(chosen[path]), file.sha256)
                 for _, path, file, _ in ranked)


def _decode_note(value: Any) -> MemoryNote:
    if not isinstance(value, dict):
        raise ValueError("invalid note")
    note = MemoryNote(**{**value, "provenance": FactProvenance(value["provenance"]),
                         "redaction_categories": tuple(value["redaction_categories"])})
    if not isinstance(note.id, str) or not isinstance(note.text, str) or not isinstance(note.resolved, bool) or note.provenance != FactProvenance.USER:
        raise ValueError("invalid user note")
    return note


def _decode_memory(data: dict[str, Any]) -> ProjectMemory:
    try:
        memory = ProjectMemory(
            schema_version=data["schema_version"], repository_root=data["repository_root"],
            repository_name=data["repository_name"], branch=data["branch"], head=data["head"],
            facts=tuple(MemoryFact(**{**v, "provenance": FactProvenance(v["provenance"])}) for v in data["facts"]),
            components=tuple(MemoryComponent(**{**v, "symbols": tuple(v["symbols"]),
                                                   "provenance": FactProvenance(v["provenance"])}) for v in data["components"]),
            changes=tuple(MemoryChange(**{**v, "affected_symbols": tuple(v["affected_symbols"]),
                                               "provenance": FactProvenance(v["provenance"])}) for v in data["changes"]),
            decisions=tuple(_decode_note(v) for v in data["decisions"]),
            issues=tuple(_decode_note(v) for v in data["issues"]),
            updated_at=data["updated_at"], fingerprint=data["fingerprint"],
            metrics=MemoryMetrics(**data["metrics"]),
        )
        if memory.fingerprint != _fingerprint(memory):
            raise ValueError("fingerprint mismatch")
        return memory
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise StateStoreError(f"corrupt Project Memory; preserved existing data: {exc}") from exc


class ProjectMemoryService:
    def __init__(self, config: GatewayConfig, *, settings: MemorySettings | None = None,
                 estimator: TokenEstimator | None = None, redactor: SecretRedactor | None = None) -> None:
        self.config = config
        self.settings = settings or MemorySettings()
        self.estimator = estimator or HeuristicTokenEstimator()
        self.redactor = redactor or SecretRedactor()
        self.store = AtomicJsonStore(config.repository_root, config.cache_dir / "project_memory.json",
                                     PROJECT_MEMORY_SCHEMA_VERSION, "Project Memory")

    def load(self) -> ProjectMemory | None:
        data = self.store.load()
        return _decode_memory(data) if data is not None else None

    def _save(self, memory: ProjectMemory) -> ProjectMemory:
        memory = replace(memory, fingerprint=_fingerprint(memory))
        for _ in range(8):
            data = asdict(memory)
            serialized = _canonical(data)
            metrics = MemoryMetrics(len(serialized.encode("utf-8")), self.estimator.estimate(serialized),
                                    len(memory.components), len(memory.decisions), len(memory.issues))
            if metrics == memory.metrics:
                break
            memory = replace(memory, metrics=metrics)
        self.store.save(asdict(memory))
        return memory

    def refresh(self) -> ProjectMemory:
        previous = self.load()
        index = RepositoryIndexer(self.config).index()
        diff = GitDiffReader(self.config).read(index)
        facts = list(_technology_facts(index, self.config))
        facts.extend(MemoryFact("language_count", f"{language}: {count}", FactProvenance.INDEX)
                     for language, count in sorted(index.language_counts.items()) if count)
        facts.append(MemoryFact("branch", index.identity.branch or "(none)", FactProvenance.GIT))
        facts.append(MemoryFact("head", index.identity.head or "(none)", FactProvenance.GIT))
        cache_prefix = self.config.cache_dir.relative_to(self.config.repository_root).as_posix() + "/"
        changes = tuple(MemoryChange(f.path, f.status, f.old_path, f.affected_symbols,
                                     index.get_file(f.path).sha256 if index.get_file(f.path) else None)
                        for f in diff.files if not f.path.startswith(cache_prefix))
        memory = ProjectMemory(PROJECT_MEMORY_SCHEMA_VERSION, str(self.config.repository_root), index.identity.name,
                               index.identity.branch, index.identity.head, tuple(facts), _components(index, self.settings),
                               changes, previous.decisions if previous else (), previous.issues if previous else (),
                               datetime.now(timezone.utc).isoformat(), "", MemoryMetrics(0, 0, 0, 0, 0))
        return self._save(memory)

    def _current(self) -> ProjectMemory:
        return self.load() or self.refresh()

    def _note(self, text: str, category: str | None, supersedes: str | None = None) -> MemoryNote:
        cleaned = self.redactor.redact(text.strip())
        if not cleaned.text:
            raise ValueError("note text is required")
        cleaned_category = self.redactor.redact(category.strip()) if category else None
        categories = tuple(sorted(set(cleaned.categories + (cleaned_category.categories if cleaned_category else ()))))
        nonce = datetime.now(timezone.utc).isoformat()
        note_id = hashlib.sha256(f"{nonce}\0{cleaned.text}".encode("utf-8")).hexdigest()[:16]
        return MemoryNote(note_id, cleaned.text, cleaned_category.text if cleaned_category else None,
                          nonce, supersedes=supersedes, redaction_categories=categories)

    def add_decision(self, text: str, *, category: str | None = None, supersedes: str | None = None) -> ProjectMemory:
        memory = self._current()
        if supersedes is not None and not any(n.id == supersedes for n in memory.decisions):
            raise ValueError(f"unknown decision: {supersedes}")
        note = self._note(text, category, supersedes)
        decisions = tuple(n for n in memory.decisions if n.id != supersedes) + (note,)
        return self._save(replace(memory, decisions=decisions, updated_at=note.created_at))

    def remove_decision(self, note_id: str) -> ProjectMemory:
        memory = self._current()
        decisions = tuple(n for n in memory.decisions if n.id != note_id)
        if len(decisions) == len(memory.decisions):
            raise ValueError(f"unknown decision: {note_id}")
        return self._save(replace(memory, decisions=decisions, updated_at=datetime.now(timezone.utc).isoformat()))

    def add_issue(self, text: str, *, category: str | None = None) -> ProjectMemory:
        memory = self._current()
        note = self._note(text, category)
        return self._save(replace(memory, issues=memory.issues + (note,), updated_at=note.created_at))

    def resolve_issue(self, note_id: str) -> ProjectMemory:
        memory = self._current()
        if not any(n.id == note_id for n in memory.issues):
            raise ValueError(f"unknown issue: {note_id}")
        now = datetime.now(timezone.utc).isoformat()
        issues = tuple(replace(n, resolved=True, resolved_at=now) if n.id == note_id else n for n in memory.issues)
        return self._save(replace(memory, issues=issues, updated_at=now))


def format_project_memory(memory: ProjectMemory) -> str:
    lines = ["MIDDLE_MAN PROJECT MEMORY", "", f"Repository: {memory.repository_name}",
             f"Branch: {memory.branch or '(none)'}", f"HEAD: {memory.head or '(none)'}", "", "Technologies:"]
    lines.extend(f"- {fact.value} [{fact.source_path}]" for fact in memory.facts if fact.category == "technology")
    if lines[-1] == "Technologies:":
        lines.append("- none detected")
    lines.extend(["", "Important components:"])
    lines.extend(f"- {item.path}" + (f" ({', '.join(item.symbols)})" if item.symbols else "") for item in memory.components)
    if not memory.components:
        lines.append("- none")
    lines.extend(["", "Changed:"])
    lines.extend(f"- {item.path} [{item.status}]" + (f" affected: {', '.join(item.affected_symbols)}" if item.affected_symbols else "") for item in memory.changes)
    if not memory.changes:
        lines.append("- none")
    lines.extend(["", "Decisions:"])
    lines.extend(f"- [{n.id}] {n.text} (user supplied)" for n in memory.decisions)
    if not memory.decisions:
        lines.append("- none")
    lines.extend(["", "Known issues:"])
    lines.extend(f"- [{n.id}] {n.text} ({'resolved' if n.resolved else 'open'}, user supplied)" for n in memory.issues)
    if not memory.issues:
        lines.append("- none")
    lines.extend(["", f"Estimated memory size: {memory.metrics.estimated_tokens} tokens ({memory.metrics.serialized_bytes} bytes)",
                  f"Fingerprint: {memory.fingerprint}"])
    return "\n".join(lines) + "\n"
