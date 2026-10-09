# Source-free locator navigation audit

This is a local-only, development-only structural audit. The machine-readable record is
[`source_free_locator_navigation_audit.json`](source_free_locator_navigation_audit.json).
The evaluator is `middle_man/experiments/locator_navigation_eval.py`. It ran the unchanged
`build_offline_locator` against the six development prompts from the frozen 24-task corpus,
using pinned source commit `0680a1cb8812d35b17ebd628de7ffba95798da7f`, tree
`6276b4a959bc93df8bb82cdde0bfc371d2c99770`, balanced mode, and a 6,000-token
internal context budget. The selector fingerprint was
`3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`.
No reserved reference labels, model calls, or rejected selector shadows were used.

## What the production prompt contains

`preview_codex` builds a local Context Pack, calls `build_offline_locator`, checks that the
pack fingerprints agree, and applies the existing read-only AUTO decision. For all six
development cases AUTO selected `LOCATOR USED` because the candidate source estimate
exceeded 10,000 tokens and locations were selected. The model-visible prompt is the
original task, followed by `MIDDLE_MAN LOCAL LOCATOR`, a fixed navigation instruction,
lines of `- repository/path:start-end (optional_symbol); ...`, and an instruction to
verify exact behavior using native repository tools. Each range is an actual selected
excerpt's location, and at most one safe symbol label is emitted per excerpt.
**No Context Pack source excerpt text is appended to the production prompt.** The
prompt does not include candidate diagnostics or the internal source-token estimate.
The development task itself may, of course, contain user-written code or symbols.

The JSON records literal locator SHA-256, paths, ranges, safe symbol labels, character
counts, and heuristic token estimates. It does not store task text or source excerpts.
`model_visible_appendix_estimated_tokens` includes the fixed heading and instructions;
`locator_estimated_tokens` measures only the path/range text. Internal selected and
candidate source-token estimates are separate local selection metrics, **not** Codex
input tokens. No provider usage or native exploration was measured in this phase.

## Measurements

`PATH_TARGETED` requires a cited path to be named. `RANGE_INTERSECTS` requires a
literal hint range to overlap the proposed cited interval. `SYMBOL_MATCH` requires a
safe emitted label naming the cited function or method, including qualified methods
in grouped citations. `AREA_NAVIGABLE` requires every reference in at least one
complete option to have its path named and either an overlapping range or matching
symbol. Multi-file options require all participating references. A `BROAD_WHOLE_FILE`
hint spans from line 1 through the file's final line; every other hint is a
`SPECIFIC_RANGE`, not a guarantee of useful precision. Full interval coverage is a
secondary structural diagnostic, not a prerequisite for navigation.

| Task | AUTO | Navigable areas | Cited refs path/range/symbol | Hints broad/specific | Locator chars/tokens | Full appendix tokens | Internal selected source tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N01 | Used | 3/3 | 3/3/0 | 5/10 | 715/179 | 228 | 5,970 |
| M02 | Used | 1/4 | 2/2/2 | 3/28 | 1,391/348 | 397 | 5,967 |
| C02 | Used | 1/3 | 1/1/0 | 1/29 | 1,159/290 | 339 | 5,936 |
| T01 | Used | 0/3 | 0/0/0 | 0/36 | 1,303/326 | 375 | 5,936 |
| G02 | Used | 0/2 | 1/0/0 | 1/25 | 955/239 | 288 | 5,935 |
| E01 | Used | 1/1 | 1/1/0 | 4/13 | 681/171 | 220 | 5,961 |

The six tasks total **6/16 navigable proposed core areas**. Locator-range full
coverage is also 6/16 here, but that coincidence is not a rule: a short overlap or
correct symbol can be navigable without covering a whole citation. The JSON records
each option and reference, all selected paths/ranges/symbols, and each locator hash.

## Missing and misleading navigation

- **N01:** All three proposed areas have a navigable path and overlapping range.
  `prefix_cache.py:1-81` and `memory.py:1-130` are whole-file hints. Their labels
  name classes rather than the cited methods, so the function-level symbol proxy is
  absent, despite useful range intersections.
- **M02:** `mcp/gateway.py` and `mcp/server.py` provide the entry area, with matching
  method labels. `gateway/indexer.py` is beyond the top-50 candidate cap;
  `gateway/relevance.py` and `gateway/context_builder.py` are ranked candidates but
  omitted by allocation. This is not one uniform range-size failure.
- **C02:** `gateway/relevance.py:1-182` navigates its candidate area, but is a broad
  whole-file hint with a nonmatching `ContextQuery` label. `gateway/indexer.py` and
  `gateway/context_builder.py` are allocation omissions.
- **T01:** The cited Phase 8 prefix-cache test, `lab/prefix_cache.py`, and
  `lab/memory.py` are all candidates marked `outside_task_cluster`; none enters the
  locator. The 36 emitted hints are elsewhere, primarily other tests and gateway
  code. This is an affinity issue, not M02's candidate-cap issue.
- **G02:** `gateway/relevance.py` is named, but only at lines 39-47 with a
  `ContextQuery` label, not the cited `RelevanceEngine.find` interval at 74-182.
  `gateway/context_builder.py` and `gateway/selection.py` are allocation omissions.
  Both proposed areas therefore lack a navigable complete option.
- **E01:** `lab/preemption.py:1-36` is a whole-file hint overlapping the cited victim
  policy. Its class label does not identify the cited `choose_victim` method.

The dominant failures differ by task: task-cluster affinity for T01, candidate-cap
ranking plus allocation for M02, allocation for C02, and allocation plus wrong-line
specificity for G02. Missing method-level labels are a secondary precision issue in
otherwise navigable N01, C02, and E01. These observations identify focused future
research questions, not a new selector rule or evidence of a beneficial change.

## Limits

The source-grounded references are **proposed, not independently human-validated**.
N01's `ownership` interval omits earlier cache retain/shared attach operations, and
G02's `selection.py` alternative may not alone establish source delivery. Neither
frozen label was changed. The metrics inspect literal hint structure; they cannot
show whether Codex follows a hint, what it reads, whether it answers correctly, or
whether provider tokens are saved. Internal Context Pack coverage, locator navigation,
native exploration, and provider usage remain distinct. The prior symbol-range
candidate remains rejected; this audit neither retests nor overturns it.
