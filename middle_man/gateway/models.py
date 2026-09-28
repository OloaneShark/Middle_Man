"""Immutable repository snapshot records and indexed lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

INDEX_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class Symbol:
    path: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int | None = None
    parent: str | None = None
    decorators: tuple[str, ...] = ()
    is_async: bool = False


@dataclass(frozen=True, slots=True)
class ImportRecord:
    module: str
    name: str | None = None
    level: int = 0
    line: int = 0


@dataclass(frozen=True, slots=True)
class IndexedFile:
    path: str
    filename: str
    extension: str
    language: str
    size_bytes: int
    sha256: str | None
    mtime_ns: int
    line_count: int | None
    is_text: bool
    is_test: bool
    parse_status: str
    parse_error: str | None = None
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[ImportRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class Relationship:
    source: str
    target: str
    kind: str


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    root: str
    name: str
    has_git: bool
    branch: str | None
    head: str | None
    updated_at: str
    schema_version: int = INDEX_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class IndexStats:
    files_scanned: int = 0
    files_created: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    files_reparsed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    ignored: int = 0
    parse_errors: int = 0
    index_duration_ms: float = 0.0


@dataclass(frozen=True)
class RepositoryIndex:
    identity: RepositoryIdentity
    files: tuple[IndexedFile, ...]
    relationships: tuple[Relationship, ...]
    stats: IndexStats
    changed_paths: tuple[str, ...] = ()
    _file_map: Mapping[str, IndexedFile] = field(init=False, repr=False, compare=False)
    _symbols: Mapping[str, tuple[Symbol, ...]] = field(init=False, repr=False, compare=False)
    _imports: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)
    _importers: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)
    _tests: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        files = {item.path: item for item in self.files}
        symbols: dict[str, list[Symbol]] = {}
        imports: dict[str, list[str]] = {}
        importers: dict[str, list[str]] = {}
        tests: dict[str, list[str]] = {}
        for item in self.files:
            for symbol in item.symbols:
                symbols.setdefault(symbol.name, []).append(symbol)
                symbols.setdefault(symbol.qualified_name, []).append(symbol)
        for relation in self.relationships:
            if relation.kind == "IMPORTS":
                imports.setdefault(relation.source, []).append(relation.target)
                importers.setdefault(relation.target, []).append(relation.source)
            elif relation.kind == "TESTS":
                tests.setdefault(relation.target, []).append(relation.source)
        object.__setattr__(self, "_file_map", MappingProxyType(files))
        object.__setattr__(self, "_symbols", MappingProxyType({k: tuple(dict.fromkeys(v)) for k, v in symbols.items()}))
        object.__setattr__(self, "_imports", MappingProxyType({k: tuple(v) for k, v in imports.items()}))
        object.__setattr__(self, "_importers", MappingProxyType({k: tuple(v) for k, v in importers.items()}))
        object.__setattr__(self, "_tests", MappingProxyType({k: tuple(v) for k, v in tests.items()}))

    def get_file(self, path: str) -> IndexedFile | None:
        return self._file_map.get(path)

    def find_symbol(self, name: str) -> tuple[Symbol, ...]:
        return self._symbols.get(name, ())

    def symbols_in_file(self, path: str) -> tuple[Symbol, ...]:
        item = self.get_file(path)
        return item.symbols if item else ()

    def imports_for(self, path: str) -> tuple[str, ...]:
        return self._imports.get(path, ())

    def importers_of(self, path: str) -> tuple[str, ...]:
        return self._importers.get(path, ())

    def tests_for(self, path: str) -> tuple[str, ...]:
        return self._tests.get(path, ())

    @property
    def language_counts(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for item in self.files:
            counts[item.language] = counts.get(item.language, 0) + 1
        return MappingProxyType(counts)
