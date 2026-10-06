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


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    head: str | None
    status: tuple[str, ...]
    digest: str
    file_hashes: tuple[tuple[str, str], ...]


def changed_paths(before: RepositorySnapshot, after: RepositorySnapshot) -> tuple[str, ...]:
    old, new = dict(before.file_hashes), dict(after.file_hashes)
    return tuple(sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path)))


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
        features = subprocess.run([executable, "-c", "features.apps=false", "-c",
                                   "features.plugins=false", "features", "list"],
                                  capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not inspect Codex CLI") from exc
    if not version:
        raise RuntimeError("Codex CLI returned no version")
    required_main = ("--no-daemon", "--ask-for-approval", "--strict-config")
    required_exec = ("--ignore-user-config", "--sandbox", "read-only", "workspace-write",
                     "--cd", "--model", "--config", "--ephemeral", "--json")
    missing = [flag for flag in required_main if flag not in main_help]
    missing += [flag for flag in required_exec if flag not in exec_help]
    if missing:
        raise RuntimeError("Installed Codex CLI lacks required documented options: " + ", ".join(missing))
    states = {parts[0]: parts[-1] for line in features.splitlines()
              if len(parts := line.split()) >= 3}
    if states.get("apps") != "false" or states.get("plugins") != "false":
        raise RuntimeError("Installed Codex CLI cannot verify per-process Apps and plugins isolation")
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


def capture_repository_state(root: Path) -> RepositorySnapshot:
    """Capture HEAD, porcelain, and Git-visible content without requiring a clean tree."""
    try:
        paths = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others",
                                "--exclude-standard", "-z"], capture_output=True, timeout=30,
                               check=True).stdout
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1",
                                 "--untracked-files=all"], capture_output=True, timeout=30,
                                check=True).stdout
        head_result = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                                     capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not capture repository state") from exc
    head = head_result.stdout.decode("ascii", "replace").strip() if head_result.returncode == 0 else None
    digest = hashlib.sha256(status + b"\0" + (head or "").encode("ascii"))
    file_hashes: list[tuple[str, str]] = []
    try:
        for raw in sorted(set(paths.split(b"\0")) - {b""}):
            relative = raw.decode("utf-8", errors="surrogateescape")
            path = root / relative
            digest.update(raw + b"\0")
            if path.is_symlink():
                value = hashlib.sha256(os.readlink(path).encode("utf-8", errors="surrogateescape")).digest()
            elif path.is_file():
                file_digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        file_digest.update(chunk)
                value = file_digest.digest()
            else:
                value = hashlib.sha256(b"<missing>").digest()
            digest.update(value)
            file_hashes.append((relative, value.hex()))
    except OSError as exc:
        raise RuntimeError("Could not hash Git-visible repository files") from exc
    return RepositorySnapshot(head, tuple(status.decode("utf-8", "replace").splitlines()),
                              digest.hexdigest(), tuple(file_hashes))


def repository_state(root: Path) -> str:
    """Compatibility digest for local-only preview integrity checks."""
    return capture_repository_state(root).digest
