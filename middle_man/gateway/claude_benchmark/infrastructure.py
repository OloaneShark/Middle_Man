"""Non-inference CLI checks and Claude memory isolation."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


MEMORY_FILES = ("CLAUDE.md", "CLAUDE.local.md")
_REQUIRED_FLAGS = ("-p", "--output-format", "--verbose", "--model", "--tools")
_ISOLATION_FLAGS = ("--safe-mode", "--restricted", "--strict-mcp-config")


def _option_blocks(help_text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    names: tuple[str, ...] = ()
    description: list[str] = []

    def save() -> None:
        for name in names:
            blocks[name] = " ".join(description)

    for line in help_text.splitlines():
        if line.startswith("  -") and not line.startswith("    "):
            save()
            header = re.split(r"\s{2,}", line.strip(), maxsplit=1)
            names = tuple(re.findall(r"(?<![\w-])--[A-Za-z][A-Za-z-]*|(?<![\w-])-[A-Za-z](?![\w-])",
                                     header[0]))
            description = header[1:] if len(header) > 1 else []
        elif names and line.startswith("    "):
            description.append(line.strip())
        elif line.startswith("Commands:"):
            save()
            break
    else:
        save()
    return blocks


@dataclass(frozen=True, slots=True)
class ClaudeCli:
    executable: str | None
    version: str | None
    flags: tuple[str, ...]
    environment: str
    error: str | None
    supports_stream_json: bool = False
    stream_json_requires_verbose: bool | None = None
    supports_max_turns: bool = False
    supports_setting_sources: bool = False
    setting_source_values: tuple[str, ...] = ()
    supports_tool_filtering: bool = False
    supports_allowed_tools: bool = False
    supports_disallowed_tools: bool = False
    supports_permission_mode: bool = False
    supports_permission_prompts: bool = False
    permission_modes: tuple[str, ...] = ()
    supports_mcp_config: bool = False
    supports_mcp_isolation: bool = False
    supports_safe_mode: bool = False
    supports_restricted_mode: bool = False
    supports_no_session_persistence: bool = False
    model_aliases: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return (self.error is None and
                all(flag in self.flags for flag in (*_REQUIRED_FLAGS, *_ISOLATION_FLAGS)) and
                self.supports_stream_json and self.supports_tool_filtering and
                self.supports_mcp_isolation and self.supports_safe_mode and
                self.supports_restricted_mode)


def discover_cli() -> ClaudeCli:
    executable = shutil.which("claude")
    environment = f"os={os.name}; shell={os.environ.get('SHELL') or os.environ.get('COMSPEC') or 'unknown'}"
    if executable is None:
        return ClaudeCli(None, None, (), environment, "Claude CLI is not on PATH")
    try:
        version = subprocess.run([executable, "--version"], check=True, capture_output=True,
                                 text=True, timeout=15).stdout.strip()
        help_result = subprocess.run([executable, "--help"], check=True, capture_output=True,
                                     text=True, timeout=15)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return ClaudeCli(executable, None, (), environment, f"Claude CLI inspection failed: {type(exc).__name__}")
    blocks = _option_blocks(help_result.stdout + "\n" + help_result.stderr)
    flags = tuple(blocks)
    output = blocks.get("--output-format", "")
    tools = blocks.get("--tools", "")
    settings = blocks.get("--setting-sources", "")
    permissions = blocks.get("--permission-mode", "")
    stream_json = '"stream-json"' in output
    tool_filtering = "Specify the list of available tools" in tools and '"Bash,Edit,Read"' in tools
    mcp_isolation = "ignoring all other MCP configurations" in blocks.get("--strict-mcp-config", "")
    safe_mode = "customizations" in blocks.get("--safe-mode", "") and "MCP servers" in blocks["--safe-mode"]
    restricted = "ignores user," in blocks.get("--restricted", "") and "settings files" in blocks["--restricted"]
    missing = [flag for flag in (*_REQUIRED_FLAGS, *_ISOLATION_FLAGS) if flag not in flags]
    if not stream_json:
        missing.append("--output-format stream-json")
    if not tool_filtering:
        missing.append("--tools documented built-in list")
    if not mcp_isolation or not safe_mode or not restricted:
        missing.append("documented memory/settings/MCP isolation semantics")
    verbose_rule = True if re.search(r"(?:requires|must use)\s+--verbose", output, re.I) else None
    return ClaudeCli(
        executable, version or None, flags, environment,
        f"required benchmark capabilities not documented: {', '.join(missing)}" if missing else None,
        supports_stream_json=stream_json,
        stream_json_requires_verbose=verbose_rule,
        supports_max_turns="--max-turns" in flags,
        supports_setting_sources="--setting-sources" in flags and
                                 all(value in settings for value in ("user", "project", "local")),
        setting_source_values=tuple(value for value in ("user", "project", "local") if value in settings),
        supports_tool_filtering=tool_filtering,
        supports_allowed_tools="--allowed-tools" in flags,
        supports_disallowed_tools="--disallowed-tools" in flags,
        supports_permission_mode="--permission-mode" in flags,
        supports_permission_prompts="--permission-prompts" in flags,
        permission_modes=tuple(re.findall(r'"([^"]+)"', permissions)),
        supports_mcp_config="--mcp-config" in flags,
        supports_mcp_isolation=mcp_isolation,
        supports_safe_mode=safe_mode,
        supports_restricted_mode=restricted,
        supports_no_session_persistence="--no-session-persistence" in flags,
        model_aliases=tuple(re.findall(r"'([A-Za-z]+)'", blocks.get("--model", ""))),
    )


def user_memory_presence(home: Path) -> dict[str, bool]:
    root = home.resolve()
    names = (root / ".claude" / "CLAUDE.md", root / ".claude" / "CLAUDE.local.md",
             root / "CLAUDE.md", root / "CLAUDE.local.md",
             root / ".claude" / "settings.json", root / ".claude" / "settings.local.json")
    return {str(path): path.is_file() for path in names}


def memory_contamination(snapshot: Path) -> tuple[Path, ...]:
    root = snapshot.resolve()
    return tuple(candidate for directory in (root, *root.parents)
                 for name in MEMORY_FILES if (candidate := directory / name).is_file())


def require_memory_isolation(snapshot: Path) -> None:
    found = memory_contamination(snapshot)
    if found:
        raise RuntimeError("Claude project/ancestor memory contaminates benchmark: " +
                           ", ".join(str(path) for path in found))


def snapshot_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in {".git", ".middle_man_cache", "__pycache__"}
                                         for part in path.relative_to(root).parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def git_clean(root: Path) -> bool:
    result = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                            check=True, capture_output=True, text=True)
    return not result.stdout.strip()
