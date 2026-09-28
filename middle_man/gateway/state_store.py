"""Safe atomic JSON persistence for local Gateway state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class StateStoreError(RuntimeError):
    pass


class AtomicJsonStore:
    def __init__(self, root: Path, path: Path, schema_version: int, label: str) -> None:
        self.root = root.resolve()
        self.path = path
        self.schema_version = schema_version
        self.label = label
        if not path.resolve().is_relative_to(self.root) or path.resolve() == self.root:
            raise ValueError(f"{label} path must stay inside the repository")

    def _check_path(self) -> None:
        current = self.path
        while current != self.root:
            if current.is_symlink():
                raise StateStoreError(f"unsafe symlink in {self.label} path: {current}")
            current = current.parent
        if not self.path.resolve().is_relative_to(self.root):
            raise StateStoreError(f"{self.label} path escapes repository root")

    def load(self) -> dict[str, Any] | None:
        self._check_path()
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != self.schema_version:
                raise StateStoreError(f"incompatible {self.label} schema; preserved existing data")
            if data.get("repository_root") != str(self.root):
                raise StateStoreError(f"{self.label} belongs to a different repository; preserved existing data")
            return data
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise StateStoreError(f"corrupt {self.label}; preserved existing data: {exc}") from exc

    def save(self, data: dict[str, Any]) -> None:
        self._check_path()
        if data.get("schema_version") != self.schema_version or data.get("repository_root") != str(self.root):
            raise ValueError(f"invalid {self.label} identity")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_path()
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            self._check_path()
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
