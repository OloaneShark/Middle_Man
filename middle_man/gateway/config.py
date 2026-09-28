"""Validated settings for local repository analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_IGNORED_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "build", "dist", "coverage", "benchmark_results", ".middle_man_cache",
})
DEFAULT_IGNORED_PATTERNS = ("*.pyc", "*.pyo", "*.egg-info/**", ".env", ".env.*", "id_rsa", "id_ed25519", "*.pem", "*.key")


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    repository_root: Path
    cache_dir: Path | None = None
    max_file_size_bytes: int = 1_000_000
    ignored_directories: frozenset[str] = field(default_factory=lambda: DEFAULT_IGNORED_DIRS)
    ignored_patterns: tuple[str, ...] = DEFAULT_IGNORED_PATTERNS
    follow_symlinks: bool = False
    git_enabled: bool = True
    syntax_parsing: bool = True
    max_search_results: int = 10
    minimum_score: float = 1.0

    def __post_init__(self) -> None:
        root = Path(self.repository_root).resolve()
        if not root.is_dir():
            raise ValueError(f"repository root is not a directory: {root}")
        cache = (root / self.cache_dir).resolve() if self.cache_dir is not None and not Path(self.cache_dir).is_absolute() else Path(self.cache_dir).resolve() if self.cache_dir is not None else root / ".middle_man_cache"
        if not cache.is_relative_to(root) or cache == root:
            raise ValueError("cache directory must be inside the repository root")
        if self.max_file_size_bytes < 1 or self.max_search_results < 1 or self.minimum_score < 0:
            raise ValueError("invalid Gateway limits")
        object.__setattr__(self, "repository_root", root)
        object.__setattr__(self, "cache_dir", cache)

    def resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else self.repository_root / candidate).resolve()
        if not resolved.is_relative_to(self.repository_root):
            raise ValueError(f"path escapes repository root: {path}")
        return resolved

    def relative_path(self, path: str | Path) -> str:
        return self.resolve_path(path).relative_to(self.repository_root).as_posix()
