"""Heuristic sizes of official MCP SDK tool definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.server import create_server


@dataclass(frozen=True, slots=True)
class MCPToolMetric:
    name: str
    description_tokens: int
    input_schema_tokens: int
    definition_tokens: int


@dataclass(frozen=True, slots=True)
class MCPToolSurfaceMetrics:
    profile: str
    tool_count: int
    total_definition_tokens: int
    tools: tuple[MCPToolMetric, ...]
    basis: str = "ceil(UTF-8 bytes / 4) of MCP SDK tool-list JSON; not Codex input usage"


async def measure_tool_surface(config: GatewayConfig, profile: str) -> MCPToolSurfaceMetrics:
    estimator = HeuristicTokenEstimator()
    tools = await create_server(config, tool_profile=profile).list_tools()
    values = []
    for tool in tools:
        wire = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        compact = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        values.append(MCPToolMetric(tool.name, estimator.estimate(tool.description or ""),
                                    estimator.estimate(compact(wire.get("inputSchema", {}))),
                                    estimator.estimate(compact(wire))))
    return MCPToolSurfaceMetrics(profile, len(values), sum(item.definition_tokens for item in values),
                                 tuple(values))
