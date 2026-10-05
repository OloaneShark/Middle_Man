"""Conservative, source-free classification of completed native search commands."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from middle_man.gateway.secrets import SecretRedactor


_OPERATORS = frozenset({"|", "||", "&", "&&", ";", ">", ">>", "<", "<<"})
_NO_CONTENT = frozenset({"-l", "--files-with-matches", "-L", "--files-without-match",
                         "-c", "--count", "-q", "--quiet", "--files"})
_SIMPLE_FLAGS = frozenset({"-n", "--line-number", "-i", "--ignore-case", "--hidden",
                           "--no-heading", "-F", "--fixed-strings", "--"})


@dataclass(frozen=True, slots=True)
class SearchObservation:
    kind: str
    content_producing: bool
    target_paths: tuple[str, ...]
    file_targeted: bool
    repository_wide: bool


@dataclass(frozen=True, slots=True)
class SearchTelemetry:
    content_search_calls: int = 0
    file_targeted_searches: int = 0
    repository_wide_searches: int = 0
    file_listing_searches: int = 0
    searched_paths: tuple[str, ...] = ()

    @property
    def unique_searched_paths(self) -> int:
        return len(self.searched_paths)


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'") else value


def _tokens(command: str, *, nested: bool = False) -> list[str] | None:
    if len(command) > 4096:
        return None
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars="|;&<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens or any(token in _OPERATORS or token and set(token) <= set("|;&<>") for token in tokens):
        return None
    executable = Path(_unquote(tokens[0])).name.lower()
    if not nested and executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        for index, token in enumerate(tokens[1:], 1):
            if token.lower() in {"-command", "-c"} and index + 1 == len(tokens) - 1:
                return _tokens(_unquote(tokens[index + 1]), nested=True)
        return None
    return tokens


def _safe_target(raw: str, root: Path) -> str | None:
    value = _unquote(raw).replace("''", "'")
    if not value or any(char in value for char in "*?[]$`%\r\n"):
        return None
    candidate = Path(value)
    if ".." in candidate.parts:
        return None
    try:
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        relative = resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if relative == Path("."):
        return "."
    if not resolved.exists() or not (resolved.is_file() or resolved.is_dir()):
        return None
    path = relative.as_posix() + ("/" if resolved.is_dir() else "")
    return path if SecretRedactor().redact(path).text == path else None


def _positional_targets(args: list[str]) -> tuple[list[str], bool] | None:
    positionals: list[str] = []
    for token in args:
        if token.startswith("-") and token not in _SIMPLE_FLAGS:
            return None
        if token not in _SIMPLE_FLAGS:
            positionals.append(token)
    if not positionals:
        return None
    return positionals[1:], not bool(positionals[1:])


def classify_search_command(command: str, root: Path) -> SearchObservation | None:
    tokens = _tokens(command)
    if tokens is None:
        return None
    verb = Path(_unquote(tokens[0])).name.lower()
    args = tokens[1:]
    if verb in {"rg", "rg.exe", "grep", "grep.exe"}:
        if verb.startswith("rg") and "--files" in args:
            return SearchObservation("file_listing_search", False, (), False, False)
        has_line_numbers = any(token in {"-n", "--line-number"} for token in args)
        content = has_line_numbers and not any(token in _NO_CONTENT for token in args)
        parsed = _positional_targets(args)
        if parsed is None:
            return SearchObservation("search", content, (), False, False)
        targets, no_explicit_target = parsed
    elif verb == "git" and len(args) >= 2 and args[0].lower() == "grep":
        search_args = args[1:]
        content = not any(token in _NO_CONTENT for token in search_args)
        if "--" in search_args:
            split = search_args.index("--")
            targets = search_args[split + 1:]
            no_explicit_target = not targets
        else:
            targets = []
            no_explicit_target = True
    elif verb == "select-string":
        lowered = [part.lower() for part in args]
        content = "-pattern" in lowered and not any(part in {"-quiet", "-list"} for part in lowered)
        targets = [args[index + 1] for index, token in enumerate(lowered[:-1])
                   if token in {"-path", "-literalpath"}]
        no_explicit_target = not targets
    else:
        return None
    normalized = tuple(dict.fromkeys(path for raw in targets
                                      if (path := _safe_target(raw, root)) is not None and path != "."))
    wide = no_explicit_target or "." in targets
    return SearchObservation("search", content, normalized,
                             any(not path.endswith("/") for path in normalized), wide)


def summarize_searches(commands: list[str], root: Path) -> SearchTelemetry:
    redactor = SecretRedactor()
    observations = [item for command in commands
                    if (item := classify_search_command(redactor.redact(command).text, root)) is not None]
    paths = tuple(sorted({path for item in observations for path in item.target_paths}))
    return SearchTelemetry(
        content_search_calls=sum(item.content_producing for item in observations),
        file_targeted_searches=sum(item.file_targeted for item in observations),
        repository_wide_searches=sum(item.repository_wide for item in observations),
        file_listing_searches=sum(item.kind == "file_listing_search" for item in observations),
        searched_paths=paths,
    )
