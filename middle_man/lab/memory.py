from __future__ import annotations

from dataclasses import dataclass
from math import ceil


class AllocationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemorySnapshot:
    used_blocks: int
    total_blocks: int

    @property
    def utilization(self) -> float:
        return self.used_blocks / self.total_blocks if self.total_blocks else 0.0


class KVBlockManager:
    def __init__(self, total_blocks: int, tokens_per_block: int) -> None:
        if total_blocks <= 0:
            raise ValueError("total_blocks must be positive")
        if tokens_per_block <= 0:
            raise ValueError("tokens_per_block must be positive")
        self.total_blocks = total_blocks
        self.tokens_per_block = tokens_per_block
        self._free_blocks: list[int] = list(range(total_blocks))
        self._request_blocks: dict[str, list[int]] = {}
        self._request_shared: dict[str, list[int]] = {}
        self._ref_counts: dict[int, int] = {}

    @property
    def free_block_count(self) -> int:
        return len(self._free_blocks)

    @property
    def used_block_count(self) -> int:
        return self.total_blocks - self.free_block_count

    def blocks_for_tokens(self, tokens: int) -> int:
        if tokens <= 0:
            return 0
        return ceil(tokens / self.tokens_per_block)

    def private_blocks(self, request_id: str) -> tuple[int, ...]:
        return tuple(self._request_blocks.get(request_id, ()))

    def shared_blocks(self, request_id: str) -> tuple[int, ...]:
        return tuple(self._request_shared.get(request_id, ()))

    def request_blocks(self, request_id: str) -> tuple[int, ...]:
        return self.shared_blocks(request_id) + self.private_blocks(request_id)

    def block_ref_count(self, block_id: int) -> int:
        return self._ref_counts.get(block_id, 0)

    def snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(self.used_block_count, self.total_blocks)

    def allocate_for_tokens(self, request_id: str, tokens: int) -> tuple[int, ...]:
        needed = self.blocks_for_tokens(tokens)
        if needed == 0:
            return ()
        return self.allocate_blocks(request_id, needed)

    def ensure_capacity_for_context(self, request_id: str, context_tokens: int) -> tuple[int, ...]:
        owned = len(self.request_blocks(request_id))
        required = self.blocks_for_tokens(context_tokens)
        missing = max(0, required - owned)
        if missing == 0:
            return ()
        return self.allocate_blocks(request_id, missing)

    def allocate_blocks(self, request_id: str, count: int) -> tuple[int, ...]:
        if count < 0:
            raise ValueError("count must be non-negative")
        if count == 0:
            return ()
        if count > self.free_block_count:
            raise AllocationError(f"not enough free KV blocks: need {count}, have {self.free_block_count}")
        selected = [self._free_blocks.pop(0) for _ in range(count)]
        self._request_blocks.setdefault(request_id, []).extend(selected)
        for block_id in selected:
            self._ref_counts[block_id] = 1
        return tuple(selected)

    def retain_cache_blocks(self, blocks: tuple[int, ...]) -> None:
        for block_id in blocks:
            if self.block_ref_count(block_id) <= 0:
                raise ValueError(f"unknown KV block {block_id}")
        for block_id in blocks:
            self._ref_counts[block_id] += 1

    def attach_shared(self, request_id: str, blocks: tuple[int, ...]) -> None:
        owned = self.request_blocks(request_id)
        if len(set(blocks)) != len(blocks) or any(block in owned for block in blocks):
            raise ValueError("duplicate shared KV block ownership")
        for block_id in blocks:
            if self.block_ref_count(block_id) <= 0:
                raise ValueError(f"unknown KV block {block_id}")
        self._request_shared.setdefault(request_id, []).extend(blocks)
        for block_id in blocks:
            self._ref_counts[block_id] += 1

    def release_cache_blocks(self, blocks: tuple[int, ...]) -> int:
        if any(self.block_ref_count(block_id) <= 0 for block_id in blocks):
            raise ValueError("cache references an unowned KV block")
        return sum(self._release_block_ref(block_id) for block_id in blocks)

    def release_request(self, request_id: str) -> int:
        released = 0
        for block_id in self._request_blocks.pop(request_id, []):
            released += self._release_block_ref(block_id)
        for block_id in self._request_shared.pop(request_id, []):
            released += self._release_block_ref(block_id)
        return released

    def _release_block_ref(self, block_id: int) -> int:
        count = self._ref_counts.get(block_id, 0)
        if count <= 0:
            raise ValueError(f"KV block {block_id} has no owner")
        if count == 1:
            del self._ref_counts[block_id]
            self._free_blocks.append(block_id)
            self._free_blocks.sort()
            return 1
        self._ref_counts[block_id] = count - 1
        return 0