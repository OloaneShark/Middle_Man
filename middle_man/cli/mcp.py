"""CLI entry points for the optional local MCP server and usage metrics."""

from __future__ import annotations

import argparse
import json
from importlib.util import find_spec
from pathlib import Path

from middle_man.gateway.config import GatewayConfig
from middle_man.mcp.usage import MCPUsageLog


def add_mcp_commands(subparsers: argparse._SubParsersAction) -> None:
    mcp = subparsers.add_parser("mcp", help="local MCP server and estimated usage metrics")
    actions = mcp.add_subparsers(dest="mcp_action", required=True)
    serve = actions.add_parser("serve", help="serve one explicit repository over stdio")
    serve.add_argument("--repo", type=Path, required=True)
    serve.add_argument("--tool-profile", choices=("codex-core", "full"), default="codex-core")
    serve.add_argument("--benchmark-run-id")
    serve.add_argument("--benchmark-task-id")
    serve.add_argument("--benchmark-mode", choices=("baseline", "optimized"))
    serve.add_argument("--benchmark-source-commit")
    serve.add_argument("--benchmark-context-budget", type=int)
    serve.add_argument("--benchmark-source-delivery-budget", type=int)
    serve.add_argument("--benchmark-expansion-budget", type=int)
    usage = actions.add_parser("usage", help="show local MCP invocation counts and estimates")
    usage.add_argument("--repo", type=Path, required=True)
    usage.add_argument("--json", action="store_true")


def run_mcp(args: argparse.Namespace) -> None:
    config = GatewayConfig(args.repo)
    if args.mcp_action == "usage":
        result = MCPUsageLog(config).summary()
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print("MIDDLE_MAN MCP USAGE (local estimates; not Codex/provider usage)")
            print(f"Calls: {result['total_calls']}  Errors: {result['errors']}")
            for name, count in result["calls_by_tool"].items():
                print(f"{name}: {count}")
            print(f"Context Packs: {result['context_packs_built']}  Expansions: {result['expansions']}")
            print(f"Estimated tokens: {result['estimated_context_tokens']}")
        return
    if find_spec("mcp") is None:
        raise SystemExit('MCP support is optional. Install it with: pip install -e ".[mcp]"')
    from middle_man.mcp.benchmark_receipts import BenchmarkIdentity, BenchmarkPolicy
    from middle_man.mcp.server import serve

    values = (args.benchmark_run_id, args.benchmark_task_id, args.benchmark_mode,
              args.benchmark_source_commit)
    if any(values) and not all(values):
        raise SystemExit("benchmark identity requires run ID, task ID, mode, and source commit")
    if not all(values) and (args.benchmark_context_budget is not None or
                            args.benchmark_source_delivery_budget is not None or
                            args.benchmark_expansion_budget is not None):
        raise SystemExit("benchmark budgets require a complete benchmark identity")
    try:
        policy = BenchmarkPolicy(
            initial_context_budget=6000 if args.benchmark_context_budget is None else args.benchmark_context_budget,
            expansion_ceiling=12000 if args.benchmark_expansion_budget is None else args.benchmark_expansion_budget,
            initial_source_delivery_budget=args.benchmark_source_delivery_budget)
        identity = BenchmarkIdentity(*values, policy=policy) if all(values) else None
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    serve(config, tool_profile=args.tool_profile, benchmark_identity=identity)
