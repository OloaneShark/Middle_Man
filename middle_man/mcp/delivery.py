"""Session-local, metadata-only tracking of source lines sent to an MCP client."""

from __future__ import annotations

from dataclasses import dataclass

from middle_man.gateway.context_models import SourceExcerpt


@dataclass(frozen=True, slots=True)
class DeliveredRange:
    path: str
    content_hash: str
    start_line: int
    end_line: int
    text: str
    symbols: tuple[str, ...]
    reasons: tuple[str, ...]


class DeliveryLedger:
    def __init__(self) -> None:
        self._lines: set[tuple[str, str, int]] = set()
        self._fingerprints: set[str] = set()

    def select(self, fingerprint: str, excerpts: tuple[SourceExcerpt, ...], *,
               force_replay: bool = False) -> tuple[DeliveredRange, ...]:
        result: list[DeliveredRange] = []
        for excerpt in excerpts:
            lines = excerpt.text.splitlines(keepends=True)
            if len(lines) != excerpt.end_line - excerpt.start_line + 1:
                # Multiline redaction can collapse source lines. Preserve the safe text
                # as one indivisible excerpt instead of slicing it against stale line offsets.
                if force_replay or any(
                    (excerpt.path, excerpt.content_hash, number) not in self._lines
                    for number in range(excerpt.start_line, excerpt.end_line + 1)
                ):
                    result.append(DeliveredRange(excerpt.path, excerpt.content_hash,
                                                 excerpt.start_line, excerpt.end_line,
                                                 excerpt.text, excerpt.symbols, excerpt.reasons))
                continue
            start = None
            for offset in range(len(lines) + 1):
                number = excerpt.start_line + offset
                new = offset < len(lines) and (force_replay or
                    (excerpt.path, excerpt.content_hash, number) not in self._lines)
                if new and start is None:
                    start = offset
                if not new and start is not None:
                    result.append(DeliveredRange(excerpt.path, excerpt.content_hash,
                                                 excerpt.start_line + start, number - 1,
                                                 "".join(lines[start:offset]), excerpt.symbols,
                                                 excerpt.reasons))
                    start = None
        return tuple(result)

    def commit(self, fingerprint: str, delivery: list[dict[str, object]]) -> None:
        for excerpt in delivery:
            for number in range(int(excerpt["start_line"]), int(excerpt["end_line"]) + 1):
                self._lines.add((str(excerpt["path"]), str(excerpt["content_hash"]), number))
        self._fingerprints.add(fingerprint)

    def already_delivered(self, fingerprint: str) -> bool:
        return fingerprint in self._fingerprints

    @property
    def line_count(self) -> int:
        return len(self._lines)
