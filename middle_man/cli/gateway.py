"""Presentation-only commands for local Gateway indexing and relevance search."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from middle_man.gateway import ContextQuery, GatewayConfig, RelevanceEngine, RepositoryIndexer
from middle_man.gateway.cache import IndexCache


def add_gateway_commands(subparsers: argparse._SubParsersAction) -> None:
    index = subparsers.add_parser("index", help="index a local repository")
    index.add_argument("--repo", type=Path, default=Path.cwd())
    index.add_argument("--rebuild", action="store_true")
    inspect = subparsers.add_parser("inspect", help="inspect a local repository index")
    inspect.add_argument("--repo", type=Path, default=Path.cwd())
    context = subparsers.add_parser("context", help="find relevant repository files")
    context.add_argument("action", choices=("find",))
    context.add_argument("query")
    context.add_argument("--repo", type=Path, default=Path.cwd())
    context.add_argument("--top-k", type=int)
    context.add_argument("--error-text", default="")
    cache = subparsers.add_parser("cache", help="manage local index cache")
    cache.add_argument("action", choices=("status", "clear", "rebuild"))
    cache.add_argument("--repo", type=Path, default=Path.cwd())


def run_gateway(args: argparse.Namespace) -> None:
    config = GatewayConfig(args.repo)
    indexer = RepositoryIndexer(config)
    if args.command == "cache":
        if args.action == "clear":
            removed = indexer.cache.clear()
            print("Middle_Man cache cleared" if removed else "Middle_Man cache already empty")
            return
        if args.action == "status":
            records = IndexCache(config.cache_dir).load(config.repository_root)
            print(f"Middle_Man cache: {len(records)} valid file records")
            return
    result = indexer.index(rebuild=args.command == "cache" and args.action == "rebuild" or getattr(args, "rebuild", False))
    if args.command == "context":
        matches = RelevanceEngine(result, config).find(ContextQuery(args.query, error_text=args.error_text), top_k=args.top_k)
        print("MIDDLE_MAN CONTEXT SEARCH")
        print(f"Query: {args.query}")
        for number, candidate in enumerate(matches, 1):
            print(f"{number}. {candidate.path}  score: {candidate.score:g}  {candidate.role}")
            for reason in candidate.reasons:
                print(f"   - {reason}")
        if not matches:
            print("No relevant files found.")
        return
    print("MIDDLE_MAN REPOSITORY INDEX")
    print(f"Repository: {result.identity.name}")
    print(f"Files discovered: {len(result.files)}")
    print(f"Indexed text files: {sum(item.is_text for item in result.files)}")
    print(f"Ignored: {result.stats.ignored}")
    print("Languages:")
    for name, count in sorted(result.language_counts.items()):
        print(f"  {name}: {count}")
    print(f"Symbols: {sum(len(item.symbols) for item in result.files)}")
    print(f"Relationships: {len(result.relationships)}")
    print(f"Parse errors: {result.stats.parse_errors}")
    print(f"Cache hits/misses: {result.stats.cache_hits}/{result.stats.cache_misses}")
    print(f"Created/modified/deleted: {result.stats.files_created}/{result.stats.files_modified}/{result.stats.files_deleted}")
    print(f"Reparsed: {result.stats.files_reparsed}")
