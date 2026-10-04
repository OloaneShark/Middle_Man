"""Dry-run Claude Code benchmark commands. No inference execution path exists."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from middle_man.gateway.claude_benchmark.infrastructure import (
    discover_cli, memory_contamination, user_memory_presence,
)
from middle_man.gateway.claude_benchmark.runner import MODES, preview_pair
from middle_man.gateway.claude_benchmark.runtime_probe import run_runtime_probes
from middle_man.gateway.codex_benchmark.tasks import TASKS


_SUPPORTED = tuple(task for task in TASKS if task.id in
                   {"preemption-v4", "oauth-bug", "upload-feature", "large-edit-v1"})


def add_claude_benchmark_commands(subparsers: argparse._SubParsersAction) -> None:
    claude = subparsers.add_parser("claude", help="local Claude Code integration previews")
    benchmark = claude.add_subparsers(dest="claude_action", required=True).add_parser(
        "benchmark", help="dry-run-only offline A/B preparation")
    actions = benchmark.add_subparsers(dest="claude_benchmark_action", required=True)
    actions.add_parser("list", help="list frozen supported tasks")
    preflight = actions.add_parser("preflight", help="inspect installed CLI and memory without inference")
    preflight.add_argument("--snapshot-root", type=Path)
    run = actions.add_parser("run", help="construct a local preview only")
    run.add_argument("task", choices=[task.id for task in _SUPPORTED])
    run.add_argument("--repo", type=Path, default=Path("."))
    run.add_argument("--model", default="sonnet")
    run.add_argument("--optimized-mode", choices=MODES, default="offline-auto")
    run.add_argument("--max-turns", type=int)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--confirm-external-service", action="store_true")
    report = actions.add_parser("report", help="read a saved local preview")
    report.add_argument("run_id")
    report.add_argument("--repo", type=Path, default=Path("."))
    probe = actions.add_parser("runtime-probe", help="isolated protocol checks, never benchmark tasks")
    probe.add_argument("--repo", type=Path, default=Path("."))
    probe.add_argument("--dry-run", action="store_true")
    probe.add_argument("--confirm-external-service", action="store_true")


def run_claude_benchmark(args: argparse.Namespace) -> None:
    action = args.claude_benchmark_action
    if action == "list":
        for task in _SUPPORTED:
            print(f"{task.id}: {task.title} ({'read-only' if task.read_only else 'edit'})")
        return
    if action == "preflight":
        cli = discover_cli()
        parent = (args.snapshot_root or Path(tempfile.gettempdir())).resolve()
        issues = memory_contamination(parent)
        print(json.dumps({**asdict(cli), "ready": cli.ready,
                          "snapshot_parent": str(parent),
                          "project_memory_paths": [str(path) for path in issues],
                          "user_memory_paths": user_memory_presence(Path.home()),
                          "user_memory_isolation": "safe-mode disables CLAUDE.md discovery; "
                                                   "restricted ignores user/project/local settings; "
                                                   "managed policy and runtime enforcement remain unverified",
                          "mcp_isolation": "safe-mode disables MCP; strict-mcp-config ignores inherited MCP",
                          "inference_enabled": False}, indent=2))
        if not cli.ready or issues:
            raise SystemExit(1)
        return
    root = args.repo.resolve()
    if action == "runtime-probe":
        if not args.dry_run and not args.confirm_external_service:
            raise SystemExit("Claude runtime probes call an external model; pass --confirm-external-service")
        cli = discover_cli()
        try:
            result = run_runtime_probes(root, cli, confirmed=args.confirm_external_service,
                                        dry_run=args.dry_run,
                                        artifact_root=root / ".middle_man_cache" / "claude_runtime_probes")
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, indent=2))
        if not args.dry_run and any(probe.get("status") != "PASS" for probe in result["probes"]):
            raise SystemExit(1)
        return
    if action == "report":
        if not args.run_id or not all(char.isalnum() or char in "-_" for char in args.run_id):
            raise SystemExit("invalid preview run ID")
        path = root / ".middle_man_cache" / "claude_benchmarks" / args.run_id / "preview.json"
        if not path.is_file():
            raise SystemExit(f"Claude preview not found: {args.run_id}")
        print(path.read_text(encoding="utf-8"))
        return
    if not args.dry_run:
        raise SystemExit("Phase 23 is dry-run-only; --confirm-external-service cannot enable inference")
    if not args.model.strip() or args.max_turns is not None and args.max_turns < 1:
        raise SystemExit("model must be nonempty and max-turns must be positive if supplied")
    cli = discover_cli()
    task = next(item for item in _SUPPORTED if item.id == args.task)
    try:
        with tempfile.TemporaryDirectory(prefix="middle-man-claude-preview-") as temporary:
            preview = preview_pair(task, Path(temporary) / "pair", cli, model=args.model,
                                   mode=args.optimized_mode, max_turns=args.max_turns)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    run_id = uuid4().hex
    path = root / ".middle_man_cache" / "claude_benchmarks" / run_id / "preview.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    data = {"run_id": run_id, "dry_run": True, "cli_version": cli.version, "cli_error": cli.error,
            "claude_invocation_shape": "claude -p <redacted prompt> --output-format stream-json --verbose "
                                       "--safe-mode --restricted --strict-mcp-config "
                                       "[--no-session-persistence] --model <configured model> "
                                       "--tools <permission profile> [--max-turns N]",
            **asdict(preview)}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2))
