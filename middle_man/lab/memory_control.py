from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from middle_man.lab.events import EventType, SimulationEvent
from middle_man.lab.memory import AllocationError, KVBlockManager
from middle_man.lab.preemption import PreemptionPolicy
from middle_man.lab.prefix_cache import PrefixCache
from middle_man.lab.request import InferenceRequest, RequestState
from middle_man.lab.work import SchedulePlan, WorkKind


@dataclass(frozen=True)
class PreparedWork:
    plan: SchedulePlan
    victims: tuple[tuple[InferenceRequest, str], ...]


class MemoryController:
    def __init__(
        self,
        memory: KVBlockManager,
        cache: PrefixCache | None,
        policy: PreemptionPolicy,
        preemption_enabled: bool,
    ) -> None:
        self.memory = memory
        self.cache = cache
        self.policy = policy
        self.preemption_enabled = preemption_enabled

    def prepare(
        self,
        plan: SchedulePlan,
        active: list[InferenceRequest],
        requests: dict[str, InferenceRequest],
        now_ms: float,
        emit: Callable[[SimulationEvent], None],
        sample: Callable[[float], None],
    ) -> PreparedWork:
        victims: list[tuple[InferenceRequest, str]] = []
        for item in plan.items:
            request = requests[item.request_id]
            if request not in active:
                continue
            target = (
                request.recompute_rebuilt_tokens + item.tokens
                if item.kind == WorkKind.RECOMPUTE
                else request.current_context_tokens + item.tokens
            )
            if self.memory.blocks_for_tokens(target) > self.memory.total_blocks:
                request.state = RequestState.FAILED
                raise AllocationError(f"request {request.request_id} cannot fit in KV memory")

            while True:
                try:
                    blocks = self.memory.ensure_capacity_for_context(request.request_id, target)
                    request.allocated_blocks.extend(blocks)
                    if blocks:
                        emit(SimulationEvent(EventType.KV_ALLOCATED, now_ms, request.request_id, blocks=len(blocks)))
                        sample(now_ms)
                    break
                except AllocationError as exc:
                    if not self.preemption_enabled:
                        request.state = RequestState.FAILED
                        raise AllocationError(
                            f"request {request.request_id} could not allocate KV blocks"
                        ) from exc
                    if self.cache and self.cache.evict_unused():
                        sample(now_ms)
                        continue
                    victim = self.policy.choose_victim(active, request, self.memory)
                    if victim is None:
                        request.state = RequestState.FAILED
                        raise AllocationError(
                            f"request {request.request_id} cannot make KV progress"
                        ) from exc
                    freed = self.memory.release_request(victim.request_id)
                    lost_context = victim.current_context_tokens
                    victim.mark_preempted()
                    active.remove(victim)
                    victims.append((victim, request.request_id))
                    emit(SimulationEvent(
                        EventType.REQUEST_PREEMPTED,
                        now_ms,
                        victim.request_id,
                        tokens=lost_context,
                        blocks=freed,
                        related_request_id=request.request_id,
                    ))
                    emit(SimulationEvent(EventType.KV_RELEASED, now_ms, victim.request_id, blocks=freed))
                    sample(now_ms)

        executable = tuple(item for item in plan.items if requests[item.request_id] in active)
        return PreparedWork(SchedulePlan(executable, plan.token_budget), tuple(victims))
