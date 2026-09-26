from __future__ import annotations

from dataclasses import dataclass

from middle_man.lab.clock import Clock, VirtualClock
from middle_man.lab.config import LabConfig, SchedulerKind
from middle_man.lab.memory import AllocationError, KVBlockManager
from middle_man.lab.request import InferenceRequest, RequestState
from middle_man.lab.runner import ModelRunner, SimulatedModelRunner
from middle_man.lab.scheduler import BalancedScheduler, DecodePriorityScheduler, SchedulerPolicy
from middle_man.lab.work import SchedulePlan, WorkKind


@dataclass(frozen=True)
class EngineResult:
    requests: tuple[InferenceRequest, ...]
    iterations: int
    elapsed_ms: float
    prompt_tokens_processed: int
    output_tokens_generated: int


class SimulationEngine:
    def __init__(
        self,
        config: LabConfig | None = None,
        *,
        clock: Clock | None = None,
        memory: KVBlockManager | None = None,
        scheduler: SchedulerPolicy | None = None,
        runner: ModelRunner | None = None,
    ) -> None:
        self.config = config or LabConfig()
        self.config.validate()
        self.clock = clock or VirtualClock()
        self.memory = memory or KVBlockManager(self.config.kv_blocks, self.config.tokens_per_block)
        self.scheduler = scheduler or self._scheduler_from_config(self.config.scheduler)
        self.runner = runner or SimulatedModelRunner(self.config.runner_costs)
        self.iterations = 0
        self.prompt_tokens_processed = 0
        self.output_tokens_generated = 0

    def run(self, requests: list[InferenceRequest]) -> EngineResult:
        by_id = {request.request_id: request for request in requests}
        if len(by_id) != len(requests):
            raise ValueError("request IDs must be unique")

        pending = sorted(requests, key=lambda request: request.arrival_time_ms)
        active: list[InferenceRequest] = []
        start_ms = self.clock.now_ms()

        while pending or active:
            self._admit_arrivals(pending, active)
            if not active:
                self._advance_to_next_arrival(pending)
                self._admit_arrivals(pending, active)

            plan = self.scheduler.plan(active, self.config.token_budget)
            plan.validate()
            if not plan.items:
                self._advance_to_next_arrival(pending)
                continue

            self._ensure_memory_for_plan(plan, by_id)
            result = self.runner.execute(plan, by_id)
            self.clock.advance_ms(result.elapsed_ms)
            now = self.clock.now_ms()

            for item in plan.items:
                request = by_id[item.request_id]
                if item.kind == WorkKind.PREFILL:
                    request.apply_prefill(item.tokens)
                    self.prompt_tokens_processed += item.tokens
                else:
                    request.apply_decode(item.tokens, now)
                    self.output_tokens_generated += item.tokens

            self.iterations += 1
            self._release_completed(active)

        return EngineResult(
            requests=tuple(requests),
            iterations=self.iterations,
            elapsed_ms=self.clock.now_ms() - start_ms,
            prompt_tokens_processed=self.prompt_tokens_processed,
            output_tokens_generated=self.output_tokens_generated,
        )

    def _admit_arrivals(self, pending: list[InferenceRequest], active: list[InferenceRequest]) -> None:
        while pending and pending[0].arrival_time_ms <= self.clock.now_ms():
            if len(active) >= self.config.max_active_sequences:
                return
            request = pending.pop(0)
            request.mark_admitted()
            active.append(request)

    def _advance_to_next_arrival(self, pending: list[InferenceRequest]) -> None:
        if not pending:
            return
        delta = max(0.0, pending[0].arrival_time_ms - self.clock.now_ms())
        self.clock.advance_ms(delta)

    def _ensure_memory_for_plan(self, plan: SchedulePlan, requests: dict[str, InferenceRequest]) -> None:
        for item in plan.items:
            request = requests[item.request_id]
            target_context = request.current_context_tokens + item.tokens
            try:
                new_blocks = self.memory.ensure_capacity_for_context(request.request_id, target_context)
            except AllocationError as exc:
                request.state = RequestState.FAILED
                raise AllocationError(f"request {request.request_id} could not allocate KV blocks") from exc
            request.allocated_blocks.extend(new_blocks)

    def _release_completed(self, active: list[InferenceRequest]) -> None:
        remaining: list[InferenceRequest] = []
        for request in active:
            if request.state == RequestState.COMPLETED:
                self.memory.release_request(request.request_id)
                request.allocated_blocks.clear()
                request.shared_blocks.clear()
            else:
                remaining.append(request)
        active[:] = remaining

    def _scheduler_from_config(self, kind: SchedulerKind) -> SchedulerPolicy:
        if kind == SchedulerKind.BALANCED:
            return BalancedScheduler()
        return DecodePriorityScheduler()
