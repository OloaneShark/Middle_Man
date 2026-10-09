"""Research-only, path-preserving refinement of indexed navigation hints."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from middle_man.experiments.locator_navigation_eval import parse_locator
from middle_man.experiments.navigation_only_shadow import ShadowLocator
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.models import IndexedFile, RepositoryIndex, Symbol
from middle_man.gateway.relevance import ContextQuery, lexical_family, terms
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator


_SAFE_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True, slots=True)
class PrecisionLocator:
    text: str
    sha256: str
    appendix_estimated_tokens: int
    selected_paths: tuple[str, ...]
    substitutions: tuple[tuple[str, int, int, str, str], ...]
    ambiguous_paths: tuple[str, ...]
    budget_blocked_paths: tuple[str, ...]


def _explicit_anchor(symbol: Symbol, query: ContextQuery) -> bool:
    name = symbol.qualified_name
    return (name in query.symbols or symbol.name in query.symbols
            or re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])",
                         query.task) is not None)


def _best_symbol(record: IndexedFile, query: ContextQuery,
                 redactor: SecretRedactor) -> tuple[Symbol | None, str]:
    query_terms = terms(query.task)
    ranked: list[tuple[tuple[int, int], Symbol, str]] = []
    for symbol in record.symbols:
        end = symbol.end_line or symbol.start_line
        name = symbol.qualified_name
        if (symbol.kind not in {"function", "method"} or symbol.path != record.path
                or record.line_count is None or not 1 <= symbol.start_line <= end <= record.line_count
                or _SAFE_SYMBOL.fullmatch(name) is None or redactor.redact(name).text != name):
            continue
        name_terms = terms(symbol.name)
        matched = {word for word in query_terms
                   if any(word == part or lexical_family(word, part) for part in name_terms)}
        anchored = _explicit_anchor(symbol, query)
        score = (int(anchored), sum(len(word) for word in matched))
        if score != (0, 0):
            ranked.append((score, symbol, "explicit_anchor" if anchored else "task_lexical"))
    if not ranked:
        return None, "no_unique_evidence"
    best = max(item[0] for item in ranked)
    winners = [item for item in ranked if item[0] == best]
    if len(winners) != 1:
        return None, "ambiguous_evidence"
    return winners[0][1], winners[0][2]


def refine_navigation_hints(config: GatewayConfig, index: RepositoryIndex,
                            query: ContextQuery, shadow: ShadowLocator, *,
                            max_appendix_tokens: int) -> PrecisionLocator:
    """Change only B's within-file spans and symbols, never its path sequence."""
    if max_appendix_tokens < 1 or shadow.appendix_estimated_tokens > max_appendix_tokens:
        raise ValueError("invalid fixed appendix budget")
    hints = parse_locator(shadow.text)
    if (len(hints) != len(shadow.selected_paths)
            or tuple(hint["path"] for hint in hints) != shadow.selected_paths):
        raise ValueError("B locator must have exactly one hint per selected path")
    lines = shadow.text.splitlines()
    redactor = SecretRedactor()
    estimator = HeuristicTokenEstimator()
    substitutions: list[tuple[str, int, int, str, str]] = []
    ambiguous: list[str] = []
    budget_blocked: list[str] = []
    for position, hint in enumerate(hints):
        path = hint["path"]
        if (config.relative_path(path) != path or redactor.redact(path).text != path
                or not config.resolve_path(path).is_file()):
            raise ValueError("unsafe B-selected navigation path")
        record = index.get_file(path)
        if record is None:
            raise ValueError("B-selected path absent from index")
        symbol, evidence = _best_symbol(record, query, redactor)
        if symbol is None:
            if evidence == "ambiguous_evidence":
                ambiguous.append(path)
            continue
        end = symbol.end_line or symbol.start_line
        new_line = f"- {path}:{symbol.start_line}-{end} ({symbol.qualified_name})"
        if new_line == lines[position]:
            continue
        proposed = list(lines)
        proposed[position] = new_line
        if estimator.estimate(append_offline_locator("", "\n".join(proposed))) > max_appendix_tokens:
            budget_blocked.append(path)
            continue
        lines[position] = new_line
        substitutions.append((path, symbol.start_line, end, symbol.qualified_name, evidence))
    text = "\n".join(lines)
    final_hints = parse_locator(text)
    selected = tuple(hint["path"] for hint in final_hints)
    if selected != shadow.selected_paths:
        raise RuntimeError("precision refinement changed path decisions")
    appendix_tokens = estimator.estimate(append_offline_locator("", text))
    if appendix_tokens > max_appendix_tokens:
        raise RuntimeError("precision refinement exceeded fixed appendix budget")
    return PrecisionLocator(text, hashlib.sha256(text.encode("utf-8")).hexdigest(),
                            appendix_tokens, selected, tuple(substitutions),
                            tuple(ambiguous), tuple(budget_blocked))
