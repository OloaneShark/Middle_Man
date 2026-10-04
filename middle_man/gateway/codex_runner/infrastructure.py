"""Codex CLI discovery and repository integrity checks without model inference."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodexCLI:
    executable: str
    version: str


def discover_codex() -> CodexCLI:
    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("Codex CLI not found on PATH")
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                 timeout=10, check=True).stdout.strip()
        main_help = subprocess.run([executable, "--help"], capture_output=True, text=True,
                                   timeout=10, check=True).stdout
        exec_help = subprocess.run([executable, "exec", "--help"], capture_output=True, text=True,
                                   timeout=10, check=True).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not inspect Codex CLI") from exc
    if not version:
        raise RuntimeError("Codex CLI returned no version")
    required_main = ("--no-daemon", "--ask-for-approval", "--strict-config")
    required_exec = ("--ignore-user-config", "--sandbox", "read-only", "workspace-write",
                     "--cd", "--model", "--config", "--ephemeral")
    missing = [flag for flag in required_main if flag not in main_help]
    missing += [flag for flag in required_exec if flag not in exec_help]
    if missing:
        raise RuntimeError("Installed Codex CLI lacks required documented options: " + ", ".join(missing))
    return CodexCLI(executable, version)


def validate_repository(root: Path) -> Path:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"repository is not a directory: {root}")
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"not a Git repository: {root}") from exc
    if os.path.normcase(str(Path(result.stdout.strip()).resolve())) != os.path.normcase(str(root)):
        raise ValueError("--repo must name the Git repository root")
    return root


def repository_state(root: Path) -> str:
    """Hash Git-visible files plus porcelain state; ignored caches are deliberately excluded."""
    try:
        paths = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others",
                                "--exclude-standard", "-z"], capture_output=True, timeout=30,
                               check=True).stdout
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z",
                                 "--untracked-files=all"], capture_output=True, timeout=30,
                                check=True).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not capture repository state") from exc
    digest = hashlib.sha256(status)
    for raw in sorted(set(paths.split(b"\0")) - {b""}):
        path = root / raw.decode("utf-8", errors="surrogateescape")
        digest.update(raw + b"\0")
        if path.is_symlink():
            digest.update(hashlib.sha256(os.readlink(path).encode("utf-8", errors="surrogateescape")).digest())
        elif path.is_file():
            file_digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    file_digest.update(chunk)
            digest.update(file_digest.digest())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()
