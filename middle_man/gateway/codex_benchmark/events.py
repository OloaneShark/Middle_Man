"""Conservative parsing of documented Codex exec JSONL events."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from middle_man.gateway.secrets import SecretRedactor

_FILE = re.compile(r"(?<![\w.])(?:[\w.-]+[/\\])*[\w.-]+\.(?:py|md|toml|json|yaml|yml|txt|css)(?!\w)", re.I)
_READ = re.compile(r"(?i)\b(?:Get-Content|cat|type|sed|head|tail)\b")
_LIST = re.compile(r"(?i)\b(?:Get-ChildItem|ls|dir)\b|\brg\s+--files\b")
_SEARCH = re.compile(r"(?i)\b(?:rg|grep|Select-String|findstr)\b")
_GIT = re.compile(r"(?i)\bgit\s+(?:status|diff|show|log|ls-files|grep)\b")


@dataclass(frozen=True, slots=True)
class CodexUsage:
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class NativeExploration:
    tool_calls: int
    file_reads: int
    unique_files: tuple[str, ...]
    rereads: int
    search_calls: int
    listing_calls: int
    git_inspections: int
    unclassified_commands: int


@dataclass(frozen=True, slots=True)
class ParsedEvents:
    thread_id: str | None
    final_message: str
    usage: CodexUsage
    native: NativeExploration
    mcp_calls: tuple[tuple[str, str], ...]
    file_change_events: int
    event_count: int
    errors: tuple[str, ...]
    sanitized_events: tuple[dict[str, Any], ...]
    reported_model: str | None
    reported_effort: str | None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _explicit_files(command: str, root: Path) -> tuple[str, ...]:
    files: list[str] = []
    for match in _FILE.finditer(command):
        candidate = match.group(0).replace("\\", "/")
        path = (root / candidate).resolve()
        if path.is_relative_to(root.resolve()) and path.is_file():
            files.append(path.relative_to(root.resolve()).as_posix())
    return tuple(dict.fromkeys(files))


def parse_codex_events(lines: Iterable[str], root: Path) -> ParsedEvents:
    redactor = SecretRedactor()
    native_commands: list[str] = []
    mcp_calls: list[tuple[str, str]] = []
    file_reads: list[str] = []
    read_count = search_count = listing_count = git_count = unclassified = 0
    file_changes = event_count = 0
    thread_id = reported_model = reported_effort = None
    final_message = ""
    errors: list[str] = []
    safe_events: list[dict[str, Any]] = []
    usage = CodexUsage()
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        event_count += 1
        kind = event.get("type")
        if kind == "thread.started":
            thread_id = event.get("thread_id") if isinstance(event.get("thread_id"), str) else None
            reported_model = event.get("model") if isinstance(event.get("model"), str) else None
            reported_effort = event.get("model_reasoning_effort") if isinstance(event.get("model_reasoning_effort"), str) else None
            safe_events.append({"type": kind, "thread_id": thread_id})
        elif kind == "turn.completed":
            values = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            input_tokens = _count(values.get("input_tokens"))
            output_tokens = _count(values.get("output_tokens"))
            usage = CodexUsage(input_tokens, _count(values.get("cached_input_tokens")), output_tokens,
                               _count(values.get("reasoning_output_tokens")),
                               _count(values.get("total_tokens")))
            safe_events.append({"type": kind, "usage": {
                "input_tokens": usage.input_tokens, "cached_input_tokens": usage.cached_input_tokens,
                "output_tokens": usage.output_tokens, "reasoning_output_tokens": usage.reasoning_output_tokens,
                "total_tokens": usage.total_tokens,
            }})
        elif kind in {"turn.failed", "error"}:
            message = redactor.redact(str(event.get("message", event.get("error", "unknown")))).text
            errors.append(message[:500])
            safe_events.append({"type": kind, "message": message[:500]})
        elif isinstance(kind, str) and kind.startswith("item."):
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if kind != "item.completed":
                continue
            if item_type == "command_execution":
                command = item.get("command", "")
                if isinstance(command, list):
                    command = " ".join(str(part) for part in command)
                command = redactor.redact(str(command)).text[:2000]
                native_commands.append(command)
                paths = _explicit_files(command, root)
                if _READ.search(command):
                    read_count += len(paths) or 1
                    file_reads.extend(paths)
                elif _LIST.search(command):
                    listing_count += 1
                elif _SEARCH.search(command):
                    search_count += 1
                elif _GIT.search(command):
                    git_count += 1
                else:
                    unclassified += 1
                safe_events.append({"type": kind, "item_type": item_type, "command": command,
                                    "explicit_read_paths": list(paths) if _READ.search(command) else []})
            elif item_type == "mcp_tool_call":
                server = str(item.get("server", ""))
                tool = str(item.get("tool", item.get("name", "")))
                mcp_calls.append((server, tool))
                safe_events.append({"type": kind, "item_type": item_type, "server": server, "tool": tool})
            elif item_type == "file_change":
                file_changes += 1
                safe_events.append({"type": kind, "item_type": item_type})
            elif item_type == "agent_message":
                final_message = redactor.redact(str(item.get("text", ""))).text
                safe_events.append({"type": kind, "item_type": item_type, "text": final_message[:4000]})
            else:
                safe_events.append({"type": kind, "item_type": str(item_type)})
    unique = tuple(sorted(set(file_reads)))
    native = NativeExploration(len(native_commands), read_count, unique, max(0, len(file_reads) - len(unique)),
                               search_count, listing_count, git_count, unclassified)
    return ParsedEvents(thread_id, final_message, usage, native, tuple(mcp_calls), file_changes,
                        event_count, tuple(errors), tuple(safe_events), reported_model, reported_effort)
