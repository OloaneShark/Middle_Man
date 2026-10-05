"""Confirmation-gated single Codex process for a real repository."""

from __future__ import annotations

import hashlib
import secrets
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from subprocess import Popen as _Popen

from middle_man.gateway.codex_runner.events import parse_production_events
from middle_man.gateway.codex_runner.infrastructure import (
    CodexCLI, capture_repository_state, changed_paths, validate_repository,
)
from middle_man.gateway.codex_runner.runner import (
    DEFAULT_EFFORT, DEFAULT_MODEL, CodexAudit, preview_codex,
)


DEFAULT_TIMEOUT = 360


@dataclass(frozen=True, slots=True)
class CodexRunResult:
    audit: CodexAudit
    run_id: str
    status: str
    failure_reasons: tuple[str, ...]
    exit_code: int | None
    timed_out: bool
    elapsed_seconds: float
    final_message: str
    thread_id: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None
    native_tool_calls: int
    explicit_reads: int
    unique_files: tuple[str, ...]
    rereads: int
    search_calls: int
    listing_calls: int
    content_search_calls: int
    file_targeted_searches: int
    repository_wide_searches: int
    file_listing_searches: int
    searched_paths: tuple[str, ...]
    unique_searched_paths: int
    git_inspections: int
    unclassified_commands: int
    locator_paths_explicitly_read: tuple[str, ...]
    locator_paths_searched: tuple[str, ...]
    non_locator_paths_searched: tuple[str, ...]
    git_head_before: str | None
    git_head_after: str | None
    git_status_before: tuple[str, ...]
    git_status_after: tuple[str, ...]
    changed_paths: tuple[str, ...]
    repository_unchanged: bool
    event_count: int
    malformed_event_lines: tuple[int, ...]
    mcp_calls: tuple[tuple[str, str], ...]
    stderr_sha256: str | None
    stderr_length_bytes: int
    external_calls: int

    def audit_dict(self) -> dict[str, object]:
        """Serializable local metadata; excludes prompts, source, and final answer."""
        data = asdict(self)
        data.pop("final_message")
        return data


def _start_codex(command: tuple[str, ...], root: Path):
    return _Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")


def _finish_stopped(process) -> tuple[str, str]:
    try:
        process.kill()
    except OSError:
        pass
    stdout, stderr = process.communicate()
    return stdout or "", stderr or ""


def run_codex(root: Path, task: str, *, mode: str, confirm_external_service: bool = False,
              model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT,
              timeout: int = DEFAULT_TIMEOUT, cli: CodexCLI | None = None) -> CodexRunResult:
    if not confirm_external_service:
        raise ValueError("live Codex execution requires --confirm-external-service")
    if timeout <= 0:
        raise ValueError("--timeout must be positive")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    root = validate_repository(root)
    before = capture_repository_state(root)
    preview = preview_codex(root, task, mode=mode, model=model, effort=effort, cli=cli)
    preprocessed = capture_repository_state(root)
    if preprocessed != before:
        raise RuntimeError("repository changed during Middle_Man preprocessing; Codex was not started")
    command = (*preview.invocation[:-1], "--json", preview.prompt)
    if capture_repository_state(root) != before:
        raise RuntimeError("repository changed before Codex process creation; Codex was not started")

    stdout = stderr = ""
    exit_code = None
    timed_out = interrupted = spawn_failed = io_failed = False
    external_calls = 0
    started = time.perf_counter()
    try:
        process = _start_codex(command, root)
        external_calls = 1
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout, stderr = _finish_stopped(process)
        except KeyboardInterrupt:
            interrupted = True
            stdout, stderr = _finish_stopped(process)
        except OSError:
            io_failed = True
            stdout, stderr = _finish_stopped(process)
        exit_code = process.returncode
    except OSError:
        spawn_failed = True
    elapsed = round(time.perf_counter() - started, 3)
    try:
        after = capture_repository_state(root)
    except RuntimeError:
        after = None
    events = parse_production_events(stdout or "", root)
    trace = events.parsed
    searches = events.search_telemetry
    locator_paths = set(preview.audit.selected_paths) if preview.audit.decision == "LOCATOR USED" else set()
    explicitly_read = tuple(sorted(locator_paths.intersection(trace.native.unique_files)))
    locator_searched = tuple(sorted(locator_paths.intersection(searches.searched_paths)))
    non_locator_searched = tuple(path for path in searches.searched_paths if path not in locator_paths)
    unchanged = after is not None and after == before
    reasons: list[str] = []
    if after is None:
        reasons.append("POST_RUN_INTEGRITY_UNKNOWN")
    elif mode == "read-only" and not unchanged:
        reasons.append("READ_ONLY_INTEGRITY_FAILURE")
    if interrupted:
        reasons.append("INTERRUPTED")
    if timed_out:
        reasons.append("TIMEOUT")
    if spawn_failed:
        reasons.append("SPAWN_ERROR")
    if io_failed:
        reasons.append("PROCESS_IO_ERROR")
    elif exit_code != 0 and not timed_out and not interrupted:
        reasons.append("CODEX_EXIT_NONZERO")
    if events.malformed_lines:
        reasons.append("MALFORMED_EVENTS")
    if events.turn_failed:
        reasons.append("CODEX_EVENT_FAILURE")
    if not events.turn_completed or not trace.final_message.strip():
        reasons.append("MISSING_FINAL_RESULT")
    if trace.mcp_calls:
        reasons.append("UNEXPECTED_MCP_ACTIVITY")
    live_audit = replace(preview.audit, dry_run=False, external_calls=external_calls,
                         repository_unchanged=unchanged)
    return CodexRunResult(
        live_audit, run_id, reasons[0] if reasons else "SUCCESS", tuple(reasons), exit_code,
        timed_out, elapsed, trace.final_message, trace.thread_id,
        trace.usage.input_tokens, trace.usage.cached_input_tokens,
        trace.usage.output_tokens, trace.usage.reasoning_output_tokens,
        trace.native.tool_calls, trace.native.file_reads, trace.native.unique_files,
        trace.native.rereads, trace.native.search_calls, trace.native.listing_calls,
        searches.content_search_calls, searches.file_targeted_searches,
        searches.repository_wide_searches, searches.file_listing_searches,
        searches.searched_paths, searches.unique_searched_paths,
        trace.native.git_inspections, trace.native.unclassified_commands,
        explicitly_read, locator_searched, non_locator_searched,
        before.head, after.head if after else None, before.status,
        after.status if after else (), changed_paths(before, after) if after else (),
        unchanged, trace.event_count, events.malformed_lines, trace.mcp_calls,
        hashlib.sha256((stderr or "").encode("utf-8")).hexdigest() if stderr else None,
        len((stderr or "").encode("utf-8")), external_calls,
    )
