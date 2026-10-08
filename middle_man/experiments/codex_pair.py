"""Read-only Codex arm capture with a durable, sanitized receipt before rendering."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.codex_runner.execution import run_codex
from middle_man.gateway.codex_runner.infrastructure import (
    CodexCLI, capture_repository_state, changed_paths, validate_repository,
)


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
            or source_fingerprint(root) != pin.content_fingerprint):
        raise RuntimeError("experiment snapshot differs from the clean pinned source")
    _verify_guidance(root)
    if capture_repository_state(root) != state:
        raise RuntimeError("experiment snapshot changed during validation")
    return state


def _verify_guidance(root: Path) -> None:
    entries = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "-z", "HEAD"],
                             check=True, capture_output=True, timeout=30).stdout
    committed = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, relative = entry.split(b"\t", 1)
        if Path(relative.decode("utf-8", "surrogateescape")).name.casefold() == "agents.md":
            mode, kind, blob = metadata.split()
            committed[relative.decode("utf-8", "surrogateescape")] = (mode, kind, blob)
    present = {path.relative_to(root).as_posix(): path for path in root.rglob("*")
               if path.name.casefold() == "agents.md"}
    if present.keys() != committed.keys():
        raise RuntimeError("experiment guidance differs from the committed tree")
    for relative, (mode, kind, blob) in committed.items():
        path = present[relative]
        if kind != b"blob":
            raise RuntimeError("experiment guidance is not a committed blob")
        expected = subprocess.run(["git", "-C", str(root), "cat-file", "blob", blob.decode("ascii")],
                                  check=True, capture_output=True, timeout=15).stdout
        if mode == b"120000":
            if not path.is_symlink():
                raise RuntimeError("experiment guidance symlink differs from the committed tree")
            actual = os.readlink(path).encode("utf-8", "surrogateescape")
        else:
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("experiment guidance type differs from the committed tree")
            actual = path.read_bytes()
        if actual != expected:
            raise RuntimeError("experiment guidance bytes differ from the committed blob")


def run_arm(root: Path, task: str, *, arm: str, pin: SourcePin, cli: CodexCLI,
            expected_cli_version: str, windows_sandbox: str, timeout: int = 360,
            model: str = "gpt-6-sol", effort: str = "high",
            research_event_inspector: Callable[[str, Path], dict[str, object]] | None = None) -> ArmObservation:
    """Run one authorized arm; the caller controls authorization and arm order."""
    if arm not in {"BASELINE", "MIDDLE_MAN"} or timeout <= 0:
        raise ValueError("invalid experiment arm or timeout")
    if model != "gpt-6-sol" or effort != "high":
        raise ValueError("this harness currently implements only the locked model and effort")
    if windows_sandbox not in {"elevated", "unelevated"}:
        raise ValueError("experiment requires an explicit supported Windows backend")
    if cli.version != expected_cli_version:
        raise RuntimeError("Codex CLI version differs from the experiment pin")
    root = validate_repository(root)
    before = verify_snapshot(root, pin)
    task_hash = hashlib.sha256(task.encode("utf-8")).hexdigest()
    result = run_codex(root, task, mode="read-only", confirm_external_service=True,
                       model=model, effort=effort, timeout=timeout, cli=cli,
                       research_windows_sandbox=windows_sandbox,
                       research_baseline=(arm == "BASELINE"),
                       research_event_inspector=research_event_inspector)
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
    locator = None if arm == "BASELINE" else {
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
        "windows_sandbox": windows_sandbox,
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
    if research_event_inspector is not None:
        receipt["research_evidence"] = result.research_evidence
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
