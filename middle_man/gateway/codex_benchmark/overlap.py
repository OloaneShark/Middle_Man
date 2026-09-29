"""Estimate repeated delivered source using path, hash, and line identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ContextDelivery:
    pack_fingerprints: tuple[str, ...]
    selected_paths: tuple[str, ...]
    selected_ranges: tuple[tuple[str, str, int, int], ...]
    candidate_tokens: int
    selected_tokens: int
    pack_result_tokens: int
    all_mcp_result_tokens: int
    unique_source_bytes: int
    repeated_source_bytes: int
    unique_source_tokens_estimate: int
    repeated_source_tokens_estimate: int
    overlap_ratio: float | None
    non_source_pack_overhead_estimate: int
    unique_source_delivery_ratio: float | None
    overlap_available: bool


def measure_delivery(entries: Iterable[dict[str, Any]]) -> ContextDelivery:
    records = tuple(entries)
    pack_entries = tuple(item for item in records if item.get("success") and item.get("tool") in
                         {"middleman_context_pack", "middleman_expand_context"})
    selected = sum(int(item.get("metrics", {}).get("selected_tokens", 0)) for item in pack_entries)
    candidate = sum(int(item.get("metrics", {}).get("raw_candidate_tokens", 0)) for item in pack_entries)
    result = sum(int(item.get("metrics", {}).get("result_tokens", 0)) for item in pack_entries)
    all_result = sum(int(item.get("metrics", {}).get("result_tokens", 0)) for item in records)
    seen: dict[tuple[str, str, int], int] = {}
    ranges: list[tuple[str, str, int, int]] = []
    paths: set[str] = set()
    repeated = 0
    available = all(isinstance(item.get("delivery"), list) for item in pack_entries)
    if available:
        for entry in pack_entries:
            for excerpt in entry["delivery"]:
                path, digest = excerpt["path"], excerpt["content_hash"]
                start, end = int(excerpt["start_line"]), int(excerpt["end_line"])
                line_bytes = excerpt["line_bytes"]
                if len(line_bytes) != end - start + 1:
                    available = False
                    break
                paths.add(path)
                ranges.append((path, digest, start, end))
                for line, size in enumerate(line_bytes, start):
                    key = (path, digest, line)
                    if key in seen:
                        repeated += int(size)
                    else:
                        seen[key] = int(size)
            if not available:
                break
    if not available:
        seen.clear()
        repeated = 0
        ranges.clear()
        paths.clear()
    unique = sum(seen.values())
    total = unique + repeated
    return ContextDelivery(
        tuple(str(item.get("pack_fingerprint")) for item in pack_entries if item.get("pack_fingerprint")),
        tuple(sorted(paths)), tuple(ranges), candidate, selected, result, all_result,
        unique, repeated, (unique + 3) // 4, (repeated + 3) // 4,
        repeated / total if available and total else None,
        result - selected, ((unique + 3) // 4) / result if available and result else None,
        available,
    )
