"""Local Context Pack, diff, and quality-benchmark command handlers."""

from __future__ import annotations

import argparse
from pathlib import Path

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.context_output import format_context_pack, save_context_pack_json
from middle_man.gateway.git_diff import GitDiffReader
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.quality import run_context_benchmarks


def run_context_pack(args: argparse.Namespace, config: GatewayConfig) -> None:
    if not args.query:
        raise ValueError("context pack requires a task query")
    pack = ContextBuilder(config).build(args.query, mode=args.mode, max_context_tokens=args.max_tokens, top_k=args.top_k)
    rendered = format_context_pack(pack)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        print(f"Context Pack: {destination}")
    else:
        print(rendered, end="")
    if args.json:
        print(f"Context Pack JSON: {save_context_pack_json(pack, args.json)}")


def run_context_benchmark(args: argparse.Namespace) -> None:
    results = run_context_benchmarks(mode=args.mode, max_context_tokens=args.max_tokens or 8000)
    print("MIDDLE_MAN CONTEXT EFFICIENCY BENCHMARK")
    print("Estimated local context tokens, not provider billing or plan usage.")
    for result in results:
        print(f"{result.name}: {'PASS' if result.success else 'FAIL'}")
        print(f"  required file/symbol recall: {result.required_file_recall:.1%}/{result.required_symbol_recall:.1%}")
        print(f"  candidate/selected estimated tokens: {result.raw_candidate_estimated_tokens}/{result.selected_estimated_tokens}")
        print(f"  estimated reduction: {result.estimated_reduction_percent:.1f}%  irrelevant files: {result.irrelevant_files_included}")
        for warning in result.warnings:
            print(f"  warning: {warning}")


def run_diff(args: argparse.Namespace, config: GatewayConfig) -> None:
    index = RepositoryIndexer(config).index()
    diff = GitDiffReader(config).read(index)
    print("MIDDLE_MAN GIT DIFF")
    if not diff.has_git:
        print("No Git repository at this root.")
        return
    print(f"Changed files: {len(diff.files)}")
    for file in diff.files:
        print(f"{file.path}  status: {file.status}" + (f"  from: {file.old_path}" if file.old_path else ""))
        print(f"  hunks: {len(file.hunks)}  +{file.additions}/-{file.deletions}" + ("  binary" if file.binary_changed else ""))
        if file.affected_symbols:
            print("  affected symbols: " + ", ".join(file.affected_symbols))
