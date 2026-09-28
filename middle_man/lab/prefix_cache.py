from __future__ import annotations

from dataclasses import dataclass

from middle_man.lab.memory import KVBlockManager
from middle_man.lab.request import InferenceRequest


@dataclass(frozen=True)
class PrefixEntry:
    key: str
    declared_tokens: int
    tokens: int
    blocks: tuple[int, ...]


class PrefixCache:
    def __init__(self, memory: KVBlockManager) -> None:
        self.memory = memory
        self._entries: dict[str, PrefixEntry] = {}

    def cacheable_tokens(self, request: InferenceRequest) -> int:
        if not request.prefix_key:
            return 0
        return (request.shared_prefix_tokens // self.memory.tokens_per_block) * self.memory.tokens_per_block

    @property
    def cached_block_count(self) -> int:
        return sum(len(entry.blocks) for entry in self._entries.values())

    def has_compatible_entry(self, request: InferenceRequest) -> bool:
        entry = self._entries.get(request.prefix_key or "")
        return (
            entry is not None
            and entry.declared_tokens == request.shared_prefix_tokens
            and entry.tokens == self.cacheable_tokens(request)
        )

    def acquire(self, request: InferenceRequest) -> int:
        tokens = self.cacheable_tokens(request)
        entry = self._entries.get(request.prefix_key or "")
        if (
            not tokens
            or entry is None
            or entry.declared_tokens != request.shared_prefix_tokens
            or entry.tokens != tokens
        ):
            return 0
        self.memory.attach_shared(request.request_id, entry.blocks)
        request.shared_blocks.extend(entry.blocks)
        request.reuse_prefix(tokens)
        return tokens

    def publish(self, request: InferenceRequest) -> bool:
        tokens = self.cacheable_tokens(request)
        if not tokens or request.prompt_processed < tokens or request.prefix_key in self._entries:
            return False
        block_count = tokens // self.memory.tokens_per_block
        blocks = self.memory.private_blocks(request.request_id)[:block_count]
        if len(blocks) != block_count:
            return False
        self.memory.retain_cache_blocks(blocks)
        self._entries[request.prefix_key] = PrefixEntry(
            request.prefix_key, request.shared_prefix_tokens, tokens, blocks
        )
        return True

    def clear(self) -> int:
        freed = 0
        for entry in self._entries.values():
            freed += self.memory.release_cache_blocks(entry.blocks)
        self._entries.clear()
        return freed

    def evict_unused(self) -> int:
        freed = 0
        for key, entry in list(self._entries.items()):
            if all(self.memory.block_ref_count(block) == 1 for block in entry.blocks):
                freed += self.memory.release_cache_blocks(entry.blocks)
                del self._entries[key]
        return freed
