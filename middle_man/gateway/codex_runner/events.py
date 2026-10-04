"""Strict production framing around the shared Codex event parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from middle_man.gateway.codex_events import ParsedEvents, parse_codex_events


@dataclass(frozen=True, slots=True)
class ProductionEvents:
    parsed: ParsedEvents
    malformed_lines: tuple[int, ...]
    turn_completed: bool
    turn_failed: bool


def parse_production_events(stdout: str, root: Path) -> ProductionEvents:
    valid: list[str] = []
    malformed: list[int] = []
    completed = failed = False
    for number, line in enumerate(stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(number)
            continue
        if not isinstance(event, dict):
            malformed.append(number)
            continue
        completed |= event.get("type") == "turn.completed"
        failed |= event.get("type") in {"turn.failed", "error"}
        valid.append(line)
    return ProductionEvents(parse_codex_events(valid, root), tuple(malformed), completed, failed)
