from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EventType(StrEnum):
    REQUEST_ADMITTED = "request_admitted"
    REQUEST_COMPLETED = "request_completed"
    PREFILL_EXECUTED = "prefill_executed"
    DECODE_EXECUTED = "decode_executed"
    RECOMPUTE_EXECUTED = "recompute_executed"
    KV_ALLOCATED = "kv_allocated"
    KV_RELEASED = "kv_released"
    REQUEST_PREEMPTED = "request_preempted"
    PREFIX_CACHE_HIT = "prefix_cache_hit"
    PREFIX_CACHE_MISS = "prefix_cache_miss"


@dataclass(frozen=True)
class SimulationEvent:
    kind: EventType
    time_ms: float
    request_id: str
    tokens: int = 0
    blocks: int = 0
    related_request_id: str | None = None
