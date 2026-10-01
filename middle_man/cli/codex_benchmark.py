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
from middle_man.gateway.codex_benchmark.offline_locator import build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.codex_benchmark.infrastructure import run_local_preflight
from middle_man.mcp.benchmark_receipts import BenchmarkPolicy


def add_codex_benchmark_commands(subparsers: argparse._SubParsersAction) -> None:
    codex = subparsers.add_parser("codex", help="real Codex integration measurements")
    codex_commands = codex.add_subparsers(dest="codex_action", required=True)
    benchmark = codex_commands.add_parser("benchmark", help="isolated Codex A/B context benchmark")
    actions = benchmark.add_subparsers(dest="benchmark_action", required=True)
    listing = actions.add_parser("list", help="list versioned benchmark tasks")
    listing.add_argument("--json", action="store_true")
    preflight = actions.add_parser("preflight", help="check local Codex sandbox and MCP infrastructure without inference")
    preflight.add_argument("--repo", type=Path, default=Path("."))
    preflight.add_argument("--model", default=DEFAULT_MODEL)
    preflight.add_argument("--effort", default=DEFAULT_EFFORT)
    preflight.add_argument("--windows-sandbox", choices=("elevated", "unelevated"), default="elevated")
    preflight.add_argument("--snapshot-root", type=Path)
    preflight.add_argument("--json", action="store_true")
    preflight.add_argument("--optimized-mode", choices=("mcp", "offline-locator"), default="mcp")
    for name in ("run", "run-all"):
        action = actions.add_parser(name, help="run one pair" if name == "run" else "run all three pairs")
        if name == "run":
            action.add_argument("task", choices=[task.id for task in TASKS])
        action.add_argument("--repo", type=Path, default=Path("."))
        action.add_argument("--model", default=DEFAULT_MODEL)
        action.add_argument("--effort", default=DEFAULT_EFFORT)
        action.add_argument("--windows-sandbox", choices=("elevated", "unelevated"), default="elevated")
        action.add_argument("--snapshot-root", type=Path)
        action.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
        action.add_argument("--benchmark-source-delivery-budget", type=int)
        action.add_argument("--benchmark-delivery-policy", choices=("locator-only",))
        action.add_argument("--optimized-mode", choices=("mcp", "offline-locator"), default="mcp")
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
        data = [{"id": task.id, "title": task.title, "read_only": task.read_only, "task_version": task.schema_version} for task in TASKS]
        print(json.dumps(data, indent=2) if args.json else "\n".join(
            f"{item['id']}: {item['title']} ({'read-only' if item['read_only'] else 'edit'})" for item in data))
        return
    root = args.repo.resolve()
    if action == "preflight":
        result = run_local_preflight("codex", model=args.model, effort=args.effort,
                                     windows_sandbox=args.windows_sandbox, snapshot_root=args.snapshot_root,
                                     repository_root=root, optimized_mode=args.optimized_mode)
        data = asdict(result)
        print(json.dumps(data, indent=2) if args.json else "\n".join(
            f"{key}: {value}" for key, value in data.items()))
        if not result.passed:
            raise SystemExit(1)
        return
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
    tasks = (tuple(next(task for task in TASKS if task.id == task_id)
                   for task_id in ("preemption-v4", "oauth-bug", "upload-feature"))
             if action == "run-all" else tuple(task for task in TASKS if task.id == args.task))
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    try:
        policy = BenchmarkPolicy(initial_source_delivery_budget=args.benchmark_source_delivery_budget,
                                 delivery_policy="locator_only" if args.benchmark_delivery_policy == "locator-only" else None)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.optimized_mode == "offline-locator" and (len(tasks) != 1 or tasks[0].id != "preemption-v4" or
            policy != BenchmarkPolicy()):
        raise SystemExit("offline-locator requires only preemption-v4 without MCP delivery-policy flags")
    base = root / ".middle_man_cache" / "codex_benchmarks"
    if args.dry_run:
        print("DRY RUN: no Codex call or persistent snapshot write")
        print("Real runs disclose repository-derived context to the external Codex service.")
        print(f"Model: {args.model}  reasoning effort: {args.effort} (explicit CLI configuration)")
        print(f"Windows sandbox: {args.windows_sandbox} (explicit; no automatic fallback)")
        if args.optimized_mode == "offline-locator":
            print("Delivery policy: offline-locator prompt metadata; canonical selection: BALANCED/6000; "
                  "initial MCP source delivery: none")
        else:
            print(f"Delivery policy: {policy.delivery_mode.replace('_', '-')}; "
                  f"canonical selection: {policy.initial_context_budget}; "
                  f"initial source delivery: {policy.initial_source_delivery_budget}; "
                  f"expansion ceiling: {policy.expansion_ceiling}")
        print(f"Optimized mode: {args.optimized_mode}")
        print(f"Artifact root: {base / '<run-id>'}")
        snapshot_base = (args.snapshot_root.resolve() if args.snapshot_root else Path(tempfile.gettempdir())) / "middle-man-codex-<run-id>"
        print(f"Independent working-copy root: {snapshot_base}")
        offline_locator = None
        if args.optimized_mode == "offline-locator":
            with tempfile.TemporaryDirectory(prefix="middle-man-offline-preview-") as temporary:
                _, preview_root, _ = prepare_pair(tasks[0], Path(temporary) / "pair", None)
                offline_locator = build_offline_locator(GatewayConfig(preview_root), ContextQuery(tasks[0].prompt))
            print(f"Offline locator: {offline_locator.estimated_tokens} heuristic tokens; "
                  f"canonical source: {offline_locator.selected_source_tokens}; hash: {offline_locator.sha256}")
            print(offline_locator.text)
        for index, task in enumerate(tasks):
            first = "optimized" if index % 2 else "baseline"
            print(f"Task: {task.id}  source: {task.source}  order: {first}, {'baseline' if first == 'optimized' else 'optimized'}")
            for mode in ("baseline", "optimized"):
                snapshot = snapshot_base / task.id / mode
                print(f"  {mode} snapshot: {snapshot}")
                if mode == "optimized" and args.optimized_mode == "mcp":
                    server_budgets = (f"--benchmark-context-budget {policy.initial_context_budget} "
                                      + (f"--benchmark-source-delivery-budget {policy.initial_source_delivery_budget} "
                                         if policy.initial_source_delivery_budget is not None else "")
                                      + ("--benchmark-delivery-policy locator-only " if policy.delivery_mode == "locator_only" else "")
                                      + f"--benchmark-expansion-budget {policy.expansion_ceiling}")
                    print(f"  optimized MCP policy args: {server_budgets}")
                print("  " + subprocess.list2cmdline(build_invocation("codex", task, mode, snapshot,
                                                            model=args.model, effort=args.effort,
                                                            windows_sandbox=args.windows_sandbox,
                                                            run_id="dry-run", policy=policy,
                                                            optimized_mode=args.optimized_mode,
                                                            locator_text=offline_locator.text if mode == "optimized" and offline_locator else None)))
        if args.optimized_mode == "offline-locator":
            print("Both runs ignore user config and have no AGENTS.md or MCP registration; preprocessing is outside Codex.")
        else:
            print("Both runs ignore user config; baseline has no AGENTS.md or Middle_Man registration; optimized configures snapshot-scoped MCP.")
        return
    if not args.confirm_external_service:
        raise SystemExit("Real Codex runs send repository-derived context to the external Codex service. "
                         "Review --dry-run, then pass --confirm-external-service explicitly.")
    print("Running real Codex benchmark; repository-derived context will reach the external Codex service.", flush=True)
    suite = run_suite(tuple(task.id for task in tasks), repository_root=root, artifact_base=base,
                      model=args.model, effort=args.effort, timeout=args.timeout, windows_sandbox=args.windows_sandbox,
                      snapshot_root=args.snapshot_root, policy=policy, optimized_mode=args.optimized_mode)
    print(format_report(asdict(suite)))
    print(f"Local sanitized artifacts: {suite.artifact_root}")
