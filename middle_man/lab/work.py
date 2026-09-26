from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkKind(StrEnum):
    PREFILL = "prefill"
    DECODE = "decode"


@dataclass(frozen=True)
class WorkItem:
    request_id: str
    kind: WorkKind
    tokens: int

    def __post_init__(self) -> None:
        if self.tokens <= 0:
            raise ValueError("work item tokens must be positive")


@dataclass(frozen=True)
class SchedulePlan:
    items: tuple[WorkItem, ...]
    token_budget: int

    @property
    def scheduled_tokens(self) -> int:
        return sum(item.tokens for item in self.items)

    def validate(self) -> None:
        if self.scheduled_tokens > self.token_budget:
            raise ValueError("schedule exceeds token budget")
