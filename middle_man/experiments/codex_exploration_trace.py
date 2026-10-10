"""Research-only, source-free ordered observations from supplied Codex JSONL."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Iterable

from middle_man.gateway.codex_benchmark.events import _GIT, _LIST, _SEARCH
from middle_man.gateway.codex_benchmark.native_reads import explicit_read_paths, has_explicit_read
from middle_man.gateway.codex_runner.events import parse_production_events
from middle_man.gateway.codex_runner.search_telemetry import classify_search_command
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.secrets import SecretRedactor


MAX_INPUT_BYTES = 4_000_000
MAX_COMMANDS = 512
MAX_PATHS_PER_COMMAND = 32
MAX_PATH_LENGTH = 240
MAX_MALFORMED_LINES_REPORTED = 32


def _jsonl(events: str | Iterable[str]) -> str:
    lines = events.splitlines() if isinstance(events, str) else events
    kept: list[str] = []
    total = 0
    for line in lines:
        if not isinstance(line, str):
            raise ValueError("JSONL event lines must be strings")
        total += len(line.encode("utf-8")) + 1
        if total > MAX_INPUT_BYTES:
            raise ValueError("exploration event input exceeds research bound")
        kept.append(line)
    return "\n".join(kept)


def _safe_path(path: str, config: GatewayConfig, redactor: SecretRedactor) -> bool:
    relative = path.rstrip("/")
    parts = Path(relative).parts
    if (not relative or len(path) > MAX_PATH_LENGTH or Path(relative).is_absolute()
            or "\\" in path or ":" in path or ".." in parts
            or any(ord(char) < 32 for char in path)
            or redactor.redact(path).text != path
            or any(part.casefold() in config.ignored_directories for part in parts)
            or any(fnmatch.fnmatch(relative.casefold(), pattern.casefold())
                   or fnmatch.fnmatch(Path(relative).name.casefold(), pattern.casefold())
                   for pattern in config.ignored_patterns)):
        return False
    try:
        if config.relative_path(relative) != relative:
            return False
        current = config.repository_root
        for part in parts:
            current = current / part
            if current.is_symlink():
                return False
        return current.is_dir() if path.endswith("/") else current.is_file()
    except (OSError, ValueError):
        return False


def analyze_exploration_trace(events: str | Iterable[str], root: Path) -> dict[str, object]:
    """Classify completed commands in order without retaining command text."""
    config = GatewayConfig(root, cache_writes_enabled=False)
    redactor = SecretRedactor()
    payload = _jsonl(events)
    production = parse_production_events(payload, config.repository_root)
    seen_reads: set[str] = set()
    seen_search_targets: set[str] = set()
    steps: list[dict[str, object]] = []
    for line in payload.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        if len(steps) >= MAX_COMMANDS:
            raise ValueError("completed native command count exceeds research bound")

        original = item.get("command", "")
        command = " ".join(str(part) for part in original) if isinstance(original, list) else str(original)
        redacted = redactor.redact(command).text
        classified = redacted[:2000]
        details_unknown = not isinstance(original, str) or redacted != command or len(redacted) > 2000
        mixed = bool(has_explicit_read(classified) and _SEARCH.search(classified))
        details_unknown |= mixed
        raw_read_paths = explicit_read_paths(classified, config.repository_root)
        if has_explicit_read(classified):
            operation = "explicit_read"
            read_count = len(raw_read_paths) or 1
        elif _LIST.search(classified):
            operation, read_count = "listing", 0
        elif _SEARCH.search(classified):
            operation, read_count = "search", 0
        elif _GIT.search(classified):
            operation, read_count = "git_inspection", 0
        else:
            operation, read_count = "unclassified", 0
            details_unknown = True

        observation = (classify_search_command(redacted, config.repository_root)
                       if operation == "search" and isinstance(original, str) else None)
        raw_paths = (raw_read_paths if operation == "explicit_read" else
                     observation.target_paths if observation is not None else ())
        if len(raw_paths) > MAX_PATHS_PER_COMMAND:
            raise ValueError("native command target count exceeds research bound")
        paths = tuple(path for path in raw_paths if _safe_path(path, config, redactor))
        previously_read = tuple(path for path in paths if path in seen_reads) if operation == "explicit_read" else ()
        revisited_search = tuple(path for path in paths if path in seen_search_targets) if operation == "search" else ()
        if operation == "explicit_read":
            seen_reads.update(paths)
        elif operation == "search":
            seen_search_targets.update(paths)
            details_unknown |= observation is None
        paths_unknown = (len(paths) != len(raw_paths) or
                         operation == "explicit_read" and not raw_paths or
                         operation == "search" and (observation is None or not raw_paths) or
                         operation in {"listing", "git_inspection", "unclassified"})
        steps.append({
            "command_position": len(steps) + 1,
            "operation_type": operation,
            "target_paths": paths,
            "explicit_file_read_count": read_count,
            "previously_read_paths": previously_read,
            "revisited_search_target_paths": revisited_search,
            "unclassified": operation == "unclassified",
            "paths_unknown": bool(paths_unknown),
            "operation_details_unknown": bool(details_unknown),
        })

    native = production.parsed.native
    if (len(steps), sum(step["explicit_file_read_count"] for step in steps),
            sum(step["operation_type"] == "search" for step in steps),
            sum(step["operation_type"] == "listing" for step in steps),
            sum(step["unclassified"] for step in steps)) != (
            native.tool_calls, native.file_reads, native.search_calls,
            native.listing_calls, native.unclassified_commands):
        raise RuntimeError("ordered trace diverges from production native classification")
    return {
        "schema": "middle_man.codex_exploration_trace.v1",
        "status": "OFFLINE_RESEARCH_ONLY",
        "steps": steps,
        "summary": {
            "native_tool_calls": native.tool_calls,
            "explicit_reads": native.file_reads,
            "unique_files": len(native.unique_files),
            "rereads": native.rereads,
            "searches": native.search_calls,
            "listings": native.listing_calls,
            "git_inspections": native.git_inspections,
            "unclassified_commands": native.unclassified_commands,
            "possible_repeated_read_commands": sum(bool(step["previously_read_paths"]) for step in steps),
            "revisited_search_target_commands": sum(bool(step["revisited_search_target_paths"]) for step in steps),
            "unknown_path_commands": sum(step["paths_unknown"] for step in steps),
            "malformed_event_count": len(production.malformed_lines),
            "malformed_event_lines": production.malformed_lines[:MAX_MALFORMED_LINES_REPORTED],
            "external_inference_calls": 0,
        },
    }
