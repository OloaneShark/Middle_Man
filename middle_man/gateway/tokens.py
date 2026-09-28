"""Provider-neutral, explicitly estimated context token counts."""

from __future__ import annotations

from math import ceil
from typing import Protocol


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


class HeuristicTokenEstimator:
    """Estimate one token per four UTF-8 bytes; not provider billing usage."""

    def estimate(self, text: str) -> int:
        return ceil(len(text.encode("utf-8")) / 4)
