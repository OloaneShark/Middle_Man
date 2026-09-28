"""Official MCP SDK stdio server for a single explicit repository root."""

from __future__ import annotations

from importlib.metadata import version
from typing import Any, Callable

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.source import StaleSourceError, UnsafeSourceError
from middle_man.gateway.state_store import StateStoreError
from middle_man.mcp.gateway import MCPGateway

SERVER_NAME = "middle-man"
SERVER_INSTRUCTIONS = (
    "Use Middle_Man before broad repository scans when repository context is needed. "
    "Check the latest handoff or project state, find relevant paths, build a bounded SAFE or BALANCED "
    "Context Pack, and expand only where needed. Compact large tool output. Native repository reads "
    "remain available when context is insufficient, stale, or the exact full source is needed; correctness comes first."
)


def create_server(config: GatewayConfig) -> MCPServer:
    gateway = MCPGateway(config)
    server = MCPServer(SERVER_NAME, version=version("middle-man"), instructions=SERVER_INSTRUCTIONS,
                       log_level="WARNING")
    annotation = ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False)

    def invoke(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except (StaleSourceError, UnsafeSourceError) as exc:
            raise ToolError(f"Source cannot be served safely: {exc}. Rebuild the Context Pack or use a native read.") from exc
        except StateStoreError as exc:
            raise ToolError("Local Middle_Man state is corrupt or unsafe; inspect it with the Middle_Man CLI.") from exc
        except ValueError as exc:
            message = gateway.redactor.redact(str(exc)).text.replace(str(config.repository_root), "<repository>")
            raise ToolError(message) from exc

    @server.tool(annotations=annotation)
    def middleman_project_state() -> dict[str, Any]:
        """Current compact repository facts, decisions, and open issues; use for orientation, not source text."""
        return invoke(gateway.project_state)

    @server.tool(annotations=annotation)
    def middleman_session_handoff() -> dict[str, Any]:
        """Latest factual task handoff and stale status; use when continuing work, not as inferred intent."""
        return invoke(gateway.session_handoff)

    @server.tool(annotations=annotation)
    def middleman_find_context(task: str, top_k: int | None = None, error_text: str = "",
                               paths: list[str] | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
        """Rank relevant paths, symbols, and reasons without source; use to decide where to look, not to read code."""
        return invoke(lambda: gateway.find_context(task, top_k=top_k, error_text=error_text,
                                                   paths=paths, symbols=symbols))

    @server.tool(annotations=annotation)
    def middleman_context_pack(task: str, mode: str = "safe", max_context_tokens: int = 6000,
                               top_k: int | None = None, error_text: str = "", paths: list[str] | None = None,
                               symbols: list[str] | None = None) -> dict[str, Any]:
        """Build bounded, source-verified and redacted excerpts; use for exact context, not a whole-repo dump."""
        return invoke(lambda: gateway.context_pack(task, mode=mode, max_context_tokens=max_context_tokens,
                                                   top_k=top_k, error_text=error_text, paths=paths, symbols=symbols))

    @server.tool(annotations=annotation)
    def middleman_expand_context(fingerprint: str, kind: str, target: str | None = None,
                                 context_lines: int = 3, max_context_tokens: int | None = None) -> dict[str, Any]:
        """Expand a prior Context Pack by file, symbol, imports, tests, or lines; use only when initial excerpts lack detail."""
        return invoke(lambda: gateway.expand_context(fingerprint, kind, target=target,
                                                     context_lines=context_lines, max_context_tokens=max_context_tokens))

    @server.tool(annotations=annotation)
    def middleman_changed_context(path: str | None = None) -> dict[str, Any]:
        """Current Git change paths, status, symbols, and hunk ranges; use for change awareness, not raw patch text."""
        return invoke(lambda: gateway.changed_context(path))

    @server.tool(annotations=annotation)
    def middleman_compact_output(output_type: str, text: str = "", max_tokens: int = 1200) -> dict[str, Any]:
        """Redact and condense supplied pytest/log/Docker/Git-status text or current Git diff; use for large output, not tiny results."""
        return invoke(lambda: gateway.compact_output(output_type, text, max_tokens=max_tokens))

    @server.tool(annotations=annotation)
    def middleman_context_stats(fingerprint: str | None = None, task: str | None = None,
                                mode: str = "safe", max_context_tokens: int = 6000) -> dict[str, Any]:
        """Estimated Context Pack sizes and reduction; use for local context accounting, not Codex billing or quota."""
        return invoke(lambda: gateway.context_stats(fingerprint=fingerprint, task=task, mode=mode,
                                                    max_context_tokens=max_context_tokens))

    @server.tool(annotations=annotation)
    def middleman_explain_selection(task: str, path: str | None = None, top_k: int = 10) -> dict[str, Any]:
        """Deterministic ranking reasons for a task/path; use to audit selection, not as proof of developer intent."""
        return invoke(lambda: gateway.explain_selection(task, path=path, top_k=top_k))

    @server.tool(annotations=annotation)
    def middleman_repo_map() -> dict[str, Any]:
        """Bounded language, component, symbol and relationship counts; use for structure, not complete file listings."""
        return invoke(gateway.repo_map)

    return server


def serve(config: GatewayConfig) -> None:
    create_server(config).run(transport="stdio")
