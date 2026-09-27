import pytest

from middle_man.lab.memory import AllocationError, KVBlockManager


def test_kv_allocator_uses_block_ids_and_releases_them() -> None:
    memory = KVBlockManager(total_blocks=4, tokens_per_block=8)
    blocks = memory.allocate_for_tokens("req-1", 17)
    assert blocks == (0, 1, 2)
    assert memory.request_blocks("req-1") == (0, 1, 2)
    assert memory.free_block_count == 1
    released = memory.release_request("req-1")
    assert released == 3
    assert memory.free_block_count == 4
    assert memory.request_blocks("req-1") == ()


def test_kv_allocator_can_assign_non_contiguous_blocks_after_release() -> None:
    memory = KVBlockManager(total_blocks=5, tokens_per_block=4)
    assert memory.allocate_blocks("a", 2) == (0, 1)
    assert memory.allocate_blocks("b", 2) == (2, 3)
    memory.release_request("a")
    assert memory.allocate_blocks("c", 3) == (0, 1, 4)


def test_released_blocks_are_reusable() -> None:
    memory = KVBlockManager(total_blocks=3, tokens_per_block=4)
    original = memory.allocate_blocks("first", 2)
    memory.release_request("first")
    reused = memory.allocate_blocks("second", 2)
    assert reused == original


def test_kv_allocator_reports_exhaustion_without_partial_allocation() -> None:
    memory = KVBlockManager(total_blocks=3, tokens_per_block=4)
    memory.allocate_blocks("existing", 2)
    before = memory.snapshot()

    with pytest.raises(AllocationError):
        memory.allocate_blocks("too-large", 2)

    assert memory.snapshot() == before
    assert memory.request_blocks("too-large") == ()
    assert memory.request_blocks("existing") == (0, 1)


def test_used_blocks_never_exceed_total_blocks() -> None:
    memory = KVBlockManager(total_blocks=4, tokens_per_block=4)
    memory.allocate_blocks("a", 2)
    assert memory.snapshot().used_blocks <= memory.snapshot().total_blocks
    memory.allocate_blocks("b", 2)
    assert memory.snapshot().used_blocks == memory.snapshot().total_blocks
    with pytest.raises(AllocationError):
        memory.allocate_blocks("c", 1)
    assert memory.snapshot().used_blocks == memory.snapshot().total_blocks


def test_ensure_capacity_allocates_only_missing_blocks() -> None:
    memory = KVBlockManager(total_blocks=8, tokens_per_block=4)
    assert memory.ensure_capacity_for_context("req-1", 1) == (0,)
    assert memory.ensure_capacity_for_context("req-1", 4) == ()
    assert memory.ensure_capacity_for_context("req-1", 5) == (1,)
