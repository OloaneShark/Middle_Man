"""Research-only, source-free additions to an unchanged production locator."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from middle_man.experiments.locator_navigation_eval import parse_locator
from middle_man.gateway.codex_runner.infrastructure import (
    capture_repository_state, validate_repository,
)
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.models import IndexedFile, RepositoryIndex, Symbol
from middle_man.gateway.offline_navigation import (
    OfflineLocator, append_offline_locator, build_offline_locator,
)
from middle_man.gateway.parsers import PythonParser
from middle_man.gateway.relevance import ContextQuery, RelevanceEngine, terms
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.source import SourceReader, StaleSourceError, UnsafeSourceError
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


APPENDIX_LIMIT = 512
RANKED_FILE_LIMIT = 100
ADDITION_LIMIT = 3
NEW_FILE_LIMIT = 2
_SAFE_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EMPTY_LOCATOR = "- No selected locations; use native repository search."


@dataclass(frozen=True, slots=True)
class APlusLocator:
    text: str
    sha256: str
    baseline_sha256: str
    baseline_appendix_estimated_tokens: int
    appendix_estimated_tokens: int
    supplemental_hints: tuple[tuple[str, int, int, str], ...]
    new_file_count: int
    skip_reasons: tuple[tuple[str, int], ...]
    feasibility_failure: bool

    def receipt(self) -> dict[str, object]:
        """Return no task, prompt, source excerpt, or complete locator text."""
        return {
            "a_locator_hash": self.baseline_sha256,
            "a_plus_locator_hash": self.sha256,
            "a_appendix_estimated_tokens": self.baseline_appendix_estimated_tokens,
            "a_plus_appendix_estimated_tokens": self.appendix_estimated_tokens,
            "supplemental_hint_count": len(self.supplemental_hints),
            "new_file_count": self.new_file_count,
            "candidate_skip_reasons": dict(self.skip_reasons),
            "prospective_feasibility_failure": self.feasibility_failure,
            "safety_status": "PASS",
            "estimates_are_provider_usage": False,
            "external_calls": 0,
        }


def _explicit_path(path: str, query: ContextQuery) -> bool:
    task = query.task.replace("\\", "/")
    return (path in {item.replace("\\", "/") for item in query.paths}
            or re.search(r"(?<![\w/])" + re.escape(path) + r"(?![\w/])", task) is not None)


def _explicit_symbol(name: str, query: ContextQuery) -> bool:
    return (name in query.symbols or re.search(
        r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])",
        query.task,
    ) is not None)


def _safe_path(config: GatewayConfig, path: str, redactor: SecretRedactor) -> bool:
    if not path or ":" in path or any(ord(char) < 32 for char in path):
        return False
    if redactor.redact(path).text != path:
        return False
    try:
        if config.relative_path(path) != path:
            return False
        current = config.repository_root
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                return False
        return current.is_file()
    except (ValueError, OSError):
        return False


def _verified_record(config: GatewayConfig, index: RepositoryIndex, path: str,
                     redactor: SecretRedactor) -> tuple[IndexedFile, frozenset[Symbol]] | None:
    if not _safe_path(config, path, redactor):
        return None
    record = index.get_file(path)
    if (record is None or record.path != path or record.language != "Python"
            or record.extension != ".py" or record.parse_status != "parsed"
            or not record.is_text or not record.sha256 or not record.line_count):
        return None
    try:
        source = SourceReader(config, index).read(path)
    except (ValueError, OSError, UnicodeError, StaleSourceError, UnsafeSourceError):
        return None
    if len(source.lines) != record.line_count:
        return None
    parsed = PythonParser().parse(path, source.text)
    if parsed.error:
        return None
    return record, frozenset(parsed.symbols)


def _valid_symbol(symbol: Symbol, record: IndexedFile, parsed: frozenset[Symbol],
                  redactor: SecretRedactor) -> bool:
    if (symbol.kind not in {"function", "method"} or symbol.path != record.path
            or symbol not in parsed
            or _IDENTIFIER.fullmatch(symbol.name) is None
            or _SAFE_SYMBOL.fullmatch(symbol.qualified_name) is None
            or redactor.redact(symbol.qualified_name).text != symbol.qualified_name
            or symbol.end_line is None or record.line_count is None
            or not 1 <= symbol.start_line <= symbol.end_line <= record.line_count):
        return False
    expected = f"{symbol.parent}.{symbol.name}" if symbol.parent else symbol.name
    if symbol.qualified_name != expected or (symbol.kind == "method" and not symbol.parent):
        return False
    if symbol.parent:
        owners = (item for item in record.symbols if item.qualified_name == symbol.parent
                  and item.end_line is not None and item.path == record.path)
        if not any((owner.kind == "class" if symbol.kind == "method"
                    else owner.kind in {"function", "method"})
                   and owner.start_line <= symbol.start_line <= symbol.end_line <= owner.end_line
                   and owner in parsed for owner in owners):
            return False
    return True


def _method_choice(record: IndexedFile, parsed: frozenset[Symbol], query: ContextQuery,
                   explicit_path: bool,
                   redactor: SecretRedactor) -> tuple[Symbol | None, int, int, str]:
    task_terms = terms(query.task)
    supported: list[tuple[int, int, Symbol]] = []
    invalid_supported = False
    for symbol in record.symbols:
        if symbol.kind not in {"function", "method"}:
            continue
        matched = task_terms & terms(symbol.name)
        if _explicit_symbol(symbol.qualified_name, query):
            tier = 0
        elif explicit_path and matched:
            tier = 1
        elif len(matched) >= 2:
            tier = 2
        else:
            continue
        if not _valid_symbol(symbol, record, parsed, redactor):
            invalid_supported = True
            continue
        supported.append((tier, len(matched), symbol))
    if invalid_supported:
        return None, 0, 0, "INVALID_INDEXED_SYMBOL"
    if not supported:
        return None, 0, 0, "NO_METHOD_EVIDENCE"
    best = min((tier, -count) for tier, count, _ in supported)
    winners = [item for item in supported if (item[0], -item[1]) == best]
    if len(winners) != 1:
        return None, 0, 0, "AMBIGUOUS_METHOD"
    tier, count, symbol = winners[0]
    return symbol, tier, count, ""


def _result(text: str, baseline: OfflineLocator, baseline_tokens: int,
            hints: list[tuple[str, int, int, str]], new_files: int,
            skipped: Counter[str], failure: bool) -> APlusLocator:
    return APlusLocator(
        text, hashlib.sha256(text.encode("utf-8")).hexdigest(), baseline.sha256,
        baseline_tokens, HeuristicTokenEstimator().estimate(append_offline_locator("", text)),
        tuple(hints), new_files, tuple(sorted(skipped.items())), failure,
    )


def build_a_plus_locator(config: GatewayConfig, index: RepositoryIndex, query: ContextQuery,
                         baseline: OfflineLocator, *, expected_head: str | None = None) -> APlusLocator:
    """Apply the frozen additive rule; never mutate A or invoke a model."""
    if (index.identity.root != str(config.repository_root)
            or expected_head is not None and index.identity.head != expected_head):
        raise ValueError("index identity differs from pinned repository")
    if (baseline.selector_fingerprint != selector_implementation_fingerprint()
            or baseline.sha256 != hashlib.sha256(baseline.text.encode("utf-8")).hexdigest()):
        raise ValueError("production locator identity changed")
    redactor = SecretRedactor()
    if redactor.redact(baseline.text).text != baseline.text:
        raise ValueError("unsafe production locator")
    baseline_hints = parse_locator(baseline.text)
    for hint in baseline_hints:
        if not _safe_path(config, hint["path"], redactor):
            raise ValueError("unsafe production locator path")
    estimator = HeuristicTokenEstimator()
    baseline_tokens = estimator.estimate(append_offline_locator("", baseline.text))
    skipped: Counter[str] = Counter()
    if baseline_tokens > APPENDIX_LIMIT:
        skipped["BASELINE_OVER_BUDGET"] += 1
        return _result(baseline.text, baseline, baseline_tokens, [], 0, skipped, True)
    if baseline.text == _EMPTY_LOCATOR:
        skipped["EMPTY_BASELINE"] += 1
        return _result(baseline.text, baseline, baseline_tokens, [], 0, skipped, False)

    safe_query = ContextQuery(redactor.redact(query.task).text, query.paths, query.symbols,
                              redactor.redact(query.error_text).text, query.changed_files)
    try:
        ranked = RelevanceEngine(index, config).find(safe_query, top_k=RANKED_FILE_LIMIT)[:RANKED_FILE_LIMIT]
    except StaleSourceError as exc:
        raise RuntimeError("source changed since indexing; A-plus aborted") from exc
    paths = list(dict.fromkeys(item.path for item in ranked))
    explicit_extra = sorted(record.path for record in index.files
                            if record.path not in paths and _explicit_path(record.path, safe_query))
    paths.extend(explicit_extra)
    baseline_paths = {hint["path"] for hint in baseline_hints}
    baseline_locations = {(hint["path"], *hint["range"], hint["symbol"])
                          for hint in baseline_hints}
    choices: list[tuple[int, int, int, str, Symbol]] = []
    for rank, path in enumerate(paths):
        verified = _verified_record(config, index, path, redactor)
        if verified is None:
            skipped["UNSAFE_OR_STALE_FILE"] += 1
            continue
        record, parsed = verified
        symbol, tier, count, reason = _method_choice(
            record, parsed, safe_query, _explicit_path(path, safe_query), redactor,
        )
        if symbol is None:
            skipped[reason] += 1
            continue
        choices.append((tier, -count, rank, path, symbol))

    lines: list[str] = []
    additions: list[tuple[str, int, int, str]] = []
    new_files = 0
    for _, _, _, path, symbol in sorted(choices, key=lambda item: item[:4]):
        if len(additions) >= ADDITION_LIMIT:
            skipped["THREE_HINT_LIMIT"] += 1
            continue
        if path not in baseline_paths and new_files >= NEW_FILE_LIMIT:
            skipped["TWO_NEW_FILE_LIMIT"] += 1
            continue
        location = (path, symbol.start_line, symbol.end_line, symbol.qualified_name)
        if location in baseline_locations or any(
            old_path == path and old_symbol == symbol.qualified_name
            and old_start <= symbol.start_line and symbol.end_line <= old_end
            for old_path, old_start, old_end, old_symbol in baseline_locations
        ):
            skipped["DUPLICATE_OR_REDUNDANT"] += 1
            continue
        line = f"- {path}:{symbol.start_line}-{symbol.end_line} ({symbol.qualified_name})"
        proposed = baseline.text + "\n" + "\n".join((*lines, line))
        if estimator.estimate(append_offline_locator("", proposed)) > APPENDIX_LIMIT:
            skipped["APPENDIX_BUDGET"] += 1
            continue
        lines.append(line)
        additions.append(location)
        if path not in baseline_paths:
            new_files += 1
    text = baseline.text + ("\n" + "\n".join(lines) if lines else "")
    return _result(text, baseline, baseline_tokens, additions, new_files, skipped, False)


def _index_fingerprint(index: RepositoryIndex) -> str:
    records = [(item.path, item.sha256, [(symbol.qualified_name, symbol.kind,
                symbol.start_line, symbol.end_line) for symbol in item.symbols])
               for item in sorted(index.files, key=lambda file: file.path)]
    return hashlib.sha256(json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def run_a_plus_dry_run(root: Path, query: ContextQuery, *, expected_head: str,
                       expected_index_fingerprint: str | None = None) -> dict[str, object]:
    """Build A and A-plus locally on a clean, pinned Git snapshot; emit metadata only."""
    root = validate_repository(root)
    before = capture_repository_state(root)
    if before.status or before.head != expected_head:
        raise ValueError("dry run requires the pinned clean repository HEAD")
    config = GatewayConfig(root, cache_writes_enabled=False)
    try:
        index = RepositoryIndexer(config).index()
        if index.identity.head != expected_head or index.changed_paths:
            raise RuntimeError("index does not belong to the pinned clean source")
        index_fingerprint = _index_fingerprint(index)
        if expected_index_fingerprint is not None and index_fingerprint != expected_index_fingerprint:
            raise RuntimeError("index fingerprint differs from pinned index")
        baseline = build_offline_locator(config, query)
        result = build_a_plus_locator(config, index, query, baseline, expected_head=expected_head)
    finally:
        after = capture_repository_state(root)
        if after != before:
            raise RuntimeError("repository HEAD, status, or Git-visible content changed")
    return {**result.receipt(), "source_head": expected_head,
            "index_fingerprint": index_fingerprint, "repository_integrity": "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Local research-only A-plus locator dry run")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-index-fingerprint")
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    report = run_a_plus_dry_run(args.repo, ContextQuery(args.task),
                                expected_head=args.expected_head,
                                expected_index_fingerprint=args.expected_index_fingerprint)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
