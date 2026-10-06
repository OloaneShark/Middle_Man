"""Prospective production A/B reviews grade meaning, not symbol parroting."""

from __future__ import annotations

from dataclasses import replace

from middle_man.gateway.codex_runner.correctness import (
    MODULE_AREAS, PRECISION_SYMBOLS, SemanticReview, score_semantic_answer,
)


GOOD = (
    "middle_man/gateway/codex_runner/events.py uses parse_production_events to validate "
    "JSONL framing, delegate native metrics to the shared parser, and separately derive "
    "production search telemetry from completed commands. Explicit reads are only "
    "conservative direct reads; content-producing rg/grep/Select-String searches remain "
    "searches, not reads. middle_man/gateway/codex_runner/search_telemetry.py uses "
    "summarize_searches and its classifier to separate content-producing matches, "
    "file-targeted or repository-wide searches, and file listings. It retains safe "
    "repository-relative target paths only, rejecting outside-root targets, traversal, "
    "ambiguous shell syntax, and unresolvable targets. "
    "middle_man/gateway/codex_runner/execution.py uses run_codex to keep explicitly read "
    "locator paths, locator paths targeted by searches, and non-locator searched paths "
    "separate. middle_man/gateway/codex_runner/audit.py uses sanitized_receipt and "
    "save_audit to retain aggregate metadata while omitting the full user task, "
    "constructed prompt, source excerpts, raw JSONL events, full shell commands, "
    "search terms, and final answer."
)

GOOD_CONCEPTS = {
    "conservative_explicit_reads": "Explicit reads are only conservative direct reads",
    "searches_remain_searches": "content-producing rg/grep/Select-String searches remain searches, not reads",
    "production_event_flow": "validate JSONL framing, delegate native metrics to the shared parser, and separately derive production search telemetry",
    "search_classification": "separate content-producing matches, file-targeted or repository-wide searches, and file listings",
    "safe_search_targets": "safe repository-relative target paths only, rejecting outside-root targets, traversal, ambiguous shell syntax, and unresolvable targets",
    "separate_locator_coverage": "explicitly read locator paths, locator paths targeted by searches, and non-locator searched paths separate",
}
GOOD_PRIVACY = {
    "full_task": "omitting the full user task",
    "constructed_prompt": "constructed prompt",
    "source_excerpts": "source excerpts",
    "raw_events": "raw JSONL events",
    "full_commands": "full shell commands",
    "search_terms": "search terms",
    "final_answer": "final answer",
}


def good_review() -> SemanticReview:
    return SemanticReview(GOOD_CONCEPTS, {area: area for area in MODULE_AREAS}, GOOD_PRIVACY)


def test_full_exact_symbol_answer_passes() -> None:
    answer = GOOD + " classify_search_command performs the classification."
    score = score_semantic_answer(answer, good_review())
    assert score.passed and score.core_correctness == 6
    assert score.module_coverage == 4 and score.symbol_precision == 6
    assert score.privacy_correctness and not score.material_errors


def test_conceptual_answer_missing_one_identifier_passes() -> None:
    assert "classify_search_command" not in GOOD
    score = score_semantic_answer(GOOD, good_review())
    assert score.passed and score.symbol_precision == 5


def test_rg_searches_called_explicit_reads_fails() -> None:
    answer = GOOD.replace("searches remain searches, not reads", "searches count as explicit reads")
    review = replace(good_review(), material_errors=("rg searches conflated with reads",))
    score = score_semantic_answer(answer, review)
    assert not score.passed and "searches_remain_searches" in score.missing_concepts
    assert score.material_errors


def test_receipt_claimed_to_store_commands_and_terms_fails() -> None:
    answer = GOOD.replace(
        "omitting the full user task, constructed prompt, source excerpts, raw JSONL events, "
        "full shell commands, search terms, and final answer",
        "omitting the full user task, constructed prompt, source excerpts, raw JSONL events, "
        "and final answer while storing full shell commands and search terms",
    )
    omissions = {key: value for key, value in GOOD_PRIVACY.items()
                 if key not in {"full_commands", "search_terms"}}
    review = replace(good_review(), privacy_omissions=omissions,
                     material_errors=("receipt claimed to persist commands and search terms",))
    score = score_semantic_answer(answer, review)
    assert not score.passed and not score.privacy_correctness
    assert set(score.missing_privacy_omissions) == {"full_commands", "search_terms"}


def test_missing_locator_coverage_distinction_fails() -> None:
    answer = GOOD.replace(
        "middle_man/gateway/codex_runner/execution.py uses run_codex to keep explicitly read "
        "locator paths, locator paths targeted by searches, and non-locator searched paths "
        "separate. ",
        "middle_man/gateway/codex_runner/execution.py uses run_codex. ",
    )
    score = score_semantic_answer(answer, good_review())
    assert not score.passed and score.missing_concepts == ("separate_locator_coverage",)


def test_all_symbols_do_not_rescue_materially_wrong_answer() -> None:
    answer = (GOOD.replace("searches remain searches, not reads", "searches count as explicit reads")
              + " classify_search_command names the classifier.")
    review = replace(good_review(), material_errors=("rg searches conflated with reads",))
    score = score_semantic_answer(answer, review)
    assert score.symbol_precision == len(PRECISION_SYMBOLS) and not score.passed


PRIOR_CONDENSED_BASELINE = (
    "Explicit reads retain the shared parser's conservative direct-read classification; "
    "searches and listings do not become reads. Production parse_production_events passes "
    "valid events to that parser and separately sends completed commands to summarize_searches. "
    "The classifier recognizes rg, grep, git grep, and Select-String, distinguishing "
    "content-producing, listing, file-targeted, and repository-wide searches without "
    "claiming the model read search output. Target extraction rejects ambiguous commands, "
    "traversal, globs, variables, missing or outside-root paths, and redacted paths; accepted "
    "targets are relative, with directory searches not credited to every descendant file. "
    "run_codex keeps locator explicit reads, locator search targets, and non-locator search "
    "targets separate. Optional sanitized_receipt/save_audit receipts retain aggregate "
    "metadata while omitting the task, constructed prompt, source excerpts, raw events, "
    "full commands, search terms, and final answer."
)


def test_prior_condensed_baseline_passes_prospectively() -> None:
    review = SemanticReview(
        concepts={
            "conservative_explicit_reads": "shared parser's conservative direct-read classification",
            "searches_remain_searches": "searches and listings do not become reads",
            "production_event_flow": "parse_production_events passes valid events to that parser and separately sends completed commands to summarize_searches",
            "search_classification": "distinguishing content-producing, listing, file-targeted, and repository-wide searches",
            "safe_search_targets": "rejects ambiguous commands, traversal, globs, variables, missing or outside-root paths, and redacted paths; accepted targets are relative",
            "separate_locator_coverage": "locator explicit reads, locator search targets, and non-locator search targets separate",
        },
        modules=dict(zip(MODULE_AREAS, (
            "The classifier recognizes rg, grep, git grep, and Select-String",
            "parse_production_events passes valid events",
            "run_codex keeps locator explicit reads",
            "sanitized_receipt/save_audit receipts retain aggregate metadata",
        ))),
        privacy_omissions={
            "full_task": "omitting the task",
            "constructed_prompt": "constructed prompt",
            "source_excerpts": "source excerpts",
            "raw_events": "raw events",
            "full_commands": "full commands",
            "search_terms": "search terms",
            "final_answer": "final answer",
        },
    )
    assert "classify_search_command" not in PRIOR_CONDENSED_BASELINE
    score = score_semantic_answer(PRIOR_CONDENSED_BASELINE, review)
    assert score.passed and score.core_correctness == 6
    assert score.module_coverage == 4 and score.privacy_correctness
    assert score.symbol_precision == 5


def test_exact_symbol_is_required_only_when_task_names_it() -> None:
    score = score_semantic_answer(GOOD, good_review(),
                                  task_required_symbols=("classify_search_command",))
    assert not score.passed and score.missing_required_symbols == ("classify_search_command",)
