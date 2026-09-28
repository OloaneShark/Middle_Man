from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RequestState(StrEnum):
    QUEUED = "queued"
    PREFILLING = "prefilling"
    DECODING = "decoding"
    PREEMPTED = "preempted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class InferenceRequest:
    request_id: str
    arrival_time_ms: float
    prompt_tokens: int
    max_output_tokens: int
    shared_prefix_tokens: int = 0
    prefix_key: str | None = None
    prompt_processed: int = 0
    output_generated: int = 0
    state: RequestState = RequestState.QUEUED
    allocated_blocks: list[int] = field(default_factory=list)
    shared_blocks: list[int] = field(default_factory=list)
    first_token_time_ms: float | None = None
    completion_time_ms: float | None = None
    preemption_count: int = 0
    recomputed_tokens: int = 0
    recompute_pending_tokens: int = 0
    recompute_rebuilt_tokens: int = 0
    prefix_cache_hit: bool = False
    prefix_reused_tokens: int = 0
    output_token_times_ms: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.prompt_tokens < 0:
            raise ValueError("prompt_tokens must be non-negative")
        if self.max_output_tokens < 0:
            raise ValueError("max_output_tokens must be non-negative")
        if self.shared_prefix_tokens < 0:
            raise ValueError("shared_prefix_tokens must be non-negative")
        if self.shared_prefix_tokens > self.prompt_tokens:
            raise ValueError("shared_prefix_tokens cannot exceed prompt_tokens")

    @property
    def remaining_prompt_tokens(self) -> int:
        return max(0, self.prompt_tokens - self.prompt_processed)

    @property
    def remaining_output_tokens(self) -> int:
        return max(0, self.max_output_tokens - self.output_generated)

    @property
    def prefill_complete(self) -> bool:
        return self.remaining_prompt_tokens == 0

    @property
    def generation_complete(self) -> bool:
        return self.remaining_output_tokens == 0

    @property
    def current_context_tokens(self) -> int:
        return self.prompt_processed + self.output_generated

    @property
    def total_allocated_block_count(self) -> int:
        return len(self.allocated_blocks) + len(self.shared_blocks)

    def mark_admitted(self, now_ms: float) -> None:
        if self.state in {RequestState.QUEUED, RequestState.PREEMPTED}:
            if self.recompute_pending_tokens:
                self.state = RequestState.PREEMPTED
            elif not self.prefill_complete:
                self.state = RequestState.PREFILLING
            elif self.generation_complete:
                self._complete(now_ms)
            else:
                self.state = RequestState.DECODING

    def reuse_prefix(self, tokens: int) -> None:
        if tokens <= 0 or tokens > self.shared_prefix_tokens:
            raise ValueError("invalid reusable prefix length")
        if self.state == RequestState.PREEMPTED:
            self.prompt_processed = max(self.prompt_processed, tokens)
            reused = min(tokens, self.current_context_tokens)
            self.recompute_rebuilt_tokens = reused
            self.recompute_pending_tokens = self.current_context_tokens - reused
        elif self.state == RequestState.QUEUED:
            if self.prompt_processed:
                raise ValueError("cannot reuse prefix after private prefill")
            self.prompt_processed = tokens
        else:
            raise ValueError(f"cannot reuse prefix in state {self.state}")
        self.prefix_cache_hit = True
        self.prefix_reused_tokens += tokens

    def apply_prefill(self, tokens: int, now_ms: float) -> None:
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        if self.state not in {RequestState.PREFILLING, RequestState.PREEMPTED, RequestState.QUEUED}:
            raise ValueError(f"cannot prefill request in state {self.state}")
        if tokens > self.remaining_prompt_tokens:
            raise ValueError("prefill tokens cannot exceed remaining prompt tokens")
        self.prompt_processed += tokens
        if not self.prefill_complete:
            self.state = RequestState.PREFILLING
        elif self.generation_complete:
            self._complete(now_ms)
        else:
            self.state = RequestState.DECODING

    def apply_decode(self, tokens: int, now_ms: float) -> None:
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        if not self.prefill_complete:
            raise ValueError("cannot decode before prefill completes")
        if self.state != RequestState.DECODING:
            raise ValueError(f"cannot decode request in state {self.state}")
        if tokens > self.remaining_output_tokens:
            raise ValueError("decode tokens cannot exceed remaining output tokens")
        if tokens and self.first_token_time_ms is None:
            self.first_token_time_ms = now_ms
        self.output_generated += tokens
        self.output_token_times_ms.extend([now_ms] * tokens)
        if self.generation_complete:
            self._complete(now_ms)

    def mark_preempted(self) -> None:
        if self.state in {RequestState.COMPLETED, RequestState.CANCELLED, RequestState.FAILED}:
            raise ValueError("cannot preempt terminal request")
        self.preemption_count += 1
        self.recompute_pending_tokens = self.current_context_tokens
        self.recompute_rebuilt_tokens = 0
        self.state = RequestState.PREEMPTED
        self.allocated_blocks.clear()
        self.shared_blocks.clear()

    def apply_recompute(self, tokens: int, now_ms: float) -> None:
        if self.state != RequestState.PREEMPTED:
            raise ValueError("request is not rebuilding KV context")
        if tokens <= 0 or tokens > self.recompute_pending_tokens:
            raise ValueError("recompute tokens exceed remaining context")
        self.recompute_pending_tokens -= tokens
        self.recompute_rebuilt_tokens += tokens
        self.recomputed_tokens += tokens
        if not self.recompute_pending_tokens:
            self.mark_admitted(now_ms)

    def _complete(self, now_ms: float) -> None:
        self.state = RequestState.COMPLETED
        self.completion_time_ms = now_ms

    def cancel(self) -> None:
        self.state = RequestState.CANCELLED