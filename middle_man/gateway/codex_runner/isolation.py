"""Per-process production policy for Codex's native repository tools."""

from __future__ import annotations


PRODUCTION_EXTERNAL_TOOL_POLICY = "LOCAL_NATIVE_ONLY"
PRODUCTION_ISOLATION_OVERRIDES = ("features.apps=false", "features.plugins=false")


def isolation_arguments() -> tuple[str, ...]:
    return tuple(part for override in PRODUCTION_ISOLATION_OVERRIDES for part in ("-c", override))


def verify_isolation_command(command: tuple[str, ...]) -> None:
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
