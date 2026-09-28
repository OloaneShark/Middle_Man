"""Immutable source-context selection records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from middle_man.gateway.models import RepositoryIdentity
from middle_man.gateway.relevance import ContextQuery, RelevanceCandidate

if TYPE_CHECKING:
    from middle_man.gateway.compact import CompactionResult


class ContextMode(str, Enum):
    SAFE = "safe"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True, slots=True)
class SourceExcerpt:
    path: str
    start_line: int
    end_line: int
    text: str
    kind: str
    symbols: tuple[str, ...]
    reasons: tuple[str, ...]
    relevance_score: float
    complete_file: bool
    truncated: bool
    content_hash: str


@dataclass(frozen=True, slots=True)
class ChangedContext:
    path: str
    status: str
    old_path: str | None
    affected_symbols: tuple[str, ...]
    hunk_ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class ContextMetrics:
    repository_files: int
    candidates_considered: int
    files_selected: int
    complete_files: int
    excerpts_selected: int
    source_lines_selected: int
    raw_candidate_bytes: int
    selected_bytes: int
    estimated_raw_candidate_tokens: int
    estimated_selected_tokens: int
    estimated_tokens_avoided: int
    estimated_reduction_percent: float
    duplicate_bytes_avoided: int


@dataclass(frozen=True, slots=True)
class ContextPack:
    fingerprint: str
    query: ContextQuery
    repository: RepositoryIdentity
    mode: ContextMode
    max_context_tokens: int
    generation: int
    candidates: tuple[RelevanceCandidate, ...]
    excerpts: tuple[SourceExcerpt, ...]
    related_tests: tuple[str, ...]
    changed_files: tuple[ChangedContext, ...]
    metrics: ContextMetrics
    warnings: tuple[str, ...]
    redaction_categories: tuple[str, ...]
    tool_outputs: tuple[CompactionResult, ...] = ()

    @property
    def selected_files(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.path for item in self.excerpts))

    @property
    def selected_symbols(self) -> tuple[str, ...]:
        return tuple(sorted({name for item in self.excerpts for name in item.symbols}))


@dataclass(frozen=True, slots=True)
class ExpansionRequest:
    kind: str
    target: str | None = None
    context_lines: int = 3

    def __post_init__(self) -> None:
        if self.kind not in {"file", "symbol", "full_file", "related_imports", "related_tests", "next_candidates", "surrounding_lines"}:
            raise ValueError(f"unknown expansion kind: {self.kind}")
        if self.context_lines < 0:
            raise ValueError("context_lines must be nonnegative")
