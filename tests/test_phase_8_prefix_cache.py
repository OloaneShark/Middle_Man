from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.events import EventType
from middle_man.lab.memory import KVBlockManager
from middle_man.lab.request import InferenceRequest, RequestState


def test_shared_block_references_survive_individual_releases() -> None:
    memory = KVBlockManager(total_blocks=4, tokens_per_block=2)
    blocks = memory.allocate_blocks("a", 2)
    memory.retain_cache_blocks(blocks)
    memory.attach_shared("b", blocks)
    assert all(memory.block_ref_count(block) == 3 for block in blocks)

    assert memory.release_request("a") == 0
    assert all(memory.block_ref_count(block) == 2 for block in blocks)
    assert memory.release_request("b") == 0
    assert all(memory.block_ref_count(block) == 1 for block in blocks)
    assert memory.release_cache_blocks(blocks) == 2
    assert memory.free_block_count == 4
    assert memory.request_blocks("a") == memory.request_blocks("b") == ()


def shared_requests(key: str = "same") -> list[InferenceRequest]:
    return [
        InferenceRequest("a", 0.0, prompt_tokens=4, max_output_tokens=1,
                         shared_prefix_tokens=4, prefix_key=key),
        InferenceRequest("b", 5.0, prompt_tokens=4, max_output_tokens=1,
                         shared_prefix_tokens=4, prefix_key=key),
    ]


def test_second_request_reuses_prefix_work_and_physical_blocks() -> None:
    config = LabConfig(token_budget=4, kv_blocks=8, tokens_per_block=2, prefix_cache_enabled=True)
    engine = SimulationEngine(config)
    requests = shared_requests()
    result = engine.run(requests)

    assert result.metrics.aggregate.prefix_cache_misses == 1
    assert result.metrics.aggregate.prefix_cache_hits == 1
    assert result.metrics.aggregate.prefix_reused_tokens == 4
    assert result.metrics.aggregate.total_prompt_tokens_processed == 4
    assert requests[1].prefix_cache_hit
    assert requests[1].prefix_reused_tokens == 4
    assert any(event.kind == EventType.PREFIX_CACHE_HIT and event.request_id == "b"
               for event in result.events)
    assert all(request.state == RequestState.COMPLETED for request in requests)
    assert engine.memory.free_block_count == engine.memory.total_blocks

    uncached = SimulationEngine(LabConfig(
        token_budget=4, kv_blocks=8, tokens_per_block=2, prefix_cache_enabled=False,
    )).run(shared_requests())
    assert uncached.prompt_tokens_processed == 8
    assert uncached.metrics.aggregate.prefix_cache_hits == 0


def test_partial_prefix_shares_only_complete_blocks() -> None:
    engine = SimulationEngine(LabConfig(
        token_budget=16, kv_blocks=8, tokens_per_block=16, prefix_cache_enabled=True,
    ))
    requests = [
        InferenceRequest("a", 0.0, 24, 0, shared_prefix_tokens=20, prefix_key="partial"),
        InferenceRequest("b", 10.0, 24, 0, shared_prefix_tokens=20, prefix_key="partial"),
    ]
    result = engine.run(requests)
    assert requests[1].prefix_reused_tokens == 16
    assert result.prompt_tokens_processed == 32
    assert engine.memory.free_block_count == engine.memory.total_blocks


def test_different_or_incompatible_keys_do_not_share() -> None:
    engine = SimulationEngine(LabConfig(
        token_budget=4, kv_blocks=12, tokens_per_block=2, prefix_cache_enabled=True,
    ))
    requests = [
        InferenceRequest("a", 0.0, 4, 0, shared_prefix_tokens=4, prefix_key="one"),
        InferenceRequest("b", 5.0, 4, 0, shared_prefix_tokens=4, prefix_key="two"),
        InferenceRequest("c", 10.0, 4, 0, shared_prefix_tokens=2, prefix_key="one"),
    ]
    result = engine.run(requests)
    assert result.metrics.aggregate.prefix_cache_hits == 0
    assert result.metrics.aggregate.prefix_cache_misses == 3
    assert result.prompt_tokens_processed == 12
    assert engine.memory.free_block_count == engine.memory.total_blocks


def test_prefix_sharing_survives_preemption_and_finishes_without_leaks() -> None:
    engine = SimulationEngine(LabConfig(
        token_budget=2, kv_blocks=3, tokens_per_block=2,
        prefix_cache_enabled=True, preemption_enabled=True,
    ))
    requests = [
        InferenceRequest("a", 0.0, 2, 3, shared_prefix_tokens=2, prefix_key="system"),
        InferenceRequest("b", 2.0, 2, 3, shared_prefix_tokens=2, prefix_key="system"),
    ]
    result = engine.run(requests)
    assert result.metrics.aggregate.prefix_cache_hits >= 1
    assert result.metrics.aggregate.preemption_count >= 1
    assert all(request.state == RequestState.COMPLETED for request in requests)
    assert all(request.output_generated == 3 for request in requests)
    assert engine.memory.free_block_count == engine.memory.total_blocks
    assert all(engine.memory.request_blocks(request.request_id) == () for request in requests)
