"""Local, human-evidenced correctness gate for prospective production A/B runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


CORE_CONCEPTS = (
    "conservative_explicit_reads",
    "searches_remain_searches",
    "production_event_flow",
    "search_classification",
    "safe_search_targets",
    "separate_locator_coverage",
)
MODULE_AREAS = (
    "middle_man/gateway/codex_runner/search_telemetry.py",
    "middle_man/gateway/codex_runner/events.py",
    "middle_man/gateway/codex_runner/execution.py",
    "middle_man/gateway/codex_runner/audit.py",
)
PRIVACY_OMISSIONS = (
    "full_task",
    "constructed_prompt",
    "source_excerpts",
    "raw_events",
    "full_commands",
    "search_terms",
    "final_answer",
)
PRECISION_SYMBOLS = (
    "classify_search_command",
    "summarize_searches",
    "parse_production_events",
    "run_codex",
    "sanitized_receipt",
    "save_audit",
)


@dataclass(frozen=True, slots=True)
class SemanticReview:
    """Reviewer judgments with answer spans; evidence is not a keyword classifier."""

    concepts: Mapping[str, str]
    modules: Mapping[str, str]
    privacy_omissions: Mapping[str, str]
    material_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticScore:
    passed: bool
    core_correctness: int
    module_coverage: int
    symbol_precision: int
    privacy_correctness: bool
    material_errors: tuple[str, ...]
    missing_concepts: tuple[str, ...]
    missing_modules: tuple[str, ...]
    missing_privacy_omissions: tuple[str, ...]
    missing_required_symbols: tuple[str, ...]


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _has_symbol(answer: str, symbol: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(symbol) + r"(?![A-Za-z0-9_])", answer) is not None


def _missing(answer: str, keys: tuple[str, ...], evidence: Mapping[str, str]) -> tuple[str, ...]:
    normalized_answer = _normalized(answer)
    return tuple(key for key in keys if not evidence.get(key)
                 or _normalized(evidence[key]) not in normalized_answer)


def score_semantic_answer(answer: str, review: SemanticReview, *,
                          task_required_symbols: tuple[str, ...] = ()) -> SemanticScore:
    """Apply the gate to a human review; never infer semantic truth from keywords."""
    for evidence, keys in ((review.concepts, CORE_CONCEPTS), (review.modules, MODULE_AREAS),
                           (review.privacy_omissions, PRIVACY_OMISSIONS)):
        unknown = set(evidence) - set(keys)
        if unknown:
            raise ValueError("unknown semantic review fields: " + ", ".join(sorted(unknown)))
    missing_concepts = _missing(answer, CORE_CONCEPTS, review.concepts)
    missing_modules = _missing(answer, MODULE_AREAS, review.modules)
    missing_privacy = _missing(answer, PRIVACY_OMISSIONS, review.privacy_omissions)
    missing_required = tuple(symbol for symbol in task_required_symbols if not _has_symbol(answer, symbol))
    return SemanticScore(
        passed=not (missing_concepts or missing_modules or missing_privacy
                    or review.material_errors or missing_required),
        core_correctness=len(CORE_CONCEPTS) - len(missing_concepts),
        module_coverage=len(MODULE_AREAS) - len(missing_modules),
        symbol_precision=sum(_has_symbol(answer, symbol) for symbol in PRECISION_SYMBOLS),
        privacy_correctness=not missing_privacy,
        material_errors=review.material_errors,
        missing_concepts=missing_concepts,
        missing_modules=missing_modules,
        missing_privacy_omissions=missing_privacy,
        missing_required_symbols=missing_required,
    )
