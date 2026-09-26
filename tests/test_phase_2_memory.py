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


def test_kv_allocator_can_assign_non_contiguous_blocks_after_release() -> None:
    memory = KVBlockManager(total_blocks=5, tokens_per_block=4)
    assert memory.allocate_blocks("a", 2) == (0, 1)
    assert memory.allocate_blocks("b", 2) == (2, 3)
    memory.release_request("a")
    assert memory.allocate_blocks("c", 3) == (0, 1, 4)


def test_kv_allocator_reports_exhaustion() -> None:
    memory = KVBlockManager(total_blocks=2, tokens_per_block=4)
    memory.allocate_for_tokens("req-1", 8)
    with pytest.raises(AllocationError):
        memory.allocate_for_tokens("req-2", 1)


def test_ensure_capacity_allocates_only_missing_blocks() -> None:
    memory = KVBlockManager(total_blocks=8, tokens_per_block=4)
    assert memory.ensure_capacity_for_context("req-1", 1) == (0,)
    assert memory.ensure_capacity_for_context("req-1", 4) == ()
    assert memory.ensure_capacity_for_context("req-1", 5) == (1,)
