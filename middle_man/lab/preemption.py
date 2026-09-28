from __future__ import annotations

from typing import Protocol

from middle_man.lab.memory import KVBlockManager
from middle_man.lab.request import InferenceRequest, RequestState


class PreemptionPolicy(Protocol):
    def choose_victim(
        self,
        active: list[InferenceRequest],
        requester: InferenceRequest,
        memory: KVBlockManager,
    ) -> InferenceRequest | None: ...


class LargestPrivateOwnerPolicy:
    def choose_victim(
        self,
        active: list[InferenceRequest],
        requester: InferenceRequest,
        memory: KVBlockManager,
    ) -> InferenceRequest | None:
        eligible = [
            request for request in active
            if request is not requester
            and request.state not in {RequestState.COMPLETED, RequestState.FAILED, RequestState.CANCELLED}
            and memory.private_blocks(request.request_id)
        ]
        if not eligible:
            return None
        return min(
            eligible,
            key=lambda request: (-len(memory.private_blocks(request.request_id)), request.request_id),
        )
