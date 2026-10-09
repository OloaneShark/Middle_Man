# Navigation hint precision shadow result

**Decision: REJECTED.** The within-file rule was frozen in
[`NAVIGATION_HINT_PRECISION_RULE.md`](NAVIGATION_HINT_PRECISION_RULE.md) before
one development-only measurement. The [metadata result](navigation_hint_precision_result.json)
compares A (production), B (previously rejected navigation-only shadow), and
C (the path-preserving precision variation). No model calls were made.

## Fixed comparison

The input source was commit `0680a1cb8812d35b17ebd628de7ffba95798da7f`
(tree `6276b4a959bc93df8bb82cdde0bfc371d2c99770`). The original 24-task
corpus, proposed reference dataset, production navigation audit, and rejected
B result were hash-checked. The six development tasks alone were scored.
Production A and rejected B locator hashes reproduced, and B/C selected path
sequences were identical for every task. Relevance scores, top-50 cap, file
choices, and path ordering did not change. C's appendix estimates all fit the
original A per-task ceilings. Production behavior was not modified.

The C rule examines indexed functions/methods within each B-selected file.
An explicit qualified code anchor wins; otherwise distinct task-word matches
to function/method names are scored by matched word length. A unique positive
winner may replace B's range and label if the full appendix still fits.
Class-name evidence alone, ties, unsafe spans/labels, and oversized replacements
retain B's original hint. This is lexical evidence, not semantic proof.

## Results

Counts are A / B / C. `Broad` includes whole-file or indexed class hints.
`Appendix` is a local heuristic estimate of the whole locator appendix, not
provider-reported input tokens.

| Task | Navigable areas | Cited paths targeted | Range intersections | Function/method symbol matches | Broad hints | Appendix tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N01 | 3/3 / 3/3 / 3/3 | 3 / 3 / 3 | 3 / 3 / 3 | 0 / 0 / 0 | 10 / 3 / 3 | 228 / 223 / 225 |
| M02 | 1/4 / 2/4 / 1/4 | 2 / 4 / 4 | 2 / 2 / 1 | 2 / 1 / 0 | 8 / 5 / 5 | 397 / 393 / 397 |
| C02 | 1/3 / 1/3 / 1/3 | 1 / 2 / 2 | 1 / 1 / 1 | 0 / 0 / 0 | 7 / 7 / 7 | 339 / 338 / 339 |
| T01 | 0/3 / 0/3 / 2/3 | 0 / 4 / 4 | 0 / 1 / 3 | 0 / 0 / 1 | 1 / 1 / 1 | 375 / 371 / 375 |
| G02 | 0/2 / 1/2 / 1/2 | 1 / 1 / 1 | 0 / 1 / 1 | 0 / 0 / 0 | 6 / 8 / 8 | 288 / 284 / 284 |
| E01 | 1/1 / 1/1 / 1/1 | 1 / 1 / 1 | 1 / 1 / 1 | 0 / 1 / 1 | 10 / 3 / 3 | 220 / 220 / 220 |

Totals: **A 6/16, B 8/16, C 9/16** navigable proposed areas. The net C gain
does **not** pass the frozen acceptance rule. M02 loses `entry`, which was
navigable under both A and B. C02 still lacks A's `candidates` area. Thus both
no-A-loss and no-B-loss conditions fail. The supported-gain, explicit-anchor,
appendix, path-parity, and safety conditions pass. No post-result tuning was done.

## What changed within files

- **T01:** The Phase 8 test hint moved to
  `test_shared_block_references_survive_individual_releases:8-21`, an exact
  function-level reference match supported by task words. A memory hint moved
  to `KVBlockManager.release_cache_blocks:107-110`, intersecting the proposed
  implementation interval. Alongside the unchanged prefix-cache hint, the
  `refcount_test` and `implementation` areas became structurally navigable.
  The second cited test interval remains missed. This is not proof of answer
  correctness or that the memory method alone explains ownership.
- **M02 regression:** A lexical `selection` match changed
  `MCPGateway.context:266-320` to `MCPGateway.explain_selection:516-527`.
  That removed the useful entry interval. The B `selection_delivery` area
  remained, but the A/B `entry` area was lost. `gateway/indexer.py` remains
  beyond the unchanged top-50 candidate cap.
- **C02:** The B `gateway/relevance.py:41-46` hint still targets
  `ContextQuery`, not cited `RelevanceEngine.find:133-145`. No unique
  function-name evidence in the task justified changing it. C retains B's
  `ranges` area but not A's `candidates` area.
- **G02:** No replacement was supported; B/C still use a broad
  `ContextBuilder` class span for `range_selection`. No precise method hint
  was gained. The proposed `selection.py` alternative remains disputed.
- **E01:** The existing accurate `choose_victim` indexed hint and explicit
  `lab/preemption.py` path anchor remained unchanged.
- **N01:** Its three areas remained navigable. Two unrelated hints changed;
  prefix-cache and memory replacements that would exceed the fixed appendix
  ceiling were retained. The ownership-reference interval caveat remains.

Incorrect-location paths and every safe B/C hint are in the JSON. Missing
candidate paths and ranking problems were intentionally left untouched.
The references are proposed, not independently human-validated; N01 ownership
and G02's selection alternative retain their prior errata. Structural range
intersection or a symbol match does not establish native Codex exploration,
answer quality, or provider token savings. C is not eligible for production
activation or further promotion under this preregistered decision.
