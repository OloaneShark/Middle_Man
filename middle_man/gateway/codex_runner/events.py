"""Strict production framing around the shared Codex event parser."""

from __future__ import annotations

import json
import re
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
    external_tool_activity: tuple[tuple[str, str], ...]


_EXTERNAL_NAME = re.compile(r"(?:^|[^a-z])(?:mcp|codex_apps|connector|plugin|app)(?:$|[^a-z])")
_SAFE_EVENT_NAME = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


def _external_activity(event: dict[str, object]) -> tuple[str, str] | None:
    item = event.get("item")
    item = item if isinstance(item, dict) else {}
    kind = event.get("type")
    item_type = item.get("type")
    if item_type == "command_execution":
        return None
    names = [value.lower() for value in (kind, item_type, item.get("server"),
             item.get("provider"), item.get("tool"), item.get("name")) if isinstance(value, str)]
    joined = " ".join(names)
    if not (_EXTERNAL_NAME.search(joined) or
            isinstance(item.get("provider"), str) or isinstance(item.get("server"), str) or
            ("resource" in joined and ("list" in joined or "read" in joined))):
        return None
    category = next((name for name in ("mcp", "codex_apps", "connector", "plugin", "app")
                     if _EXTERNAL_NAME.search(" ".join(value for value in names if name in value))),
                    "resource")
    detail = item_type if isinstance(item_type, str) else kind
    return category, detail if isinstance(detail, str) and _SAFE_EVENT_NAME.fullmatch(detail) else "unknown"


def parse_production_events(stdout: str, root: Path) -> ProductionEvents:
    valid: list[str] = []
    malformed: list[int] = []
    completed = failed = False
    commands: list[str] = []
    external: list[tuple[str, str]] = []
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
        activity = _external_activity(event)
        if activity is not None:
            external.append(activity)
        completed |= event.get("type") == "turn.completed"
        failed |= event.get("type") in {"turn.failed", "error"}
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "command_execution":
            command = item.get("command")
            if isinstance(command, str):
                commands.append(command)
        valid.append(line)
    return ProductionEvents(parse_codex_events(valid, root), tuple(malformed), completed, failed,
                            summarize_searches(commands, root), tuple(external))
