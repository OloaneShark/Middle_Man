"""Safe, incremental repository scanner and lightweight relationship builder."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from middle_man.gateway.cache import IndexCache
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import IndexedFile, IndexStats, Relationship, RepositoryIdentity, RepositoryIndex
from middle_man.gateway.parsers import ParserRegistry

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TSX", ".jsx": "JSX",
    ".html": "HTML", ".css": "CSS", ".json": "JSON", ".toml": "TOML", ".yaml": "YAML",
    ".yml": "YAML", ".md": "Markdown", ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell",
}
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".db", ".sqlite", ".exe", ".dll", ".so", ".mp3", ".mp4", ".woff", ".ttf"}


def _git(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=5, check=False)
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _identity(config: GatewayConfig) -> tuple[RepositoryIdentity, tuple[str, ...]]:
    root = config.repository_root
    git_root = _git(root, "rev-parse", "--show-toplevel") if config.git_enabled else None
    has_git = git_root is not None and Path(git_root.strip()).resolve() == root
    branch = (_git(root, "branch", "--show-current") or "").strip() if has_git else None
    head = (_git(root, "rev-parse", "HEAD") or "").strip() if has_git else None
    changed: set[str] = set()
    if has_git:
        raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all") or ""
        chunks = raw.split("\0")
        index = 0
        while index < len(chunks):
            item = chunks[index]
            if len(item) >= 4:
                name = item[3:]
                if item[:2].strip().startswith("R") or "R" in item[:2]:
                    index += 1
                try:
                    changed.add(config.relative_path(name))
                except ValueError:
                    pass
            index += 1
    return RepositoryIdentity(str(root), root.name, has_git, branch or None, head or None,
                              datetime.now(timezone.utc).isoformat()), tuple(sorted(changed))


def _rules(root: Path, name: str) -> tuple[str, ...]:
    path = root / name
    try:
        return tuple(line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))
    except (OSError, UnicodeError):
        return ()


def _matches(pattern: str, path: str, is_dir: bool) -> bool:
    pattern = pattern.lstrip("/")
    directory_only = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    if directory_only and not is_dir:
        return False
    if "/" in pattern:
        return fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern + "/")
    return any(fnmatch.fnmatchcase(part, pattern) for part in path.split("/"))


def _ignored(config: GatewayConfig, path: str, is_dir: bool, git_rules: tuple[str, ...], own_rules: tuple[str, ...]) -> bool:
    parts = path.split("/")
    if any(part in config.ignored_directories for part in parts):
        return True
    if any(_matches(pattern, path, is_dir) for pattern in config.ignored_patterns):
        return True
    result = False
    for pattern in (*git_rules, *own_rules):
        negated = pattern.startswith("!")
        if _matches(pattern[1:] if negated else pattern, path, is_dir):
            result = not negated
    return result


def _is_test(path: str) -> bool:
    name = Path(path).name
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py") or "/tests/" in f"/{path}" or "/__tests__/" in f"/{path}" or any(name.endswith(suffix) for suffix in (".test.js", ".spec.js", ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"))


def _module_map(files: tuple[IndexedFile, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in files:
        if item.extension == ".py":
            parts = list(Path(item.path).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            if parts:
                result[".".join(parts)] = item.path
    return result


def _relationships(files: tuple[IndexedFile, ...]) -> tuple[Relationship, ...]:
    modules = _module_map(files)
    by_path = {item.path: item for item in files}
    edges: set[Relationship] = set()
    for item in files:
        for symbol in item.symbols:
            edges.add(Relationship(item.path, symbol.qualified_name, "CONTAINS_SYMBOL"))
        package = list(Path(item.path).parent.parts)
        for imported in item.imports:
            if imported.level:
                base = package[:max(0, len(package) - imported.level + 1)]
                prefix = ".".join((*base, imported.module)) if imported.module else ".".join(base)
            else:
                prefix = imported.module
            candidates = [f"{prefix}.{imported.name}" if prefix and imported.name else prefix]
            if prefix not in candidates:
                candidates.append(prefix)
            if not imported.name and prefix:
                candidates.extend(".".join(prefix.split(".")[:n]) for n in range(len(prefix.split(".")) - 1, 0, -1))
            target = next((modules[name] for name in candidates if name in modules), None)
            if target and target != item.path:
                edges.add(Relationship(item.path, target, "IMPORTS"))
                if item.is_test and not by_path[target].is_test:
                    edges.add(Relationship(item.path, target, "TESTS"))
    return tuple(sorted(edges, key=lambda e: (e.source, e.kind, e.target)))


class RepositoryIndexer:
    def __init__(self, config: GatewayConfig, parsers: ParserRegistry | None = None) -> None:
        self.config = config
        self.parsers = parsers or ParserRegistry()
        self.cache = IndexCache(config.cache_dir)

    def index(self, *, rebuild: bool = False) -> RepositoryIndex:
        start = perf_counter()
        config = self.config
        parse_settings = {"max_file_size_bytes": config.max_file_size_bytes, "syntax_parsing": config.syntax_parsing}
        old = {} if rebuild else self.cache.load(config.repository_root, parse_settings)
        records: dict[str, IndexedFile] = {}
        counts: Counter[str] = Counter()
        git_rules = _rules(config.repository_root, ".gitignore")
        own_rules = _rules(config.repository_root, ".middlemanignore")
        visited: set[Path] = set()
        for directory, dirs, names in os.walk(config.repository_root, followlinks=config.follow_symlinks):
            real_dir = Path(directory).resolve()
            if not real_dir.is_relative_to(config.repository_root) or real_dir in visited:
                dirs[:] = []
                continue
            visited.add(real_dir)
            accepted_dirs = []
            for name in sorted(dirs):
                path = Path(directory) / name
                relative = path.relative_to(config.repository_root).as_posix()
                if _ignored(config, relative, True, git_rules, own_rules) or path.is_symlink() and not config.follow_symlinks or not path.resolve().is_relative_to(config.repository_root):
                    counts["ignored"] += 1
                else:
                    accepted_dirs.append(name)
            dirs[:] = accepted_dirs
            for name in sorted(names):
                path = Path(directory) / name
                relative = path.relative_to(config.repository_root).as_posix()
                if _ignored(config, relative, False, git_rules, own_rules) or path.is_symlink() and not config.follow_symlinks or not path.resolve().is_relative_to(config.repository_root):
                    counts["ignored"] += 1
                    continue
                try:
                    record = self._scan_file(path, relative, old.get(relative), counts)
                except (OSError, UnicodeError):
                    continue
                records[relative] = record
        counts["files_deleted"] = len(old.keys() - records.keys())
        files = tuple(records[path] for path in sorted(records))
        relations = _relationships(files)
        identity, changed = _identity(config)
        counts["parse_errors"] = sum(item.parse_status == "error" for item in files)
        stats = IndexStats(files_scanned=len(files), files_created=counts["files_created"], files_modified=counts["files_modified"],
                           files_deleted=counts["files_deleted"], files_unchanged=counts["files_unchanged"],
                           files_reparsed=counts["files_reparsed"], cache_hits=counts["cache_hits"], cache_misses=counts["cache_misses"],
                           ignored=counts["ignored"], parse_errors=counts["parse_errors"], index_duration_ms=(perf_counter() - start) * 1000)
        self.cache.save(config.repository_root, files, parse_settings)
        return RepositoryIndex(identity, files, relations, stats, changed)

    def _scan_file(self, path: Path, relative: str, cached: IndexedFile | None, counts: Counter[str]) -> IndexedFile:
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
        hash_value = digest.hexdigest()
        if cached and cached.sha256 == hash_value and cached.size_bytes == size:
            counts["files_unchanged"] += 1
            counts["cache_hits"] += 1
            return replace(cached, mtime_ns=path.stat().st_mtime_ns)
        counts["cache_misses"] += 1
        counts["files_modified" if cached else "files_created"] += 1
        extension = path.suffix.lower()
        language = LANGUAGES.get(extension, "Other")
        base = dict(path=relative, filename=path.name, extension=extension, language=language, size_bytes=size,
                    sha256=hash_value, mtime_ns=path.stat().st_mtime_ns, line_count=None, is_text=False,
                    is_test=_is_test(relative))
        if size > self.config.max_file_size_bytes:
            return IndexedFile(**base, parse_status="oversized")
        if extension in BINARY_EXTENSIONS:
            return IndexedFile(**base, parse_status="binary")
        raw = path.read_bytes()
        if b"\0" in raw[:8192]:
            return IndexedFile(**base, parse_status="binary")
        try:
            source = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return IndexedFile(**base, parse_status="binary")
        base["is_text"] = True
        base["line_count"] = len(source.splitlines())
        if not self.config.syntax_parsing or language == "Other":
            return IndexedFile(**base, parse_status="text")
        counts["files_reparsed"] += 1
        parsed = self.parsers.for_language(language).parse(relative, source)
        return IndexedFile(**base, parse_status="error" if parsed.error else "parsed", parse_error=parsed.error,
                           symbols=parsed.symbols, imports=parsed.imports)
