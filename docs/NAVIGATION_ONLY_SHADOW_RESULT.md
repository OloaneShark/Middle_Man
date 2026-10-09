# Navigation-only shadow result

**Decision: REJECTED.** This was one preregistered, local-only candidate. The rule
was frozen in [`NAVIGATION_ONLY_SHADOW_RULE.md`](NAVIGATION_ONLY_SHADOW_RULE.md)
before evaluating the six development tasks. The source-free, metadata-only result
is [`navigation_only_shadow_result.json`](navigation_only_shadow_result.json).
No production locator, relevance score, AUTO behavior, ContextBuilder, frozen input,
or historical experiment was changed. No model or A/B call was made.

## Integration and rule

Production first creates the top-50 relevance candidates, reads and proposes source
ranges, then allocates selected Context Pack excerpts under its 6,000 estimated
source-token budget. `build_offline_locator` formats only those selected excerpts'
paths, ranges, and optional safe symbols. Thus source-token budgeting and
task-cluster exclusions affect which *source-free* navigation hints reach Codex,
even though excerpt text itself never enters the prompt.

The shadow instead walks the identical top-50 `RelevanceEngine` order directly.
It emits at most one verified indexed-symbol range per path, or a file-level
`1-line_count` fallback, without consulting excerpt cost or source allocation.
It keeps only hints that fit the original task's **full model-visible locator
appendix** heuristic estimate. The result records valid candidates skipped by
that prompt budget. This does not equate prompt tokens with internal source tokens.

The pinned source is commit `0680a1cb8812d35b17ebd628de7ffba95798da7f`,
tree `6276b4a959bc93df8bb82cdde0bfc371d2c99770`, balanced mode, internal
Context Pack budget 6,000. All six production baseline locator hashes and their
navigation counts were reproduced; each shadow's candidate pool exactly matched
the production pack's 50 candidates. The snapshot remained clean.

## Development comparison

Values are production baseline / shadow. `Appendix` is the heuristic estimate of
the entire fixed wrapper plus locator, not provider-reported input usage.

| Task | Navigable areas | Cited refs targeted | Range hits | Symbol hits | Broad hints | Shadow paths | Appendix tokens | Budget-skipped paths |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N01 | 3/3 / 3/3 | 3 / 3 | 3 / 3 | 0 / 0 | 5 / 0 | 9 | 228 / 223 | 41 |
| M02 | 1/4 / 2/4 | 2 / 4 | 2 / 2 | 2 / 1 | 3 / 0 | 19 | 397 / 393 | 31 |
| C02 | 1/3 / 1/3 | 1 / 2 | 1 / 1 | 0 / 0 | 1 / 2 | 18 | 339 / 338 | 32 |
| T01 | 0/3 / 0/3 | 0 / 4 | 0 / 1 | 0 / 0 | 0 / 0 | 15 | 375 / 371 | 35 |
| G02 | 0/2 / 1/2 | 1 / 1 | 0 / 1 | 0 / 0 | 1 / 5 | 15 | 288 / 284 | 35 |
| E01 | 1/1 / 1/1 | 1 / 1 | 1 / 1 | 0 / 1 | 4 / 1 | 10 | 220 / 220 | 40 |

Total navigable proposed areas increased **6/16 to 8/16**, but this aggregate
conceals a disallowed regression. N01 retained all three areas. M02 retained
`entry` and gained `selection_delivery`; G02 gained `range_selection`. E01
retained `victim_policy` and its explicit `lab/preemption.py` anchor. C02 **lost**
its previously navigable `candidates` area while gaining `ranges`, so the
no-loss condition failed. All other predeclared conditions passed, including
test-focused nonweakening and every appendix budget. This is a rejection, not a
net-score win or permission to activate the candidate.

## Mechanisms and remaining misses

- **M02 candidate cap:** `gateway/indexer.py` remains outside the unchanged top-50
  pool. Independent hint budgeting cannot retrieve it. The shadow added
  `gateway/context_builder.py:69-375` (an indexed class span), making the
  proposed `selection_delivery` area navigable, but `gateway/relevance.py:41-46`
  still points away from its cited `find` interval.
- **T01 affinity bypass, insufficient precision:** All cited Phase 8 test and
  `lab/memory.py`/`lab/prefix_cache.py` paths were emitted, unlike production's
  task-cluster exclusions. The test hint targets lines 57-68 rather than the
  cited 8-21 and 33-54 tests; memory targets 120-130 rather than 89-118.
  Prefix-cache intersects, but neither complete multi-file implementation
  option nor either cited test area is navigable.
- **G02 indexed-symbol behavior:** Its gain comes from the broad
  `gateway/context_builder.py:69-375` class span overlapping the cited interval.
  `gateway/relevance.py` and `gateway/selection.py` were omitted by the fixed
  prompt budget. This is not evidence of a precise indexed `find` hint.
- **C02 regression:** The shadow targets `gateway/relevance.py:41-46` via
  `ContextQuery`, missing cited `RelevanceEngine.find:133-145`. It adds a broad
  `ContextBuilder` span, trading away the old `candidates` area for `ranges`.
- **Symbol precision:** E01's indexed `choose_victim` method adds one exact
  symbol match. Other gains often arise from broad class spans, and the shadow
  has fewer symbol matches than baseline for M02. Indexed symbols do not
  uniformly improve useful precision.

The JSON records selected paths/ranges/symbols, hashes, missing cited paths,
explicit-anchor retention, and prompt-budget omissions. Paths not present in
the proposed references are labeled **UNKNOWN**, not irrelevant. Valid paths
skipped by the fixed appendix cap range from 31 to 41 per task, so this study
cannot isolate whether a different prompt budget would help. Such a change
would require a new prospective rule, not post hoc tuning here.

## Interpretation

This candidate demonstrates that source-allocation independence can add cited
paths without increasing estimated prompt overhead, but path targeting alone
does not ensure useful ranges. The reference set is proposed, not independently
human-validated; N01's ownership interval and G02's `selection.py` alternative
retain their earlier errata. Structural navigation does not establish Codex's
native exploration, answer correctness, or provider token savings. The rejected
rule is not activated; any future work must address both range choice and
no-regression behavior under a new prospective design.
