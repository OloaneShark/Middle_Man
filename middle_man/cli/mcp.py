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
    from middle_man.mcp.server import serve

    serve(config, tool_profile=args.tool_profile)
