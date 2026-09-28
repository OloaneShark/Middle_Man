"""Versioned JSON cache containing parsed structure, never full source text."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from middle_man.gateway.models import INDEX_SCHEMA_VERSION, ImportRecord, IndexedFile, Symbol
from middle_man import __version__


class IndexCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "index.json"

    def load(self, root: Path, parse_settings: dict[str, object] | None = None) -> dict[str, IndexedFile]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema_version"] != INDEX_SCHEMA_VERSION or data["root"] != str(root) or (parse_settings is not None and data.get("parse_settings") != parse_settings):
                return {}
            records = {}
            for raw in data["files"]:
                raw["symbols"] = tuple(Symbol(**{**value, "decorators": tuple(value["decorators"])}) for value in raw["symbols"])
                raw["imports"] = tuple(ImportRecord(**value) for value in raw["imports"])
                item = IndexedFile(**raw)
                if not item.path or item.path.startswith("/") or ".." in Path(item.path).parts:
                    return {}
                records[item.path] = item
            return records
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def save(self, root: Path, files: tuple[IndexedFile, ...], parse_settings: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError("cache path must not be a symlink")
        payload = {"schema_version": INDEX_SCHEMA_VERSION, "middle_man_version": __version__,
                   "root": str(root), "parse_settings": parse_settings, "files": [asdict(item) for item in files]}
        temporary = self.directory / "index.json.tmp"
        if temporary.is_symlink():
            raise ValueError("cache temporary path must not be a symlink")
        try:
            temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self) -> bool:
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError("cache path must not be a symlink")
        existed = self.path.exists()
        self.path.unlink(missing_ok=True)
        return existed
