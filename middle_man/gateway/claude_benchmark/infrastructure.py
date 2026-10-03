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


@dataclass(frozen=True, slots=True)
class ClaudeCli:
    executable: str | None
    version: str | None
    flags: tuple[str, ...]
    environment: str
    error: str | None

    @property
    def ready(self) -> bool:
        return self.error is None and all(flag in self.flags for flag in _REQUIRED_FLAGS)


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
    flags = tuple(dict.fromkeys(re.findall(r"(?<![\w-])(?:--[a-z][a-z-]*|-p)(?![\w-])",
                                        help_result.stdout + "\n" + help_result.stderr)))
    missing = [flag for flag in _REQUIRED_FLAGS if flag not in flags]
    return ClaudeCli(executable, version or None, flags, environment,
                     f"required CLI flags not documented: {', '.join(missing)}" if missing else None)


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
