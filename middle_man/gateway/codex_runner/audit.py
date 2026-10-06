"""Opt-in, source-free local receipts for production Codex runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from middle_man.gateway.secrets import SecretRedactor

if TYPE_CHECKING:
    from middle_man.gateway.codex_runner.execution import CodexRunResult


def _safe_paths(paths: tuple[str, ...]) -> list[str]:
    redactor = SecretRedactor()
    return [path for path in paths if path and not Path(path).is_absolute()
            and ".." not in Path(path).parts and not any(ord(char) < 32 for char in path)
            and redactor.redact(path).text == path]


def sanitized_receipt(result: CodexRunResult) -> dict[str, object]:
    audit = result.audit
    before = "\n".join(result.git_status_before)
    after = "\n".join(result.git_status_after)
    return {
        "schema_version": 1,
        "run_id": result.run_id,
        "task_hash": audit.task_hash,
        "task_length_bytes": audit.task_length_bytes,
        "task_mode": audit.task_mode,
        "codex_version": audit.codex_version,
        "requested_model": audit.requested_model,
        "requested_effort": audit.requested_effort,
        "auto_decision": audit.decision,
        "auto_reason": audit.decision_reason,
        "candidate_tokens_estimate": audit.candidate_tokens_estimate,
        "selected_tokens_estimate": audit.selected_tokens_estimate,
        "locator_estimated_tokens": audit.locator_estimated_tokens,
        "model_visible_middle_man_tokens": audit.model_visible_middle_man_tokens,
        "selected_paths": _safe_paths(audit.selected_paths),
        "locator_hash": audit.locator_hash,
        "selector_fingerprint": audit.selector_fingerprint,
        "status": result.status,
        "failure_reasons": list(result.failure_reasons),
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "elapsed_seconds": result.elapsed_seconds,
        "input_tokens": result.input_tokens,
        "cached_input_tokens": result.cached_input_tokens,
        "output_tokens": result.output_tokens,
        "reasoning_output_tokens": result.reasoning_output_tokens,
        "native_tool_calls": result.native_tool_calls,
        "explicit_reads": result.explicit_reads,
        "unique_files": _safe_paths(result.unique_files),
        "rereads": result.rereads,
        "search_calls": result.search_calls,
        "listing_calls": result.listing_calls,
        "content_search_calls": result.content_search_calls,
        "file_targeted_searches": result.file_targeted_searches,
        "repository_wide_searches": result.repository_wide_searches,
        "file_listing_searches": result.file_listing_searches,
        "searched_paths": _safe_paths(result.searched_paths),
        "unique_searched_paths": result.unique_searched_paths,
        "git_inspections": result.git_inspections,
        "unclassified_commands": result.unclassified_commands,
        "locator_paths_explicitly_read": _safe_paths(result.locator_paths_explicitly_read),
        "locator_paths_searched": _safe_paths(result.locator_paths_searched),
        "non_locator_paths_searched": _safe_paths(result.non_locator_paths_searched),
        "git_head_before": result.git_head_before,
        "git_head_after": result.git_head_after,
        "git_status_before_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
        "git_status_after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
        "git_status_before_entries": len(result.git_status_before),
        "git_status_after_entries": len(result.git_status_after),
        "changed_paths": _safe_paths(result.changed_paths),
        "repository_unchanged": result.repository_unchanged,
        "event_count": result.event_count,
        "malformed_event_lines": list(result.malformed_event_lines),
        "mcp_call_count": len(result.mcp_calls),
        "external_tool_activity_count": len(result.external_tool_activity),
        "external_tool_activity": [list(activity) for activity in result.external_tool_activity],
        "stderr_sha256": result.stderr_sha256,
        "stderr_length_bytes": result.stderr_length_bytes,
        "external_calls": result.external_calls,
    }


def save_audit(result: CodexRunResult) -> Path:
    root = Path(result.audit.repository_root).resolve()
    cache = root / ".middle_man_cache"
    runs = cache / "codex_runs"
    target = runs / result.run_id
    for directory in (cache, runs):
        if directory.is_symlink() or not directory.resolve().is_relative_to(root):
            raise ValueError("audit path escapes repository")
        directory.mkdir(exist_ok=True)
    target.mkdir(exist_ok=False)
    path = target / "result.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(sanitized_receipt(result), stream, indent=2, sort_keys=True)
        stream.write("\n")
    return path
