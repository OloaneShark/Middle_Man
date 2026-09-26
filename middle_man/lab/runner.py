from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from middle_man.lab.config import RunnerCostConfig
from middle_man.lab.request import InferenceRequest
from middle_man.lab.work import SchedulePlan, WorkKind


@dataclass(frozen=True)
class ExecutionResult:
    elapsed_ms: float
    prompt_tokens: int
    output_tokens: int


class ModelRunner(Protocol):
    def execute(self, plan: SchedulePlan, requests: dict[str, InferenceRequest]) -> ExecutionResult: ...


class SimulatedModelRunner:
    def __init__(self, costs: RunnerCostConfig | None = None) -> None:
        self.costs = costs or RunnerCostConfig()

    def execute(self, plan: SchedulePlan, requests: dict[str, InferenceRequest]) -> ExecutionResult:
        prefill_tokens = 0
        decode_tokens = 0
        context_cost = 0.0
        for item in plan.items:
            request = requests[item.request_id]
            context_cost += request.current_context_tokens * self.costs.context_scale_ms
            if item.kind == WorkKind.PREFILL:
                prefill_tokens += item.tokens
            else:
                decode_tokens += item.tokens

        elapsed = 0.0
        if prefill_tokens:
            elapsed += self.costs.prefill_base_ms + prefill_tokens * self.costs.prefill_token_ms
        if decode_tokens:
            elapsed += self.costs.decode_base_ms + decode_tokens * self.costs.decode_token_ms

        batch_size = max(1, len(plan.items))
        discount = min(0.7, (batch_size - 1) * self.costs.batch_discount)
        elapsed = elapsed * (1 - discount) + context_cost
        return ExecutionResult(elapsed_ms=max(0.0, elapsed), prompt_tokens=prefill_tokens, output_tokens=decode_tokens)


class TorchModelRunner:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("TorchModelRunner is an optional future integration and is not installed by default")
