from __future__ import annotations

from dataclasses import dataclass

from middle_man.lab.clock import Clock, VirtualClock
from middle_man.lab.config import LabConfig, SchedulerKind
from middle_man.lab.events import EventType, SimulationEvent
from middle_man.lab.memory import KVBlockManager
from middle_man.lab.memory_control import MemoryController
from middle_man.lab.metrics import MetricsCollector, MetricsResult
from middle_man.lab.preemption import LargestPrivateOwnerPolicy, PreemptionPolicy
from middle_man.lab.prefix_cache import PrefixCache
from middle_man.lab.request import InferenceRequest, RequestState
from middle_man.lab.runner import ModelRunner, SimulatedModelRunner
from middle_man.lab.scheduler import BalancedScheduler, DecodePriorityScheduler, SchedulerPolicy
from middle_man.lab.work import SchedulePlan, WorkKind


class SimulationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineResult:
    requests: tuple[InferenceRequest, ...]
    iterations: int
    elapsed_ms: float
    prompt_tokens_processed: int
    output_tokens_generated: int
    metrics: MetricsResult
    events: tuple[SimulationEvent, ...]


class SimulationEngine:
    def __init__(
        self,
        config: LabConfig | None = None,
        *,
        clock: Clock | None = None,
        memory: KVBlockManager | None = None,
        scheduler: SchedulerPolicy | None = None,
        runner: ModelRunner | None = None,
        preemption_policy: PreemptionPolicy | None = None,
    ) -> None:
        self.config = config or LabConfig()
        self.config.validate()
        self.clock = clock or VirtualClock()
        self.memory = memory or KVBlockManager(self.config.kv_blocks, self.config.tokens_per_block)
        self.scheduler = scheduler or self._scheduler_from_config(self.config.scheduler)
        self.runner = runner or SimulatedModelRunner(self.config.runner_costs)
        self.preemption_policy = preemption_policy or LargestPrivateOwnerPolicy()
        self.iterations = 0
        self.prompt_tokens_processed = 0
        self.output_tokens_generated = 0

    def run(self, requests: list[InferenceRequest]) -> EngineResult:
        by_id = {request.request_id: request for request in requests}
        if len(by_id) != len(requests):
            raise ValueError("request IDs must be unique")
        self.iterations = 0
        self.prompt_tokens_processed = 0
        self.output_tokens_generated = 0
        pending = sorted(requests, key=lambda request: request.arrival_time_ms)
        active: list[InferenceRequest] = []
        resume_after: dict[str, str] = {}
        events: list[SimulationEvent] = []
        cache = PrefixCache(self.memory) if self.config.prefix_cache_enabled else None
        collector = MetricsCollector(self.memory, cache)
        collector.sample(self.clock.now_ms())
        controller = MemoryController(
            self.memory, cache, self.preemption_policy, self.config.preemption_enabled
        )
        start_ms = self.clock.now_ms()

        try:
            while pending or active:
                self._admit_arrivals(pending, active, resume_after, cache, events, collector)
                if not active:
                    if pending:
                        self._advance_to_next_arrival(pending, resume_after, by_id)
                        self._admit_arrivals(pending, active, resume_after, cache, events, collector)
                    if not active:
                        continue

                plan = self.scheduler.plan(active, self.config.token_budget)
                plan.validate()
                if not plan.items:
                    raise SimulationError("scheduler produced no work for active requests")

                prepared = controller.prepare(
                    plan, active, by_id, self.clock.now_ms(), events.append, collector.sample
                )
                for victim, requester_id in prepared.victims:
                    resume_after[victim.request_id] = requester_id
                    pending.append(victim)
                if not prepared.plan.items:
                    raise SimulationError("KV pressure left no executable work")
                self._execute(prepared.plan, by_id, cache, events, collector)
                self.iterations += 1
                self._release_completed(active, events, collector)
        finally:
            if cache:
                cache.clear()
                collector.sample(self.clock.now_ms())
            for request in requests:
                if self.memory.request_blocks(request.request_id):
                    self.memory.release_request(request.request_id)
                    request.allocated_blocks.clear()
                    request.shared_blocks.clear()
                    collector.sample(self.clock.now_ms())

        elapsed_ms = self.clock.now_ms() - start_ms
        event_tuple = tuple(events)
        metrics = collector.build(
            requests, event_tuple, elapsed_ms, self.iterations,
            self.prompt_tokens_processed, self.output_tokens_generated,
        )
        return EngineResult(
            requests=tuple(requests),
            iterations=self.iterations,
            elapsed_ms=elapsed_ms,
            prompt_tokens_processed=self.prompt_tokens_processed,
            output_tokens_generated=self.output_tokens_generated,
            metrics=metrics,
            events=event_tuple,
        )

    def _admit_arrivals(
        self,
        pending: list[InferenceRequest],
        active: list[InferenceRequest],
        resume_after: dict[str, str],
        cache: PrefixCache | None,
        events: list[SimulationEvent],
        collector: MetricsCollector,
    ) -> None:
        for request in list(pending):
            if len(active) >= self.config.max_active_sequences:
                break
            if request.arrival_time_ms > self.clock.now_ms():
                continue
            if cache and cache.cacheable_tokens(request) and not cache.has_compatible_entry(request):
                same_prefix_active = any(
                    item.prefix_key == request.prefix_key
                    and cache.cacheable_tokens(item) == cache.cacheable_tokens(request)
                    and item.state != RequestState.PREEMPTED
                    for item in active
                )
                if same_prefix_active:
                    continue
            blocker_id = resume_after.get(request.request_id)
            if blocker_id and any(
                item.request_id == blocker_id and item.state != RequestState.COMPLETED
                for item in active + pending
            ):
                continue
            pending.remove(request)
            resume_after.pop(request.request_id, None)
            if cache and cache.cacheable_tokens(request):
                reused = cache.acquire(request)
                kind = EventType.PREFIX_CACHE_HIT if reused else EventType.PREFIX_CACHE_MISS
                events.append(SimulationEvent(kind, self.clock.now_ms(), request.request_id, tokens=reused))
                if reused:
                    collector.sample(self.clock.now_ms())
            request.mark_admitted(self.clock.now_ms())
            events.append(SimulationEvent(EventType.REQUEST_ADMITTED, self.clock.now_ms(), request.request_id))
            if request.state == RequestState.COMPLETED:
                events.append(SimulationEvent(EventType.REQUEST_COMPLETED, self.clock.now_ms(), request.request_id))
                self._release_request(request, events, collector)
            elif request.state not in {RequestState.CANCELLED, RequestState.FAILED}:
                active.append(request)

    def _advance_to_next_arrival(
        self,
        pending: list[InferenceRequest],
        resume_after: dict[str, str],
        by_id: dict[str, InferenceRequest],
    ) -> None:
        ready = [
            request.arrival_time_ms for request in pending
            if not (
                resume_after.get(request.request_id)
                and by_id[resume_after[request.request_id]].state != RequestState.COMPLETED
            )
        ]
        if not ready:
            raise SimulationError("no active request can unblock pending work")
        next_time = min(ready)
        if next_time <= self.clock.now_ms():
            raise SimulationError("admission made no progress")
        self.clock.advance_ms(next_time - self.clock.now_ms())

    def _execute(
        self,
        plan: SchedulePlan,
        by_id: dict[str, InferenceRequest],
        cache: PrefixCache | None,
        events: list[SimulationEvent],
        collector: MetricsCollector,
    ) -> None:
        result = self.runner.execute(plan, by_id)
        self.clock.advance_ms(result.elapsed_ms)
        now = self.clock.now_ms()
        for item in plan.items:
            request = by_id[item.request_id]
            if item.kind == WorkKind.PREFILL:
                request.apply_prefill(item.tokens, now)
                self.prompt_tokens_processed += item.tokens
                events.append(SimulationEvent(EventType.PREFILL_EXECUTED, now, request.request_id, tokens=item.tokens))
                if cache and cache.publish(request):
                    collector.sample(now)
            elif item.kind == WorkKind.RECOMPUTE:
                request.apply_recompute(item.tokens, now)
                events.append(SimulationEvent(EventType.RECOMPUTE_EXECUTED, now, request.request_id, tokens=item.tokens))
            else:
                request.apply_decode(item.tokens, now)
                self.output_tokens_generated += item.tokens
                events.append(SimulationEvent(EventType.DECODE_EXECUTED, now, request.request_id, tokens=item.tokens))
            if request.state == RequestState.COMPLETED:
                events.append(SimulationEvent(EventType.REQUEST_COMPLETED, now, request.request_id))

    def _release_completed(
        self,
        active: list[InferenceRequest],
        events: list[SimulationEvent],
        collector: MetricsCollector,
    ) -> None:
        for request in list(active):
            if request.state == RequestState.COMPLETED:
                self._release_request(request, events, collector)
                active.remove(request)

    def _release_request(
        self,
        request: InferenceRequest,
        events: list[SimulationEvent],
        collector: MetricsCollector,
    ) -> None:
        freed = self.memory.release_request(request.request_id)
        request.allocated_blocks.clear()
        request.shared_blocks.clear()
        events.append(SimulationEvent(EventType.KV_RELEASED, self.clock.now_ms(), request.request_id, blocks=freed))
        collector.sample(self.clock.now_ms())

    def _scheduler_from_config(self, kind: SchedulerKind) -> SchedulerPolicy:
        if kind == SchedulerKind.BALANCED:
            return BalancedScheduler()
        return DecodePriorityScheduler()