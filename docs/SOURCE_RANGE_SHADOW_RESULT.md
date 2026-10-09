# Symbol-Centered Range Shadow Result

**Decision: REJECT.** This was one frozen, local-only candidate, not a production change. The exact premeasurement rule is in `docs/SOURCE_RANGE_SHADOW_RULE.md`; the metadata-only paired result is `docs/source_range_shadow_result.json`. No raw source excerpts, Codex inference, Claude calls, or external A/B calls were involved. The six-task production baseline was reproduced against its frozen artifact before the candidate was compared.

## Why full files appeared

Balanced mode ordinarily uses a 40-line full-file threshold. More important here, `_select_ranges` can propose a broad class symbol (for example `ContextBuilder:68-375`); import, symbol, and class-header ranges are merged, and `_assemble` promotes merged coverage of at least 75% of a file to a full-file range. That yielded redacted local estimates of 5,858 tokens for `context_builder.py:1-375`, 2,457 for `relevance.py:1-182`, and 1,272 for `memory.py:1-130`. The first two could affect the 6,000-token budget; the memory file was useful complete evidence for N01. Small full-file proposals were not automatically altered.

## Six Development Tasks

| Task | Path-covered core areas, current to shadow | Full cited core areas, current to shadow | Selected source tokens, current to shadow | Narrowed proposals |
| --- | ---: | ---: | ---: | ---: |
| N01 | 3/3 to 3/3 | **3/3 to 2/3** | 5,970 to 5,790 | 1 |
| M02 | 1/4 to 3/4 | 1/4 to 1/4 | 5,967 to 5,971 | 2 |
| C02 | 1/3 to 1/3 | **1/3 to 0/3** | 5,936 to 5,949 | 1 |
| T01 | 0/3 to 0/3 | 0/3 to 0/3 | 5,936 to 5,936 | 0 |
| G02 | 1/2 to 1/2 | 0/2 to 0/2 | 5,935 to 5,935 | 0 |
| E01 | 1/1 to 1/1 | 1/1 to 1/1 | 5,961 to 5,961 | 0 |

Complete core-area range coverage fell from **6/16 to 4/16**. There were no gains in complete areas. The predeclared sensitivity excluding disputed N01 `ownership` and G02 `range_selection` also declines, **5/14 to 4/14**. These are proposed source-grounded references, not human-validated ground truth; neither disputed area was relabeled or edited.

## Delivered Evidence and Mechanisms

- **N01 regression:** The unique-term rule narrowed `memory.py:1-130` (1,272 estimated tokens) to the class header and `attach_shared` region (`21`, `95-106`; 151 proposal tokens). The cited ownership/release interval `112-130` was no longer delivered. Reuse, cache lifetime, and the supporting prefix-cache test remained full. The total pack became only 180 tokens smaller because freed budget was spent on other ranges.
- **M02 false path gain:** The rule narrowed `relevance.py` and `context_builder.py` proposals (2,457 to 1,864 and 5,858 to 2,926 estimated tokens). The shadow pack selected class headers/imports from both files, increasing path-level coverage from 1 to 3 areas, but neither cited implementation interval was delivered. Both retained `context_budget` omissions. Core `indexer.py` remained beyond the unchanged candidate cap.
- **C02 regression:** A narrower `RelevanceEngine.find` proposal replaced the previously delivered full `relevance.py` file. The unchanged allocator omitted that narrower proposal with `context_budget`, losing the complete candidate-ranking interval `133-145`. `indexer.py` and `context_builder.py` stayed budget-omitted; supporting `parsers.py` remained beyond the cap.
- **T01 and G02 unchanged:** T01's cited test and implementation candidates still have `outside_task_cluster`, regardless of saved proposal cost elsewhere. G02 still delivers only `relevance.py:39-47`, not `find:74-182`; `context_builder.py` and `selection.py` remain budget-omitted. G02's unresolved scope and disputed `selection.py` alternative remain separate from the measured result.
- **E01 protected:** The explicitly anchored `preemption.py:1-36` and cited method remained fully delivered. No cited test range was weakened. The candidate used the same candidate ordering, scores, cap, affinity, allocation code, 6,000-token budget, redaction, and pinned source; all six candidate packs stayed within budget.

Lower proposal cost did **not** imply lower total selected tokens or better evidence. This candidate damaged two previously complete areas, and the predeclared acceptance checks reject it. The remaining candidate-cap and affinity omissions are independent failure mechanisms. Do not activate or tune this rule against these development labels, and do not use the committed reserved labels as a rescue set; they are an operational, not genuinely blind, holdout.
