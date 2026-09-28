"""Structured working-tree diffs with indexed Python symbol mapping."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import RepositoryIndex

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: str
    text: str
    old_line: int | None
    new_line: int | None


@dataclass(frozen=True, slots=True)
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True, slots=True)
class FileDiff:
    path: str
    old_path: str | None
    status: str
    additions: int
    deletions: int
    hunks: tuple[DiffHunk, ...]
    binary_changed: bool
    affected_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GitDiff:
    has_git: bool
    files: tuple[FileDiff, ...]

    def get_file(self, path: str) -> FileDiff | None:
        return next((item for item in self.files if item.path == path), None)


def _run(root: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=10, check=False)
        return result.returncode, result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def _status(root: Path) -> dict[str, tuple[str, str | None]]:
    code, raw = _run(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if code:
        return {}
    result: dict[str, tuple[str, str | None]] = {}
    parts = raw.split("\0")
    position = 0
    while position < len(parts):
        entry = parts[position]
        position += 1
        if len(entry) < 4:
            continue
        flags, name = entry[:2], entry[3:]
        old_path = None
        if "R" in flags or "C" in flags:
            if position < len(parts):
                old_path = parts[position]
                position += 1
        status = "untracked" if flags == "??" else "renamed" if "R" in flags else "deleted" if "D" in flags else "added" if "A" in flags else "modified"
        result[name.replace("\\", "/")] = (status, old_path.replace("\\", "/") if old_path else None)
    return result


def _patches(root: Path) -> str:
    flags = ("--no-ext-diff", "--no-color", "--find-renames", "--unified=0")
    code, patch = _run(root, "diff", *flags, "HEAD")
    if code == 0:
        return patch
    return _run(root, "diff", *flags, "--cached")[1] + _run(root, "diff", *flags)[1]


def _parse_patch(patch: str) -> dict[str, tuple[str | None, tuple[DiffHunk, ...], bool]]:
    result: dict[str, tuple[str | None, tuple[DiffHunk, ...], bool]] = {}
    path: str | None = None
    old_path: str | None = None
    hunks: list[DiffHunk] = []
    lines: list[DiffLine] = []
    header: tuple[int, int, int, int] | None = None
    binary = False
    old_number = new_number = 0

    def finish_hunk() -> None:
        nonlocal header, lines
        if header is not None:
            hunks.append(DiffHunk(*header, tuple(lines)))
        header = None
        lines = []

    def finish_file() -> None:
        finish_hunk()
        if path is not None:
            previous = result.get(path)
            result[path] = (old_path or (previous[0] if previous else None),
                            (previous[1] if previous else ()) + tuple(hunks), binary or (previous[2] if previous else False))

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            finish_file()
            marker = line.rsplit(" b/", 1)
            path = marker[1].strip('"') if len(marker) == 2 else None
            old_path = None
            hunks = []
            binary = False
        elif line.startswith("rename from "):
            old_path = line[len("rename from "):]
        elif line.startswith("rename to "):
            path = line[len("rename to "):]
        elif line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            binary = True
        elif match := _HUNK.match(line):
            finish_hunk()
            header = (int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
            old_number, new_number = header[0], header[2]
        elif header is not None and line.startswith(("+", "-", " ")):
            kind = line[0]
            lines.append(DiffLine(kind, line[1:], old_number if kind != "+" else None,
                                  new_number if kind != "-" else None))
            old_number += kind != "+"
            new_number += kind != "-"
    finish_file()
    return result


def _affected(path: str, hunks: tuple[DiffHunk, ...], index: RepositoryIndex) -> tuple[str, ...]:
    symbols = index.symbols_in_file(path)
    affected: set[str] = set()
    for hunk in hunks:
        changed = [line.new_line for line in hunk.lines if line.new_line is not None and line.kind == "+"]
        if not changed:
            changed = [hunk.new_start]
        for line in changed:
            enclosing = [item for item in symbols if item.start_line <= line <= (item.end_line or item.start_line)]
            if enclosing:
                chosen = min(enclosing, key=lambda item: ((item.end_line or item.start_line) - item.start_line, item.qualified_name))
                affected.add(chosen.qualified_name)
    return tuple(sorted(affected))


class GitDiffReader:
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config

    def read(self, index: RepositoryIndex | None = None) -> GitDiff:
        root = self.config.repository_root
        if not self.config.git_enabled or Path(_run(root, "rev-parse", "--show-toplevel")[1].strip() or root).resolve() != root:
            return GitDiff(False, ())
        statuses = _status(root)
        parsed = _parse_patch(_patches(root))
        files = []
        for path in sorted(statuses.keys() | parsed.keys()):
            status, status_old = statuses.get(path, ("modified", None))
            patch_old, hunks, binary = parsed.get(path, (None, (), False))
            additions = sum(line.kind == "+" for hunk in hunks for line in hunk.lines)
            deletions = sum(line.kind == "-" for hunk in hunks for line in hunk.lines)
            files.append(FileDiff(path, status_old or patch_old, status, additions, deletions, hunks,
                                  binary, _affected(path, hunks, index) if index else ()))
        return GitDiff(True, tuple(files))
