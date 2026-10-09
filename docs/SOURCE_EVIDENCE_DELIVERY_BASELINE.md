# Development Source-Evidence Delivery Baseline

This is a **local-only**, metadata-level audit of the unchanged production `ContextBuilder`, using the six development labels in `docs/source_selection_reference_dataset.json`. No Codex or Claude inference ran. The reserved labels were not evaluated; because they are committed alongside the development labels, they are an operational holdout, **not a blind dataset**. Detailed excerpt bounds, per-excerpt local token estimates, area/option statuses, and diagnostics are in `docs/source_evidence_delivery_baseline.json`. No excerpt text is saved there.

## Frozen inputs

- Source commit `0680a1cb8812d35b17ebd628de7ffba95798da7f`, tree `6276b4a959bc93df8bb82cdde0bfc371d2c99770`, source fingerprint `6f360e98d7d87339129d0fde8725b6e26a03fcdf0f16f9a24d8c7a3f6a3db340`.
- Frozen 24-task corpus and its task hashes, reference dataset checksum, selector fingerprint `3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`.
- Balanced mode, 6,000 estimated source-token budget, 50-candidate production cap. Snapshot remained Git-clean. Token counts are local estimates, not Codex billing or savings.

## Coverage

| Task | Path-covered core areas | Full cited ranges | Missing core evidence | Selected source tokens |
| --- | ---: | ---: | --- | ---: |
| N01 | 3/3 | 3/3 | None; supporting prefix-cache test also full | 5,970 |
| M02 | 1/4 | 1/4 | Index, ranking, selection/delivery files absent | 5,967 |
| C02 | 1/3 | 1/3 | Index relationships and range assembly files absent | 5,936 |
| T01 | 0/3 | 0/3 | Both cited test intervals and implementation files absent | 5,936 |
| G02 | 1/2 | 0/2 | `relevance.py` selected, but only lines 39-47 delivered, not cited 74-182; selection alternative files absent | 5,935 |
| E01 | 1/1 | 1/1 | None; explicit preemption anchor retained | 5,961 |

Aggregate: 7/16 areas have their referenced path set, **6/16 have all cited lines**, 9/16 have no referenced file excerpt, and 1/16 has a selected file but no cited lines. There were no partially covered cited intervals in this six-task run; synthetic tests cover partial and multi-excerpt cases. T01's two test citations are missing, while N01's cited test interval is fully delivered. G02 retains its pre-existing unresolved scope note. Full-range status means structural line coverage only; it cannot prove answer correctness or that redaction preserved semantics.

## Observed omissions

- **Budget allocation:** M02 ranks `relevance.py` and `context_builder.py`, but both have `context_budget` diagnostics; C02 similarly omits `indexer.py` and `context_builder.py`; G02 omits `context_builder.py` and `selection.py`. Several proposed ranges are entire files, which do not fit after earlier selections. This is an observed diagnostic, not proof that a different allocation would improve answers.
- **Candidate cap:** M02's core `indexer.py` is present in uncapped local ranking but beyond the production candidate cap. C02's supporting `parsers.py` and G02's supporting `indexer.py` are likewise beyond the cap. This distinction is based on the same local `RelevanceEngine` query with a full-file-count top-k, not on model search paths.
- **Task clustering:** T01's cited test file, `prefix_cache.py`, and `memory.py` all appear among production candidates and proposed ranges, but each has `outside_task_cluster`; unrelated Phase 22 test excerpts are selected. The observed decision is clear. Whether test/source competition is the cause, rather than a symptom of task affinity, remains a hypothesis.
- **Excerpt selection:** G02 selects `relevance.py` but delivers only its `ContextQuery` lines 39-47; the cited `RelevanceEngine.find` interval 74-182 is not delivered. Thus a file hit overstates evidence coverage.

Overall the principal measured failure is **file/range allocation before delivery**: nine missing-file areas versus one selected-file/wrong-range area. Ranking/cap contributes to one core area; budget and affinity decisions account for most other missing core paths. The pack alone cannot establish causal impact on an eventual model answer.

## Reference integrity

The development citations all point to existing files, valid line intervals, and overlapping AST symbol spans (`citation_span_issues: []`). Two semantic concerns remain **proposed dataset errata**, not edits to the frozen labels:

1. N01's ownership citation, `middle_man/lab/memory.py:112-130`, shows reference release but not the earlier cache retain and shared attach operations at lines 89-105. Its stated behavior may need a broader interval after separate review.
2. G02's alternative `middle_man/gateway/selection.py:175-326` establishes budget allocation, but alone may not establish conversion of candidates into delivered source excerpts. Its validity as a complete alternative needs review.

## Next experiment

A single **shadow-only** candidate is to test narrower, symbol-centered proposals for large full-file candidates before budget allocation, with the development references as diagnostics and the reserved split held out. Do not alter production AUTO or treat this baseline as evidence of token savings. T01's independent cluster omission must remain visible in that experiment rather than being explained away by the budget result.
