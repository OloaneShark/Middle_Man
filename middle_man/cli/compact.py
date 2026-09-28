"""CLI input and JSON export for deterministic output compaction."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.git_diff import GitDiffReader
from middle_man.gateway.indexer import RepositoryIndexer


def run_compact(args: argparse.Namespace) -> None:
    compactor = OutputCompactor()
    if args.output_type == "git-diff":
        config = GatewayConfig(args.repo)
        result = compactor.compact_git_diff(GitDiffReader(config).read(RepositoryIndexer(config).index()),
                                            max_tokens=args.max_tokens)
    else:
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        else:
            if sys.stdin.isatty():
                raise ValueError("provide a file or pipe input to compact")
            try:
                text = sys.stdin.buffer.read().decode("utf-8", errors="replace") if hasattr(sys.stdin, "buffer") else sys.stdin.read()
            except OSError as exc:
                raise ValueError("provide a file or pipe input to compact") from exc
        result = compactor.compact(args.output_type, text, max_tokens=args.max_tokens)
    print(result.compacted_text, end="")
    print(f"[Middle_Man estimated context tokens: {result.estimated_original_tokens} -> {result.estimated_compacted_tokens}; "
          f"avoided {result.estimated_tokens_avoided}; not provider billing]")
    if args.json:
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(asdict(result), indent=2, sort_keys=True), encoding="utf-8")
        print(f"Compaction JSON: {destination}")
