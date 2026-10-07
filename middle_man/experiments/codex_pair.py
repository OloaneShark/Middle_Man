"""Read-only Codex arm capture with a durable, sanitized receipt before rendering."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.codex_runner.events import parse_production_events
from middle_man.gateway.codex_runner.execution import run_codex
from middle_man.gateway.codex_runner.infrastructure import (
    CodexCLI, capture_repository_state, changed_paths, validate_repository,
)
from middle_man.gateway.codex_runner.isolation import verify_isolation_command
from middle_man.gateway.codex_runner.runner import build_invocation


_Popen = subprocess.Popen


@dataclass(frozen=True, slots=True)
class SourcePin:
    commit: str
    tree: str
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class ArmObservation:
    receipt: dict[str, object]
    final_answer: str  # Memory-only: deliberately excluded from the persisted receipt.


def verify_snapshot(root: Path, pin: SourcePin):
    root = validate_repository(root)
    state = capture_repository_state(root)
    tree = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"],
                          check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    if (state.head != pin.commit or state.status or tree != pin.tree
            or source_fingerprint(root) != pin.content_fingerprint
            or (root / "AGENTS.md").exists()):
        raise RuntimeError("experiment snapshot differs from the clean pinned source")
    return state


def _details(events) -> dict[str, object]:
    trace = events.parsed
    searches = events.search_telemetry
    return {
        "input_tokens": trace.usage.input_tokens,
        "cached_input_tokens": trace.usage.cached_input_tokens,
        "output_tokens": trace.usage.output_tokens,
        "reasoning_output_tokens": trace.usage.reasoning_output_tokens,
        "native_tool_calls": trace.native.tool_calls,
        "explicit_reads": trace.native.file_reads,
        "unique_explicit_read_files": len(trace.native.unique_files),
        "rereads": trace.native.rereads,
        "search_calls": trace.native.search_calls,
        "listing_calls": trace.native.listing_calls,
        "content_search_calls": searches.content_search_calls,
        "file_targeted_searches": searches.file_targeted_searches,
        "repository_wide_searches": searches.repository_wide_searches,
        "file_listing_searches": searches.file_listing_searches,
        "git_inspections": trace.native.git_inspections,
        "unclassified_commands": trace.native.unclassified_commands,
        "event_count": trace.event_count,
        "malformed_event_lines": list(events.malformed_lines),
        "external_tool_activity_count": len(events.external_tool_activity),
        "mcp_call_count": len(trace.mcp_calls),
    }


def _baseline(root: Path, task: str, cli: CodexCLI, timeout: int, expected_before):
    invocation = build_invocation(cli, root, task, mode="read-only",
                                  model="gpt-6-sol", effort="high")
    command = (*invocation[:-1], "--json", task)
    verify_isolation_command(command)
    before = capture_repository_state(root)
    if before != expected_before:
        raise RuntimeError("baseline snapshot changed before process creation")
    started = time.perf_counter()
    stdout = ""
    exit_code = None
    timed_out = spawn_failed = False
    try:
        process = _Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace")
        try:
            stdout, _stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, _stderr = process.communicate()
        exit_code = process.returncode
    except OSError:
        spawn_failed = True
    elapsed = round(time.perf_counter() - started, 3)
    try:
        after = capture_repository_state(root)
    except RuntimeError:
        after = None
    events = parse_production_events(stdout or "", root)
    reasons = []
    if after is None:
        reasons.append("POST_RUN_INTEGRITY_UNKNOWN")
    elif after != before:
        reasons.append("READ_ONLY_INTEGRITY_FAILURE")
    if timed_out:
        reasons.append("TIMEOUT")
    if spawn_failed:
        reasons.append("SPAWN_ERROR")
    elif exit_code != 0 and not timed_out:
        reasons.append("CODEX_EXIT_NONZERO")
    if events.malformed_lines:
        reasons.append("MALFORMED_EVENTS")
    if events.turn_failed:
        reasons.append("CODEX_EVENT_FAILURE")
    if not events.turn_completed or not events.parsed.final_message.strip():
        reasons.append("MISSING_FINAL_RESULT")
    if events.external_tool_activity:
        reasons.append("UNEXPECTED_EXTERNAL_TOOL_ACTIVITY")
    if events.parsed.mcp_calls:
        reasons.append("UNEXPECTED_MCP_ACTIVITY")
    return events, before, after, elapsed, exit_code, timed_out, reasons, not spawn_failed


def run_arm(root: Path, task: str, *, arm: str, pin: SourcePin, cli: CodexCLI,
            expected_cli_version: str, timeout: int = 360,
            model: str = "gpt-6-sol", effort: str = "high") -> ArmObservation:
    """Run one authorized arm; the caller controls authorization and arm order."""
    if arm not in {"BASELINE", "MIDDLE_MAN"} or timeout <= 0:
        raise ValueError("invalid experiment arm or timeout")
    if model != "gpt-6-sol" or effort != "high":
        raise ValueError("this harness currently implements only the locked model and effort")
    if cli.version != expected_cli_version:
        raise RuntimeError("Codex CLI version differs from the experiment pin")
    root = validate_repository(root)
    before = verify_snapshot(root, pin)
    task_hash = hashlib.sha256(task.encode("utf-8")).hexdigest()
    if arm == "BASELINE":
        events, _observed_before, after, elapsed, exit_code, timed_out, reasons, started = _baseline(
            root, task, cli, timeout, before)
        metrics = _details(events)
        answer = events.parsed.final_message
        locator = None
    else:
        result = run_codex(root, task, mode="read-only", confirm_external_service=True,
                           model=model, effort=effort, timeout=timeout, cli=cli)
        try:
            after = capture_repository_state(root)
        except RuntimeError:
            after = None
        elapsed, exit_code, timed_out = result.elapsed_seconds, result.exit_code, result.timed_out
        reasons = list(result.failure_reasons)
        started = bool(result.external_calls)
        answer = result.final_message
        metrics = {
            "input_tokens": result.input_tokens,
            "cached_input_tokens": result.cached_input_tokens,
            "output_tokens": result.output_tokens,
            "reasoning_output_tokens": result.reasoning_output_tokens,
            "native_tool_calls": result.native_tool_calls,
            "explicit_reads": result.explicit_reads,
            "unique_explicit_read_files": len(result.unique_files),
            "rereads": result.rereads,
            "search_calls": result.search_calls,
            "listing_calls": result.listing_calls,
            "content_search_calls": result.content_search_calls,
            "file_targeted_searches": result.file_targeted_searches,
            "repository_wide_searches": result.repository_wide_searches,
            "file_listing_searches": result.file_listing_searches,
            "git_inspections": result.git_inspections,
            "unclassified_commands": result.unclassified_commands,
            "event_count": result.event_count,
            "malformed_event_lines": list(result.malformed_event_lines),
            "external_tool_activity_count": len(result.external_tool_activity),
            "mcp_call_count": len(result.mcp_calls),
        }
        locator = {
            "decision": result.audit.decision,
            "reason": result.audit.decision_reason,
            "candidate_tokens_estimate": result.audit.candidate_tokens_estimate,
            "selected_tokens_estimate": result.audit.selected_tokens_estimate,
            "locator_tokens_estimate": result.audit.locator_estimated_tokens,
            "model_visible_tokens_estimate": result.audit.model_visible_middle_man_tokens,
            "selected_paths": list(result.audit.selected_paths),
            "locator_hash": result.audit.locator_hash,
            "locator_paths_explicitly_read": list(result.locator_paths_explicitly_read),
            "locator_paths_searched": list(result.locator_paths_searched),
            "non_locator_paths_searched": list(result.non_locator_paths_searched),
        }
    if after is None:
        if "POST_RUN_INTEGRITY_UNKNOWN" not in reasons:
            reasons.insert(0, "POST_RUN_INTEGRITY_UNKNOWN")
    elif after != before and "READ_ONLY_INTEGRITY_FAILURE" not in reasons:
        reasons.insert(0, "READ_ONLY_INTEGRITY_FAILURE")
    try:
        source_after = source_fingerprint(root)
    except OSError:
        source_after = None
    if source_after is None and "POST_RUN_INTEGRITY_UNKNOWN" not in reasons:
        reasons.insert(0, "POST_RUN_INTEGRITY_UNKNOWN")
    elif (source_after != pin.content_fingerprint
          and "READ_ONLY_INTEGRITY_FAILURE" not in reasons):
        reasons.insert(0, "READ_ONLY_INTEGRITY_FAILURE")
    receipt = {
        "schema_version": 1,
        "arm": arm,
        "task_sha256": task_hash,
        "source_commit": pin.commit,
        "source_tree": pin.tree,
        "source_fingerprint_before": pin.content_fingerprint,
        "source_fingerprint_after": source_after,
        "cli_version": cli.version,
        "model": model,
        "effort": effort,
        "timeout_seconds": timeout,
        "process_started": started,
        "status": reasons[0] if reasons else "SUCCESS",
        "failure_reasons": reasons,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "metrics": metrics,
        "locator": locator,
        "semantic_review": None,
        "repository": {
            "head_before": before.head,
            "head_after": after.head if after else None,
            "status_before": list(before.status),
            "status_after": list(after.status) if after else None,
            "content_digest_before": before.digest,
            "content_digest_after": after.digest if after else None,
            "changed_paths": list(changed_paths(before, after)) if after else None,
            "unchanged": after == before,
        },
    }
    return ArmObservation(receipt, answer)


def record_and_render(observation: ArmObservation, receipt_path: Path, stream: TextIO) -> str:
    """Persist sanitized metadata first; console failures cannot erase the observation."""
    receipt_path = receipt_path.resolve()
    if receipt_path.exists():
        raise FileExistsError("experiment receipt already exists; refusing overwrite")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    def save(rendering_status: str) -> None:
        payload = json.dumps({**observation.receipt, "output_rendering": rendering_status},
                             ensure_ascii=True, sort_keys=True, indent=2) + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=receipt_path.parent,
                                             prefix=".codex-pair-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, receipt_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    save("RESULT_CAPTURED")
    display = json.dumps({"receipt": observation.receipt,
                          "final_answer": observation.final_answer}, ensure_ascii=True)
    try:
        stream.write(display + "\n")
        stream.flush()
    except (UnicodeError, OSError):
        save("OUTPUT_RENDERING_FAILURE")
        return "OUTPUT_RENDERING_FAILURE"
    save("RENDERED")
    return "RENDERED"
