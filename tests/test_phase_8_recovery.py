from middle_man.lab.memory import KVBlockManager
from middle_man.lab.prefix_cache import PrefixCache
from middle_man.lab.request import InferenceRequest, RequestState


def test_preempted_partial_prefix_resumes_after_shared_prefix_boundary() -> None:
    memory = KVBlockManager(6, 2)
    cache = PrefixCache(memory)
    source = InferenceRequest("source", 0.0, 4, 1, shared_prefix_tokens=4, prefix_key="same")
    source.mark_admitted(0.0)
    source.allocated_blocks.extend(memory.ensure_capacity_for_context("source", 4))
    source.apply_prefill(4, 1.0)
    assert cache.publish(source)

    victim = InferenceRequest("victim", 0.0, 6, 1, shared_prefix_tokens=4, prefix_key="same")
    victim.mark_admitted(0.0)
    victim.allocated_blocks.extend(memory.ensure_capacity_for_context("victim", 2))
    victim.apply_prefill(2, 1.0)
    memory.release_request("victim")
    victim.mark_preempted()

    assert cache.acquire(victim) == 4
    victim.mark_admitted(2.0)
    assert victim.state == RequestState.PREFILLING
    assert victim.prompt_processed == 4
    assert victim.recompute_pending_tokens == 0
    assert victim.shared_blocks == [0, 1]
    assert memory.ensure_capacity_for_context("victim", 6) == (2,)
    victim.apply_prefill(2, 3.0)
    victim.apply_decode(1, 4.0)
    assert victim.state == RequestState.COMPLETED

    memory.release_request("victim")
    memory.release_request("source")
    cache.clear()
    assert memory.free_block_count == memory.total_blocks
