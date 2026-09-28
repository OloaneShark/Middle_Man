import pytest

from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.memory import KVBlockManager
from middle_man.lab.request import InferenceRequest
from middle_man.lab.scheduler import DecodePriorityScheduler
from middle_man.lab.work import SchedulePlan


class SharingObserver(DecodePriorityScheduler):
    def __init__(self, memory: KVBlockManager) -> None:
        self.memory = memory
        self.shared_snapshots: list[tuple[int, ...]] = []

    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan:
        if len(requests) == 2:
            first = set(self.memory.request_blocks(requests[0].request_id))
            second = set(self.memory.request_blocks(requests[1].request_id))
            overlap = tuple(sorted(first & second))
            if overlap:
                self.shared_snapshots.append(overlap)
                assert all(self.memory.block_ref_count(block) == 3 for block in overlap)
        return super().plan(requests, token_budget)


def test_engine_really_shares_block_ids_then_cleans_up() -> None:
    config = LabConfig(token_budget=4, kv_blocks=8, tokens_per_block=2, prefix_cache_enabled=True)
    memory = KVBlockManager(8, 2)
    observer = SharingObserver(memory)
    engine = SimulationEngine(config, memory=memory, scheduler=observer)
    requests = [
        InferenceRequest("first", 0.0, 4, 1, shared_prefix_tokens=4, prefix_key="same"),
        InferenceRequest("second", 0.0, 4, 1, shared_prefix_tokens=4, prefix_key="same"),
    ]

    cached = engine.run(requests)

    assert observer.shared_snapshots == [(0, 1)]
    assert all(memory.block_ref_count(block) == 0 for block in range(memory.total_blocks))
    assert memory.free_block_count == memory.total_blocks

    uncached = SimulationEngine(LabConfig(
        token_budget=4, kv_blocks=8, tokens_per_block=2, prefix_cache_enabled=False,
    )).run([
        InferenceRequest("first", 0.0, 4, 1, shared_prefix_tokens=4, prefix_key="same"),
        InferenceRequest("second", 0.0, 4, 1, shared_prefix_tokens=4, prefix_key="same"),
    ])
    assert cached.prompt_tokens_processed < uncached.prompt_tokens_processed
    assert cached.metrics.aggregate.peak_kv_used_blocks < uncached.metrics.aggregate.peak_kv_used_blocks


def test_cache_reference_cannot_be_released_twice() -> None:
    memory = KVBlockManager(2, 2)
    blocks = memory.allocate_blocks("owner", 1)
    memory.retain_cache_blocks(blocks)
    memory.release_request("owner")
    memory.release_cache_blocks(blocks)
    assert memory.free_block_count == memory.total_blocks
    with pytest.raises(ValueError, match="unowned"):
        memory.release_cache_blocks(blocks)
    assert memory.used_block_count == 0
