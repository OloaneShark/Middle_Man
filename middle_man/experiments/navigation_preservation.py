"""Source-free, non-selective locator hint preservation and cost accounting."""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

from middle_man.experiments.locator_navigation_eval import parse_locator
from middle_man.experiments.source_selection_reference_eval import _safe_path
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator


_SAFE_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True, slots=True)
class Hint:
    path: str
    start: int
    end: int
    symbol: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "start_line": self.start,
                "end_line": self.end, "symbol": self.symbol}


def checked_hints(records: Iterable[dict[str, object]], config: GatewayConfig) -> tuple[Hint, ...]:
    """Validate committed source-free records against the pinned repository."""
    redactor = SecretRedactor()
    hints = []
    for record in records:
        path = record["path"]
        interval = record["range"]
        symbol = record["symbol"]
        if (not isinstance(path, str) or _safe_path(path) != path
                or config.relative_path(path) != path or any(ord(char) < 32 for char in path)
                or redactor.redact(path).text != path or not config.resolve_path(path).is_file()):
            raise ValueError("unsafe or missing locator path")
        if (not isinstance(interval, (list, tuple)) or len(interval) != 2
                or any(type(value) is not int for value in interval)
                or interval[0] < 1 or interval[1] < interval[0]):
            raise ValueError("invalid locator interval")
        if symbol is not None and (not isinstance(symbol, str)
                                   or _SAFE_SYMBOL.fullmatch(symbol) is None
                                   or redactor.redact(symbol).text != symbol):
            raise ValueError("unsafe locator symbol")
        hints.append(Hint(path, interval[0], interval[1], symbol))
    return tuple(hints)


def format_hints(hints: Iterable[Hint]) -> str:
    """Use production-compatible grouped path and semicolon range syntax."""
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for hint in hints:
        label = f"{hint.start}-{hint.end}"
        if hint.symbol is not None:
            label += f" ({hint.symbol})"
        grouped.setdefault(hint.path, []).append(label)
    if not grouped:
        return "- No selected locations; use native repository search."
    text = "\n".join(f"- {path}:{'; '.join(labels)}" for path, labels in grouped.items())
    if len(parse_locator(text)) != sum(len(labels) for labels in grouped.values()):
        raise RuntimeError("formatted hints failed production-compatible parse")
    return text


def measure(text: str) -> dict[str, int | str]:
    locator_bytes = len(text.encode("utf-8"))
    appendix = append_offline_locator("", text)
    appendix_bytes = len(appendix.encode("utf-8"))
    estimator = HeuristicTokenEstimator()
    return {"locator_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "locator_bytes": locator_bytes, "locator_estimated_tokens": estimator.estimate(text),
            "appendix_bytes": appendix_bytes, "appendix_estimated_tokens": estimator.estimate(appendix),
            "fixed_wrapper_bytes": appendix_bytes - locator_bytes}


def _cost_components(hints: tuple[Hint, ...], text: str) -> dict[str, int]:
    grouped: OrderedDict[str, list[Hint]] = OrderedDict()
    for hint in hints:
        grouped.setdefault(hint.path, []).append(hint)
    path_bytes = sum(len(path.encode("utf-8")) for path in grouped)
    range_bytes = sum(len(f"{hint.start}-{hint.end}".encode("utf-8")) for hint in hints)
    symbol_bytes = sum(len(f" ({hint.symbol})".encode("utf-8")) for hint in hints
                       if hint.symbol is not None)
    separators = 3 * len(grouped) + max(0, len(grouped) - 1)
    separators += 2 * sum(len(items) - 1 for items in grouped.values())
    if path_bytes + range_bytes + symbol_bytes + separators != len(text.encode("utf-8")):
        raise RuntimeError("locator byte cost decomposition differs")
    return {"path_bytes": path_bytes, "range_bytes": range_bytes,
            "symbol_bytes": symbol_bytes, "format_separator_bytes": separators}


def preservation_scenario(base: tuple[Hint, ...], supplements: Iterable[tuple[Hint, ...]],
                          *, appendix_budget: int) -> dict[str, object]:
    """Keep all originals and all distinct additions; measure, never trim."""
    if appendix_budget < 1:
        raise ValueError("appendix budget must be positive")
    combined = list(dict.fromkeys(base))
    seen = set(combined)
    duplicates = len(base) - len(combined)
    unique_additions = 0
    additions_beyond_budget = 0
    estimator = HeuristicTokenEstimator()
    for source in supplements:
        for hint in source:
            if hint in seen:
                duplicates += 1
                continue
            seen.add(hint)
            combined.append(hint)
            unique_additions += 1
            if estimator.estimate(append_offline_locator("", format_hints(combined))) > appendix_budget:
                additions_beyond_budget += 1
    text = format_hints(combined)
    parsed = parse_locator(text)
    final = tuple(Hint(item["path"], *item["range"], item["symbol"]) for item in parsed)
    if not set(base) <= set(final):
        raise RuntimeError("original locator hint lost")
    original_paths = tuple(dict.fromkeys(hint.path for hint in base))
    final_paths = tuple(dict.fromkeys(hint.path for hint in final))
    if final_paths[:len(original_paths)] != original_paths:
        raise RuntimeError("original locator path order changed")
    for path in original_paths:
        before = tuple(hint for hint in dict.fromkeys(base) if hint.path == path)
        after = tuple(hint for hint in final if hint.path == path)
        if after[:len(before)] != before:
            raise RuntimeError("original same-path hint order changed")
    costs = measure(text)
    components = _cost_components(final, text)
    return {"hints": [hint.as_dict() for hint in final],
            "selected_paths": list(final_paths), "distinct_paths": len(final_paths),
            "distinct_locations": len({(hint.path, hint.start, hint.end) for hint in final}),
            "distinct_hints": len(final), "exact_duplicates_removed": duplicates,
            "unique_supplemental_hints": unique_additions,
            "supplemental_hints_beyond_budget_in_input_order": additions_beyond_budget,
            "appendix_budget": appendix_budget,
            "appendix_over_under_tokens": costs["appendix_estimated_tokens"] - appendix_budget,
            "fits_fixed_budget": costs["appendix_estimated_tokens"] <= appendix_budget,
            **costs, **components}
