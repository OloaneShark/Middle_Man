"""Strict production framing around the shared Codex event parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from middle_man.gateway.codex_events import ParsedEvents, parse_codex_events
from middle_man.gateway.codex_runner.search_telemetry import SearchTelemetry, summarize_searches


@dataclass(frozen=True, slots=True)
class ProductionEvents:
    parsed: ParsedEvents
    malformed_lines: tuple[int, ...]
    turn_completed: bool
    turn_failed: bool
    search_telemetry: SearchTelemetry


def parse_production_events(stdout: str, root: Path) -> ProductionEvents:
    valid: list[str] = []
    malformed: list[int] = []
    completed = failed = False
    commands: list[str] = []
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
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "command_execution":
            command = item.get("command")
            if isinstance(command, str):
                commands.append(command)
        valid.append(line)
    return ProductionEvents(parse_codex_events(valid, root), tuple(malformed), completed, failed,
                            summarize_searches(commands, root))
