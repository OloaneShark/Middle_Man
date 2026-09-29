"""Explicit, isolated CLI for real Codex context benchmarks."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from middle_man.gateway.codex_benchmark.runner import (
    DEFAULT_EFFORT, DEFAULT_MODEL, DEFAULT_TIMEOUT, build_invocation, format_report, load_suite, run_suite,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS


def add_codex_benchmark_commands(subparsers: argparse._SubParsersAction) -> None:
    codex = subparsers.add_parser("codex", help="real Codex integration measurements")
    codex_commands = codex.add_subparsers(dest="codex_action", required=True)
    benchmark = codex_commands.add_parser("benchmark", help="isolated Codex A/B context benchmark")
    actions = benchmark.add_subparsers(dest="benchmark_action", required=True)
    listing = actions.add_parser("list", help="list the three benchmark tasks")
    listing.add_argument("--json", action="store_true")
    for name in ("run", "run-all"):
        action = actions.add_parser(name, help="run one pair" if name == "run" else "run all three pairs")
        if name == "run":
            action.add_argument("task", choices=[task.id for task in TASKS])
        action.add_argument("--repo", type=Path, default=Path("."))
        action.add_argument("--model", default=DEFAULT_MODEL)
        action.add_argument("--effort", default=DEFAULT_EFFORT)
        action.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
        action.add_argument("--dry-run", action="store_true")
        action.add_argument("--confirm-external-service", action="store_true")
    for name in ("report", "overlap"):
        action = actions.add_parser(name, help="read a completed local benchmark artifact")
        action.add_argument("run_id")
        action.add_argument("--repo", type=Path, default=Path("."))
        action.add_argument("--json", action="store_true")


def run_codex_benchmark(args: argparse.Namespace) -> None:
    action = args.benchmark_action
    if action == "list":
        data = [{"id": task.id, "title": task.title, "read_only": task.read_only} for task in TASKS]
        print(json.dumps(data, indent=2) if args.json else "\n".join(
            f"{item['id']}: {item['title']} ({'read-only' if item['read_only'] else 'edit'})" for item in data))
        return
    root = args.repo.resolve()
    if action in {"report", "overlap"}:
        data = load_suite(root, args.run_id)
        if action == "report":
            print(json.dumps(data, indent=2) if args.json else format_report(data))
        else:
            overlap = {pair["task_id"]: pair["optimized"]["context"] for pair in data["pairs"]}
            print(json.dumps(overlap, indent=2) if args.json else "\n".join(
                f"{name}: overlap={item['overlap_ratio']} repeated_bytes={item['repeated_source_bytes']} "
                f"unique_bytes={item['unique_source_bytes']}" for name, item in overlap.items()))
        return
    tasks = TASKS if action == "run-all" else tuple(task for task in TASKS if task.id == args.task)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    base = root / ".middle_man_cache" / "codex_benchmarks"
    if args.dry_run:
        print("DRY RUN: no Codex call or snapshot write")
        print("Real runs disclose repository-derived context to the external Codex service.")
        print(f"Model: {args.model}  reasoning effort: {args.effort} (explicit CLI configuration)")
        print(f"Artifact root: {base / '<run-id>'}")
        snapshot_base = Path(tempfile.gettempdir()) / "middle-man-codex-<run-id>"
        print(f"Independent working-copy root: {snapshot_base}")
        for index, task in enumerate(tasks):
            first = "optimized" if index % 2 else "baseline"
            print(f"Task: {task.id}  source: {task.source}  order: {first}, {'baseline' if first == 'optimized' else 'optimized'}")
            for mode in ("baseline", "optimized"):
                snapshot = snapshot_base / task.id / mode
                print(f"  {mode} snapshot: {snapshot}")
                print("  " + subprocess.list2cmdline(build_invocation("codex", task, mode, snapshot,
                                                            model=args.model, effort=args.effort)))
        print("Both runs ignore user config; baseline has no AGENTS.md or Middle_Man registration; optimized configures snapshot-scoped MCP.")
        return
    if not args.confirm_external_service:
        raise SystemExit("Real Codex runs send repository-derived context to the external Codex service. "
                         "Review --dry-run, then pass --confirm-external-service explicitly.")
    print("Running real Codex benchmark; repository-derived context will reach the external Codex service.", flush=True)
    suite = run_suite(tuple(task.id for task in tasks), repository_root=root, artifact_base=base,
                      model=args.model, effort=args.effort, timeout=args.timeout)
    print(format_report(asdict(suite)))
    print(f"Local sanitized artifacts: {suite.artifact_root}")
