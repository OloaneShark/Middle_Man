"""Claude-specific observation models; absent provider fields stay absent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClaudeUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ToolAction:
    name: str
    kind: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ClaudeRunEvents:
    session_id: str | None
    result_text: str | None
    status: str
    duration_ms: int | None
    duration_api_ms: int | None
    num_turns: int | None
    total_cost_usd: float | None
    usage: ClaudeUsage
    observed_model: str | None
    actions: tuple[ToolAction, ...]
    unique_files: tuple[str, ...]
    rereads: int
    warnings: tuple[str, ...]

    @property
    def tool_calls(self) -> int:
        return len(self.actions)

    @property
    def file_reads(self) -> int:
        return sum(action.kind == "read" for action in self.actions)

    @property
    def searches(self) -> int:
        return sum(action.kind == "search" for action in self.actions)

    @property
    def listings(self) -> int:
        return sum(action.kind == "listing" for action in self.actions)

    @property
    def edits(self) -> int:
        return sum(action.kind == "edit" for action in self.actions)

    @property
    def writes(self) -> int:
        return sum(action.kind == "write" for action in self.actions)

    @property
    def bash_commands(self) -> int:
        return sum(action.kind == "bash" for action in self.actions)
