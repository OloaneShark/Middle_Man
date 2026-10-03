"""Parse documented-style Claude stream-json events without inferred usage."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable

from .models import ClaudeRunEvents, ClaudeUsage, ToolAction


def _integer(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _usage(value: Any) -> ClaudeUsage:
    data = value if isinstance(value, dict) else {}
    return ClaudeUsage(*(_integer(data.get(name)) for name in ClaudeUsage.__dataclass_fields__))


def _action(block: dict[str, Any]) -> ToolAction | None:
    name = block.get("name")
    if block.get("type") != "tool_use" or not isinstance(name, str):
        return None
    arguments = block.get("input")
    arguments = arguments if isinstance(arguments, dict) else {}
    kind = {"Read": "read", "Grep": "search", "Glob": "listing",
            "Edit": "edit", "MultiEdit": "edit", "Write": "write", "Bash": "bash"}.get(name, "other")
    path = arguments.get("file_path") if kind in {"read", "edit", "write"} else None
    return ToolAction(name, kind, path if isinstance(path, str) and path else None)


def parse_stream_json(lines: Iterable[str], *, strict: bool = True,
                      timed_out: bool = False) -> ClaudeRunEvents:
    session = result_text = model = None
    duration = api_duration = turns = None
    cost = None
    usage = ClaudeUsage()
    message_usages: list[ClaudeUsage] = []
    actions: list[ToolAction] = []
    warnings: list[str] = []
    final_status = None
    result_has_usage = False
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError(f"malformed Claude stream-json line {number}") from exc
            warnings.append(f"malformed Claude stream-json line {number}")
            continue
        if not isinstance(event, dict):
            if strict:
                raise ValueError(f"Claude stream-json line {number} is not an object")
            warnings.append(f"Claude stream-json line {number} is not an object")
            continue
        if isinstance(event.get("session_id"), str):
            session = event["session_id"]
        kind = event.get("type")
        if kind == "assistant":
            message = event.get("message")
            if isinstance(message, dict):
                if isinstance(message.get("model"), str):
                    model = message["model"]
                if isinstance(message.get("usage"), dict):
                    message_usages.append(_usage(message["usage"]))
                blocks = message.get("content")
                if isinstance(blocks, list):
                    actions.extend(action for block in blocks if isinstance(block, dict)
                                   if (action := _action(block)) is not None)
        elif kind == "result":
            final_status = "error" if event.get("is_error") is True or event.get("subtype") not in (None, "success") else "success"
            result_text = event.get("result") if isinstance(event.get("result"), str) else None
            duration = _integer(event.get("duration_ms"))
            api_duration = _integer(event.get("duration_api_ms"))
            turns = _integer(event.get("num_turns"))
            raw_cost = event.get("total_cost_usd")
            cost = float(raw_cost) if type(raw_cost) in (int, float) and raw_cost >= 0 else None
            if isinstance(event.get("usage"), dict):
                usage = _usage(event["usage"])
                result_has_usage = True
    if not result_has_usage and message_usages:
        usage = ClaudeUsage(*(sum(value for item in message_usages if (value := getattr(item, name)) is not None)
                              if any(getattr(item, name) is not None for item in message_usages) else None
                              for name in ClaudeUsage.__dataclass_fields__))
    if final_status is None:
        warnings.append("stream ended without a final result")
    if timed_out:
        warnings.append("process timed out")
    reads = Counter(action.path for action in actions if action.kind == "read" and action.path)
    files = tuple(dict.fromkeys(action.path for action in actions if action.path))
    return ClaudeRunEvents(session, result_text, "timeout" if timed_out else final_status or "incomplete",
                           duration, api_duration, turns, cost, usage, model, tuple(actions), files,
                           sum(count - 1 for count in reads.values()), tuple(warnings))
