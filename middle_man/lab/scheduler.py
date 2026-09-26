from __future__ import annotations

from typing import Protocol

from middle_man.lab.request import InferenceRequest, RequestState
from middle_man.lab.work import SchedulePlan, WorkItem, WorkKind


class SchedulerPolicy(Protocol):
    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan: ...


class DecodePriorityScheduler:
    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan:
        remaining = token_budget
        items: list[WorkItem] = []
        decoding = [req for req in requests if req.state == RequestState.DECODING and req.remaining_output_tokens > 0]
        prefilling = [
            req
            for req in requests
            if req.state in {RequestState.PREFILLING, RequestState.QUEUED, RequestState.PREEMPTED}
            and req.remaining_prompt_tokens > 0
        ]

        for req in sorted(decoding, key=lambda item: (item.first_token_time_ms is not None, item.arrival_time_ms)):
            if remaining <= 0:
                break
            items.append(WorkItem(req.request_id, WorkKind.DECODE, 1))
            remaining -= 1

        for req in sorted(prefilling, key=lambda item: item.arrival_time_ms):
            if remaining <= 0:
                break
            tokens = min(remaining, req.remaining_prompt_tokens)
            items.append(WorkItem(req.request_id, WorkKind.PREFILL, tokens))
            remaining -= tokens

        return SchedulePlan(tuple(items), token_budget)


class BalancedScheduler:
    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan:
        remaining = token_budget
        items: list[WorkItem] = []
        decode_budget = max(1, token_budget // 2)
        decoding = [req for req in requests if req.state == RequestState.DECODING and req.remaining_output_tokens > 0]
        prefilling = [
            req
            for req in requests
            if req.state in {RequestState.PREFILLING, RequestState.QUEUED, RequestState.PREEMPTED}
            and req.remaining_prompt_tokens > 0
        ]

        for req in sorted(decoding, key=lambda item: item.arrival_time_ms):
            if remaining <= 0 or decode_budget <= 0:
                break
            items.append(WorkItem(req.request_id, WorkKind.DECODE, 1))
            remaining -= 1
            decode_budget -= 1

        if prefilling and remaining > 0:
            share = max(1, remaining // len(prefilling))
            for req in sorted(prefilling, key=lambda item: item.arrival_time_ms):
                if remaining <= 0:
                    break
                tokens = min(share, remaining, req.remaining_prompt_tokens)
                items.append(WorkItem(req.request_id, WorkKind.PREFILL, tokens))
                remaining -= tokens

        for req in sorted(decoding, key=lambda item: item.arrival_time_ms):
            if remaining <= 0:
                break
            already_scheduled = any(item.request_id == req.request_id for item in items)
            if not already_scheduled:
                items.append(WorkItem(req.request_id, WorkKind.DECODE, 1))
                remaining -= 1

        return SchedulePlan(tuple(items), token_budget)
