"""Per-process production policy for Codex's native repository tools."""

from __future__ import annotations


PRODUCTION_EXTERNAL_TOOL_POLICY = "LOCAL_NATIVE_ONLY"
PRODUCTION_ISOLATION_OVERRIDES = ("features.apps=false", "features.plugins=false")


def isolation_arguments() -> tuple[str, ...]:
    return tuple(part for override in PRODUCTION_ISOLATION_OVERRIDES for part in ("-c", override))


def verify_isolation_command(command: tuple[str, ...], *,
                             research_windows_sandbox: str | None = None) -> None:
    """Fail before spawning if the production command loses its isolation contract."""
    options = command[:-1]
    if ("--ignore-user-config" not in options or "--strict-config" not in options
            or "--no-daemon" not in options or "--ephemeral" not in options
            or "--enable" in options or "--config" in options):
        raise RuntimeError("production Codex isolation command is incomplete")
    overrides = [options[index + 1] for index, part in enumerate(options[:-1]) if part == "-c"]
    for name in ("apps", "plugins"):
        if sum(value.startswith(f"features.{name}=") for value in overrides) != 1:
            raise RuntimeError("production Codex isolation command is incomplete")
    if (any(value not in overrides for value in PRODUCTION_ISOLATION_OVERRIDES)
            or any(value.startswith("mcp_servers.") for value in overrides)):
        raise RuntimeError("production Codex isolation command is incomplete")
    backend = [value for value in overrides if value.startswith("windows.sandbox=")]
    if research_windows_sandbox is None:
        if backend:
            raise RuntimeError("Windows backend requires explicit research selection")
    else:
        mode = options[options.index("-s") + 1] if options.count("-s") == 1 else None
        approval = options[options.index("-a") + 1] if options.count("-a") == 1 else None
        if (research_windows_sandbox not in {"elevated", "unelevated"}
                or backend != [f'windows.sandbox="{research_windows_sandbox}"']
                or mode != "read-only" or approval != "never"):
            raise RuntimeError("research Windows backend isolation is incomplete")
