"""User-facing Codex runner with an explicit external-service gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from middle_man.gateway.codex_runner.runner import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS, preview_codex
from middle_man.gateway.codex_runner.execution import DEFAULT_TIMEOUT, run_codex
from middle_man.gateway.codex_runner.audit import save_audit


def add_codex_run_command(actions: argparse._SubParsersAction) -> None:
    run = actions.add_parser("run", help="prepare or run one Codex task in the current repository")
    run.add_argument("task", help="quoted user task; preserved exactly in the Codex prompt")
    run.add_argument("--repo", type=Path, default=Path("."))
    modes = run.add_mutually_exclusive_group(required=True)
    modes.add_argument("--read-only", action="store_true")
    modes.add_argument("--workspace-write", action="store_true")
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--effort", choices=EFFORTS, default=DEFAULT_EFFORT)
    execution = run.add_mutually_exclusive_group(required=True)
    execution.add_argument("--dry-run", action="store_true", help="preview without a Codex model call")
    execution.add_argument("--confirm-external-service", action="store_true",
                           help="send the task and optional source-free locator to Codex")
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                     help="Codex process timeout in seconds (default: 360)")
    run.add_argument("--json", action="store_true", help="print source-free audit JSON")
    run.add_argument("--save-audit", action="store_true",
                     help="save sanitized production metadata under .middle_man_cache/codex_runs")


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


def run_codex_command(args: argparse.Namespace) -> None:
    if args.dry_run:
        if args.save_audit:
            raise SystemExit("--save-audit requires --confirm-external-service")
        run_codex_preview(args)
        return
    try:
        result = run_codex(args.repo, args.task,
                           mode="read-only" if args.read_only else "workspace-write",
                           confirm_external_service=args.confirm_external_service,
                           model=args.model, effort=args.effort, timeout=args.timeout)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    audit_path = None
    audit_error = None
    if args.save_audit:
        try:
            audit_path = save_audit(result)
        except (OSError, ValueError) as exc:
            audit_error = str(exc)
    if args.json:
        print(json.dumps({**result.audit_dict(), "final_message": result.final_message,
                          "saved_audit_path": str(audit_path) if audit_path else None,
                          "audit_error": audit_error}, indent=2))
    else:
        print("MIDDLE_MAN CODEX")
        print(f"Run ID: {result.run_id}")
        print(f"Mode: {result.audit.task_mode}")
        print(f"AUTO: {result.audit.decision} ({result.audit.decision_reason})")
        print(f"Model-visible Middle_Man content: {result.audit.model_visible_middle_man_tokens:,} heuristic tokens")
        print(f"Codex: {result.audit.codex_version}")
        print(f"Model: {result.audit.requested_model}; effort: {result.audit.requested_effort}")
        print(f"Elapsed: {result.elapsed_seconds:.3f} s")
        print(f"Exit: {result.exit_code if result.exit_code is not None else 'unavailable'}; status: {result.status}")
        print(f"Usage (input/cached/output/reasoning): {result.input_tokens} / {result.cached_input_tokens} / "
              f"{result.output_tokens} / {result.reasoning_output_tokens}")
        print(f"Native calls: {result.native_tool_calls}; explicit reads: {result.explicit_reads}; "
              f"unique files: {len(result.unique_files)}; rereads: {result.rereads}; "
              f"searches: {result.search_calls}; listings: {result.listing_calls}")
        print(f"Content-producing searches: {result.content_search_calls}; "
              f"file-targeted: {result.file_targeted_searches}; "
              f"repository-wide: {result.repository_wide_searches}; "
              f"file-listing searches: {result.file_listing_searches}")
        if result.audit.decision == "LOCATOR USED":
            total = len(result.audit.selected_paths)
            print(f"Locator paths explicitly read: {len(result.locator_paths_explicitly_read)}/{total}; "
                  f"targeted by searches: {len(result.locator_paths_searched)}/{total}; "
                  f"non-locator search targets: {len(result.non_locator_paths_searched)}")
        print(f"Repository unchanged: {'YES' if result.repository_unchanged else 'NO'}")
        if audit_path:
            print(f"Audit: {audit_path}")
        if audit_error:
            print(f"Audit save failed: {audit_error}")
        if result.failure_reasons:
            print("Failure reasons: " + ", ".join(result.failure_reasons))
        print()
        print(result.final_message)
    if result.status != "SUCCESS" or audit_error:
        raise SystemExit(1)
