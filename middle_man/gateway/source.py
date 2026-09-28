"""Verified source-of-truth reads for indexed, in-root files only."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import IndexedFile, RepositoryIndex


class StaleSourceError(RuntimeError):
    pass


class UnsafeSourceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: str
    text: str
    sha256: str
    lines: tuple[str, ...]
    size_bytes: int


class SourceReader:
    def __init__(self, config: GatewayConfig, index: RepositoryIndex) -> None:
        self.config = config
        self.index = index

    def read(self, path: str) -> SourceFile:
        record = self.index.get_file(path)
        if record is None or not record.is_text or record.parse_status in {"oversized", "binary"}:
            raise UnsafeSourceError(f"file is not an indexed, readable text source: {path}")
        absolute = self.config.resolve_path(path)
        if self.config.relative_path(absolute) != path:
            raise UnsafeSourceError(f"noncanonical repository path: {path}")
        if not self.config.follow_symlinks:
            current = absolute
            while current != self.config.repository_root:
                if current.is_symlink():
                    raise UnsafeSourceError(f"symlink source is not allowed: {path}")
                current = current.parent
        try:
            if absolute.stat().st_size > self.config.max_file_size_bytes:
                raise UnsafeSourceError(f"source exceeds configured limit: {path}")
            raw = absolute.read_bytes()
        except FileNotFoundError as exc:
            raise StaleSourceError(f"source disappeared since indexing: {path}") from exc
        if len(raw) > self.config.max_file_size_bytes:
            raise UnsafeSourceError(f"source exceeds configured limit: {path}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != record.sha256:
            raise StaleSourceError(f"source changed since indexing: {path}")
        text = raw.decode("utf-8-sig")
        return SourceFile(path, text, digest, tuple(text.splitlines(keepends=True)), len(raw))
