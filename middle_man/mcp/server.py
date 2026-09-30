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
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity

SERVER_NAME = "middle-man"
CORE_INSTRUCTIONS = (
    "For a fresh scoped repository task, call middleman_context with the concrete engineering request, "
    "including relevant behaviors or symbols. For missing detail on the same task, prefer "
    "middleman_expand_context on the existing fingerprint. Call middleman_context again when intent "
    "materially changes or a new selection is needed. Use middleman_session_handoff for continuation, "
    "middleman_project_state for broad orientation, and middleman_compact_output for large output. "
    "Native search and reads remain valid for exact, missing, or stale source."
)
FULL_INSTRUCTIONS = (
    "Full diagnostic Middle_Man profile: find_context ranks without source; context_pack "
    "builds a rich bounded source pack; expand_context adds detail. Native reads and tests "
    "remain available for exact or missing context."
)

def create_server(config: GatewayConfig, tool_profile: str = "full",
                  benchmark_identity: BenchmarkIdentity | None = None) -> MCPServer:
    if tool_profile not in {"full", "codex-core"}:
        raise ValueError("tool_profile must be full or codex-core")
    gateway = MCPGateway(config, benchmark_identity=benchmark_identity)
    server = MCPServer(SERVER_NAME, version=version("middle-man"), instructions=CORE_INSTRUCTIONS if tool_profile == "codex-core" else FULL_INSTRUCTIONS,
                       log_level="WARNING")
    annotation = ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False)

    def full_only(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        return server.tool(annotations=annotation)(func) if tool_profile == "full" else func

    def core_only(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        return server.tool(annotations=annotation)(func) if tool_profile == "codex-core" else func

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

    @full_only
    def middleman_find_context(task: str, top_k: int | None = None, error_text: str = "",
                               paths: list[str] | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
        """Rank relevant paths, symbols, and reasons without source; use to decide where to look, not to read code."""
        return invoke(lambda: gateway.find_context(task, top_k=top_k, error_text=error_text,
                                                   paths=paths, symbols=symbols))

    @full_only
    def middleman_context_pack(task: str, mode: str = "safe", max_context_tokens: int = 6000,
                               top_k: int | None = None, error_text: str = "", paths: list[str] | None = None,
                               symbols: list[str] | None = None) -> dict[str, Any]:
        """Build bounded, source-verified and redacted excerpts; use for exact context, not a whole-repo dump."""
        return invoke(lambda: gateway.context_pack(task, mode=mode, max_context_tokens=max_context_tokens,
                                                   top_k=top_k, error_text=error_text, paths=paths, symbols=symbols))

    @core_only
    def middleman_context(task: str, mode: str = "balanced", max_context_tokens: int = 6000,
                          error_text: str = "", paths: list[str] | None = None,
                          symbols: list[str] | None = None, force_replay: bool = False) -> dict[str, Any]:
        """Initial scoped source selection for a concrete task; expand an existing fingerprint for missing detail. A new task may need a new context call; force_replay resends prior source."""
        return invoke(lambda: gateway.context(task, mode=mode, max_context_tokens=max_context_tokens,
                                              error_text=error_text, paths=paths, symbols=symbols,
                                              force_replay=force_replay))

    @server.tool(annotations=annotation)
    def middleman_expand_context(fingerprint: str, kind: str, target: str | None = None,
                                 context_lines: int = 3, max_context_tokens: int | None = None) -> dict[str, Any]:
        """Get missing source from a partial Context Pack; native reads remain valid for exact or stale source."""
        return invoke(lambda: gateway.expand_context(fingerprint, kind, target=target, core=tool_profile == "codex-core",
                                                     context_lines=context_lines, max_context_tokens=max_context_tokens))

    @full_only
    def middleman_changed_context(path: str | None = None) -> dict[str, Any]:
        """Current Git change paths, status, symbols, and hunk ranges; use for change awareness, not raw patch text."""
        return invoke(lambda: gateway.changed_context(path))

    @server.tool(annotations=annotation)
    def middleman_compact_output(output_type: str, text: str = "", max_tokens: int = 1200) -> dict[str, Any]:
        """Redact and condense supplied pytest/log/Docker/Git-status text or current Git diff; use for large output, not tiny results."""
        return invoke(lambda: gateway.compact_output(output_type, text, max_tokens=max_tokens))

    @full_only
    def middleman_context_stats(fingerprint: str | None = None, task: str | None = None,
                                mode: str = "safe", max_context_tokens: int = 6000) -> dict[str, Any]:
        """Estimated Context Pack sizes and reduction; use for local context accounting, not Codex billing or quota."""
        return invoke(lambda: gateway.context_stats(fingerprint=fingerprint, task=task, mode=mode,
                                                    max_context_tokens=max_context_tokens))

    @full_only
    def middleman_explain_selection(task: str, path: str | None = None, top_k: int = 10) -> dict[str, Any]:
        """Deterministic ranking reasons for a task/path; use to audit selection, not as proof of developer intent."""
        return invoke(lambda: gateway.explain_selection(task, path=path, top_k=top_k))

    @full_only
    def middleman_repo_map() -> dict[str, Any]:
        """Bounded language, component, symbol and relationship counts; use for structure, not complete file listings."""
        return invoke(gateway.repo_map)

    return server


def serve(config: GatewayConfig, tool_profile: str = "codex-core",
          benchmark_identity: BenchmarkIdentity | None = None) -> None:
    create_server(config, tool_profile=tool_profile, benchmark_identity=benchmark_identity).run(transport="stdio")
