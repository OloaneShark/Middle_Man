"""Opt-in, local preflight and evidence adapter for one future Codex pilot."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from middle_man.experiments.codex_exploration_trace import MAX_INPUT_BYTES, analyze_exploration_trace
from middle_man.gateway.codex_benchmark.tasks import source_fingerprint
from middle_man.gateway.codex_runner.events import parse_production_events
from middle_man.gateway.codex_runner.execution import CodexRunResult, run_codex
from middle_man.gateway.codex_runner.infrastructure import (
    CodexCLI, RepositorySnapshot, capture_repository_state, validate_repository,
)
from middle_man.gateway.codex_runner.runner import preview_codex
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


SOURCE_COMMIT = "db187e0f48f54222dd250502a2e40b7f1fb16401"
SOURCE_TREE = "c597226461db5975ffafd50a769404e03442fda6"
SOURCE_FINGERPRINT = "1a91d487a2629d4c82cbae7072ac873e8fcb516597fe954d53f74b649c4241fa"
AGENTS_BLOB = "0c8baf10e4f781c6b9eaa03c38a24b40d4e1978c"
SELECTOR_FINGERPRINT = "3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555"
TASK = ("Trace a read-only production Codex request from the CLI through local context selection, "
        "isolated execution, event parsing, audit creation, and repository integrity checks.")
TASK_SHA256 = "380ce2cdd99f2d2ea66a2b9c4dfa417af8227b1af4402c51387d45fb9d13531d"
CLI_VERSION = "codex-cli 0.162.0-alpha.17.2"
MODEL = "gpt-6-sol"
EFFORT = "high"
SANDBOX = "unelevated"
TIMEOUT_SECONDS = 360


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args],
                                   text=True, encoding="utf-8", timeout=20).strip()


def _layout(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tracked = set(subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "-z"],
                                          timeout=30).decode("utf-8").strip("\0").split("\0"))
    files: set[str] = set()
    directories: set[str] = set()
    for base, names, filenames in os.walk(root, topdown=True, followlinks=False):
        parent = Path(base)
        if parent == root:
            names[:] = [name for name in names if name != ".git"]
        for name in names:
            directory = parent / name
            if directory.is_symlink():
                raise ValueError("pilot snapshot contains a symlink directory")
            directories.add(directory.relative_to(root).as_posix())
        for name in filenames:
            path = parent / name
            if path.is_symlink() or (parent == root and name == ".git"):
                raise ValueError("pilot snapshot contains a symlink or Git worktree file")
            files.add(path.relative_to(root).as_posix())
    if files != tracked or not files:
        raise ValueError("pilot snapshot contains missing or untracked files")
    return tuple(sorted(files)), tuple(sorted(directories))


@dataclass(slots=True)
class PilotPreparation:
    root: Path
    before: RepositorySnapshot
    layout: tuple[tuple[str, ...], tuple[str, ...]]
    locator_decision: str
    locator_hash: str | None
    locator_estimated_tokens: int
    inspector: Callable[[str, Path], dict[str, object]]
    started: bool = False

    def check_ready(self) -> None:
        try:
            unchanged = capture_repository_state(self.root) == self.before and _layout(self.root) == self.layout
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            unchanged = False
        if not unchanged:
            raise RuntimeError("pinned pilot snapshot changed before process creation")

    def run_once(self, cli: CodexCLI, *, confirm_external_service: bool = False) -> tuple[CodexRunResult, dict[str, object]]:
        """One fixed research invocation; no retry, persistence, or CLI entry point."""
        if not confirm_external_service:
            raise ValueError("pilot requires separate external-service confirmation")
        if self.started:
            raise RuntimeError("pilot preparation has already been used")
        if cli.version != CLI_VERSION:
            raise ValueError("pilot CLI version changed")
        self.check_ready()
        self.started = True
        result = run_codex(self.root, TASK, mode="read-only", confirm_external_service=True,
                           model=MODEL, effort=EFFORT, timeout=TIMEOUT_SECONDS, cli=cli,
                           research_windows_sandbox=SANDBOX,
                           research_event_inspector=self.inspector)
        return result, assess_pilot(result, self)


def prepare_pilot(root: Path, cli: CodexCLI) -> PilotPreparation:
    """Validate a clean exact-source snapshot and build an in-memory callback."""
    root = validate_repository(root)
    if hashlib.sha256(TASK.encode("utf-8")).hexdigest() != TASK_SHA256:
        raise ValueError("pilot task wording changed")
    if cli.version != CLI_VERSION:
        raise ValueError("pilot CLI version differs from the local preflight pin")
    before = capture_repository_state(root)
    if before.status or before.head != SOURCE_COMMIT:
        raise ValueError("pilot snapshot must begin clean at the pinned HEAD")
    layout = _layout(root)
    if (_git(root, "rev-parse", "HEAD^{tree}") != SOURCE_TREE or
            _git(root, "rev-parse", "HEAD:AGENTS.md") != AGENTS_BLOB or
            source_fingerprint(root) != SOURCE_FINGERPRINT or
            selector_implementation_fingerprint() != SELECTOR_FINGERPRINT):
        raise ValueError("pilot source, selector, or clean-state pin differs")
    preview = preview_codex(root, TASK, mode="read-only", model=MODEL, effort=EFFORT, cli=cli,
                            research_windows_sandbox=SANDBOX)
    if capture_repository_state(root) != before or _layout(root) != layout:
        raise RuntimeError("pilot preview changed the pinned snapshot")

    def inspect(stdout: str, actual_root: Path) -> dict[str, object]:
        try:
            unchanged = (Path(actual_root).resolve() == root and
                         capture_repository_state(root) == before and _layout(root) == layout)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            unchanged = False
        if not unchanged:
            return {"valid": False, "failure": "SNAPSHOT_CHANGED"}
        if len(stdout.encode("utf-8")) > MAX_INPUT_BYTES:
            return {"valid": False, "failure": "EVENT_INPUT_OVER_BOUND"}
        events = parse_production_events(stdout, root)
        if events.malformed_lines:
            return {"valid": False, "failure": "MALFORMED_EVENTS"}
        if events.external_tool_activity or events.parsed.mcp_calls:
            return {"valid": False, "failure": "UNEXPECTED_EXTERNAL_TOOL_ACTIVITY"}
        if events.turn_failed or not events.turn_completed or not events.parsed.final_message.strip():
            return {"valid": False, "failure": "INCOMPLETE_TURN"}
        usage = events.parsed.usage
        if any(value is None for value in (usage.input_tokens, usage.cached_input_tokens,
                                           usage.output_tokens)):
            return {"valid": False, "failure": "MISSING_PROVIDER_USAGE"}
        return {"valid": True, "trace": analyze_exploration_trace(stdout, root)}

    return PilotPreparation(root, before, layout, preview.audit.decision, preview.audit.locator_hash,
                            preview.audit.locator_estimated_tokens, inspect)


def assess_pilot(result: CodexRunResult, prepared: PilotPreparation) -> dict[str, object]:
    """Fail closed on any runner or research failure; return no answer or prompt."""
    evidence = result.research_evidence
    valid = (result.status == "SUCCESS" and result.exit_code == 0 and not result.timed_out
             and not result.failure_reasons and result.external_calls == 1 and result.repository_unchanged
             and result.git_head_before == result.git_head_after == SOURCE_COMMIT
             and not result.git_status_before and not result.git_status_after
             and not result.malformed_event_lines and not result.mcp_calls
             and not result.external_tool_activity and not result.audit.dry_run
             and result.audit.task_mode == "read-only" and result.audit.task_hash == TASK_SHA256
             and Path(result.audit.repository_root).resolve() == prepared.root
             and result.audit.codex_version == CLI_VERSION
             and result.audit.requested_model == MODEL and result.audit.requested_effort == EFFORT
             and result.audit.decision == prepared.locator_decision
             and result.audit.locator_hash == prepared.locator_hash
             and result.audit.locator_estimated_tokens == prepared.locator_estimated_tokens
             and all(value is not None for value in (
                 result.input_tokens, result.cached_input_tokens, result.output_tokens))
             and isinstance(evidence, dict) and evidence.get("valid") is True
             and isinstance(evidence.get("trace"), dict))
    if not valid:
        return {"valid": False, "failure": "PILOT_VALIDITY_FAILURE"}
    trace = evidence["trace"]
    summary = trace.get("summary")
    if not isinstance(summary, dict) or (
            summary.get("native_tool_calls") != result.native_tool_calls or
            summary.get("explicit_reads") != result.explicit_reads or
            summary.get("unique_files") != len(result.unique_files) or
            summary.get("rereads") != result.rereads or
            summary.get("searches") != result.search_calls or
            summary.get("listings") != result.listing_calls or
            summary.get("unclassified_commands") != result.unclassified_commands):
        return {"valid": False, "failure": "AGGREGATE_PARITY_FAILURE"}
    return {"valid": True, "source_commit": SOURCE_COMMIT, "task_sha256": TASK_SHA256,
            "locator_decision": prepared.locator_decision,
            "locator_estimated_tokens": prepared.locator_estimated_tokens,
            "provider_usage": {"input_tokens": result.input_tokens,
                               "cached_input_tokens": result.cached_input_tokens,
                               "output_tokens": result.output_tokens,
                               "reasoning_output_tokens": result.reasoning_output_tokens},
            "trace": trace, "elapsed_seconds": result.elapsed_seconds}
