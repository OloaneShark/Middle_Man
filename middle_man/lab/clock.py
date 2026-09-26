from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> float: ...

    def advance_ms(self, delta_ms: float) -> None: ...


@dataclass
class VirtualClock:
    current_ms: float = 0.0

    def now_ms(self) -> float:
        return self.current_ms

    def advance_ms(self, delta_ms: float) -> None:
        if delta_ms < 0:
            raise ValueError("delta_ms must be non-negative")
        self.current_ms += delta_ms


class WallClock:
    def now_ms(self) -> float:
        return time.time() * 1000

    def advance_ms(self, delta_ms: float) -> None:
        if delta_ms < 0:
            raise ValueError("delta_ms must be non-negative")
        time.sleep(delta_ms / 1000)
