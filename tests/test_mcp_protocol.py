from __future__ import annotations

import asyncio
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from middle_man.gateway.config import GatewayConfig
from tests.test_mcp_gateway import repo  # noqa: F401

mcp = pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters
from middle_man.mcp.server import create_server


EXPECTED_TOOLS = {
    "middleman_project_state",
    "middleman_session_handoff",
    "middleman_find_context",
    "middleman_context_pack",
    "middleman_expand_context",
    "middleman_changed_context",
    "middleman_compact_output",
    "middleman_context_stats",
    "middleman_explain_selection",
    "middleman_repo_map",
}


async def _exercise(client: Client) -> None:
    async with client:
        assert client.server_info is not None
        assert client.server_info.name == "middle-man"
        assert client.server_info.version == version("middle-man")
        listing = await client.list_tools()
        assert {tool.name for tool in listing.tools} == EXPECTED_TOOLS
        assert all(tool.annotations and tool.annotations.read_only_hint for tool in listing.tools)

        found = await client.call_tool("middleman_find_context", {"task": "AuthService.login"})
        assert not found.is_error
        assert found.structured_content["ranked_files"][0]["path"] == "auth.py"

        pack = await client.call_tool("middleman_context_pack", {
            "task": "AuthService.login", "max_context_tokens": 600,
        })
        assert not pack.is_error
        assert "auth.py" in pack.structured_content["selected_paths"]
        assert "fixture-secret-895731" not in str(pack)

        stats = await client.call_tool("middleman_context_stats", {
            "fingerprint": pack.structured_content["fingerprint"],
        })
        assert not stats.is_error
        assert stats.structured_content["estimated_selected_tokens"] <= 600

        changed = await client.call_tool("middleman_changed_context", {})
        assert not changed.is_error
        assert any(item["path"] == "auth.py" for item in changed.structured_content["changed_files"])


def test_in_memory_protocol(repo: Path) -> None:
    asyncio.run(_exercise(Client(create_server(GatewayConfig(repo)), raise_exceptions=True)))


def test_real_stdio_protocol(repo: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "middle_man", "mcp", "serve", "--repo", str(repo)],
    )
    asyncio.run(_exercise(Client(params, raise_exceptions=True, read_timeout_seconds=15)))
