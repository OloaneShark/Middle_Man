from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SchedulerKind(StrEnum):
    DECODE_PRIORITY = "decode-priority"
    BALANCED = "balanced"


@dataclass(frozen=True)
class RunnerCostConfig:
    prefill_base_ms: float = 1.0
    prefill_token_ms: float = 0.08
    decode_base_ms: float = 0.6
    decode_token_ms: float = 0.22
    context_scale_ms: float = 0.002
    batch_discount: float = 0.08

    def validate(self) -> None:
        values = self.__dict__.items()
        for name, value in values:
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.batch_discount >= 1:
            raise ValueError("batch_discount must be less than 1")


@dataclass(frozen=True)
class LabConfig:
    token_budget: int = 64
    max_active_sequences: int = 16
    kv_blocks: int = 128
    tokens_per_block: int = 16
    scheduler: SchedulerKind = SchedulerKind.DECODE_PRIORITY
    prefix_cache_enabled: bool = True
    preemption_enabled: bool = True
    random_seed: int = 7
    debug: bool = False
    runner_costs: RunnerCostConfig = RunnerCostConfig()

    def validate(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.max_active_sequences <= 0:
            raise ValueError("max_active_sequences must be positive")
        if self.kv_blocks <= 0:
            raise ValueError("kv_blocks must be positive")
        if self.tokens_per_block <= 0:
            raise ValueError("tokens_per_block must be positive")
        self.runner_costs.validate()
