"""Conservative explicit read-path extraction from completed native commands."""

from __future__ import annotations

import re
from pathlib import Path

_TOKEN = r'''(?:"[^"]+"|'(?:''|[^'])*'|[^\s;|,)]+)'''
_POWERSHELL = re.compile(r"(?i)\b(?:Get-Content|cat|type)\s+(?:(?:-LiteralPath|-Path)\s+)?(" + _TOKEN + r")")
_PATH_READ = re.compile(r"(?i)\bPath\(\s*[rR]?(" + _TOKEN + r")\s*\)\.read_(?:text|bytes)\s*\(")
_OPEN_READ = re.compile(r"(?i)\bopen\(\s*[rR]?(" + _TOKEN + r")\s*,\s*(?:mode\s*=\s*)?(['\"])r[btx]?\2")
_OPEN_DEFAULT = re.compile(r"(?i)\bopen\(\s*[rR]?(" + _TOKEN + r")\s*\)")
_FALLBACK = re.compile(r"(?i)(?:[\w. -]+[/\\])+[\w. -]+\.(?:py|md|toml|json|yaml|yml|txt|css)")


def _normalize(token: str, root: Path) -> str | None:
    token = token.strip().strip('"\'').replace("''", "'")
    while "\\\\" in token:
        token = token.replace("\\\\", "\\")
    path = (root / token).resolve()
    base = root.resolve()
    return path.relative_to(base).as_posix() if path.is_relative_to(base) and path.is_file() else None


def explicit_read_paths(command: str, root: Path) -> tuple[str, ...]:
    found: list[str] = []
    for expression in (_POWERSHELL, _PATH_READ, _OPEN_READ, _OPEN_DEFAULT):
        for match in expression.finditer(command):
            path = _normalize(match.group(1), root)
            if path:
                found.append(path)
            elif expression is _POWERSHELL:
                # Windows PowerShell's nested -Command quoting may split a path token.
                tail = command[match.start(1):match.start(1) + 220].split("|", 1)[0]
                for candidate in _FALLBACK.finditer(tail):
                    path = _normalize(candidate.group(0), root)
                    if path:
                        found.append(path)
                        break
    return tuple(dict.fromkeys(found))


def has_explicit_read(command: str) -> bool:
    return any(pattern.search(command) for pattern in (_POWERSHELL, _PATH_READ, _OPEN_READ))
