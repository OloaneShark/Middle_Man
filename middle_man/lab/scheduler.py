from __future__ import annotations

from typing import Protocol

from middle_man.lab.request import InferenceRequest, RequestState
from middle_man.lab.work import SchedulePlan, WorkItem, WorkKind


class SchedulerPolicy(Protocol):
    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan: ...


def _prefill_candidates(requests: list[InferenceRequest]) -> list[tuple[InferenceRequest, WorkKind, int]]:
    candidates = []
    for request in requests:
        if request.state == RequestState.PREEMPTED and request.recompute_pending_tokens:
            candidates.append((request, WorkKind.RECOMPUTE, request.recompute_pending_tokens))
        elif request.state in {RequestState.PREFILLING, RequestState.QUEUED} and request.remaining_prompt_tokens:
            candidates.append((request, WorkKind.PREFILL, request.remaining_prompt_tokens))
    return sorted(candidates, key=lambda item: item[0].arrival_time_ms)


class DecodePriorityScheduler:
    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan:
        remaining = token_budget
        items: list[WorkItem] = []
        decoding = [req for req in requests if req.state == RequestState.DECODING and req.remaining_output_tokens > 0]

        for req in sorted(decoding, key=lambda item: (item.first_token_time_ms is not None, item.arrival_time_ms)):
            if remaining <= 0:
                break
            items.append(WorkItem(req.request_id, WorkKind.DECODE, 1))
            remaining -= 1

        for req, kind, available in _prefill_candidates(requests):
            if remaining <= 0:
                break
            tokens = min(remaining, available)
            items.append(WorkItem(req.request_id, kind, tokens))
            remaining -= tokens

        return SchedulePlan(tuple(items), token_budget)


class BalancedScheduler:
    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan:
        remaining = token_budget
        items: list[WorkItem] = []
        decode_budget = max(1, token_budget // 2)
        decoding = [req for req in requests if req.state == RequestState.DECODING and req.remaining_output_tokens > 0]
        prefilling = _prefill_candidates(requests)

        for req in sorted(decoding, key=lambda item: item.arrival_time_ms):
            if remaining <= 0 or decode_budget <= 0:
                break
            items.append(WorkItem(req.request_id, WorkKind.DECODE, 1))
            remaining -= 1
            decode_budget -= 1

        if prefilling and remaining > 0:
            share = max(1, remaining // len(prefilling))
            for req, kind, available in prefilling:
                if remaining <= 0:
                    break
                tokens = min(share, remaining, available)
                items.append(WorkItem(req.request_id, kind, tokens))
                remaining -= tokens

        for req in sorted(decoding, key=lambda item: item.arrival_time_ms):
            if remaining <= 0:
                break
            if not any(item.request_id == req.request_id for item in items):
                items.append(WorkItem(req.request_id, WorkKind.DECODE, 1))
                remaining -= 1

        return SchedulePlan(tuple(items), token_budget)