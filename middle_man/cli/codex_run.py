"""User-facing, local-only Codex run preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from middle_man.gateway.codex_runner.runner import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS, preview_codex


def add_codex_run_command(actions: argparse._SubParsersAction) -> None:
    run = actions.add_parser("run", help="preview production Codex navigation on the current repository")
    run.add_argument("task", help="quoted user task; preserved exactly in the Codex prompt")
    run.add_argument("--repo", type=Path, default=Path("."))
    modes = run.add_mutually_exclusive_group(required=True)
    modes.add_argument("--read-only", action="store_true")
    modes.add_argument("--workspace-write", action="store_true")
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--effort", choices=EFFORTS, default=DEFAULT_EFFORT)
    run.add_argument("--dry-run", action="store_true", required=True,
                     help="required; live Codex execution is not available")
    run.add_argument("--json", action="store_true", help="print source-free audit JSON")


def run_codex_preview(args: argparse.Namespace) -> None:
    try:
        preview = preview_codex(args.repo, args.task,
                                mode="read-only" if args.read_only else "workspace-write",
                                model=args.model, effort=args.effort)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    audit = preview.audit
    if args.json:
        print(json.dumps({**audit.as_dict(), "redacted_command_shape": preview.redacted_command_shape}, indent=2))
        return
    print("MIDDLE_MAN CODEX")
    print(f"Repository: {audit.repository_root}")
    print(f"Mode: {audit.task_mode}")
    print(f"AUTO: {audit.decision} ({audit.decision_reason})")
    print(f"Candidate source: {audit.candidate_tokens_estimate:,} heuristic tokens")
    print(f"Selected source: {audit.selected_tokens_estimate:,} heuristic tokens")
    print(f"Locator: {audit.locator_estimated_tokens:,} heuristic tokens")
    print(f"Model-visible Middle_Man content: {audit.model_visible_middle_man_tokens:,} heuristic tokens")
    print(f"Locator paths: {', '.join(audit.selected_paths) if audit.decision == 'LOCATOR USED' else '(none)'}")
    print(f"Codex: {audit.codex_version} ({audit.codex_executable})")
    print(f"Model: {audit.requested_model}; effort: {audit.requested_effort}")
    print("Command shape: " + " ".join(preview.redacted_command_shape))
    print("External call: NO (dry-run)")
