# Exploratory A-versus-A-plus offline navigation result

Status: **EXPLORATORY_NO_CLEAR_GAIN**. This is one local, source-pinned comparison
using `AI_PROPOSED_SOURCE_GROUNDED_NOT_HUMAN_VALIDATED` references. It is not a
human-validated or blinded assessment, a semantic correctness evaluation, or a
provider-token benchmark. Neither locator was changed or called again to tune
the result. The structured, source-free per-task receipt is
`docs/a_plus_exploratory_offline_result.json`.

## Identity and method

- Starting orchestration HEAD: `b97e210c793f413bd0a7aca983bb1a74605a0eb0`.
- Pinned source commit/tree: `8a6dca9e3cfadd144f14e860d182ec44ac0faedc` /
  `467f280dfc781897099d726085974223cf9d6754`.
- Pinned filesystem source fingerprint:
  `bf192a20ad175d0714ddaeee4927c034f452fed5fb93c396acb0a94d515e3c9c`.
- Frozen corpus task-array SHA-256:
  `4580134b1ed60c4b75c3c951cda89e65e863ec32dbc70f39e192efaac69770af`.
- Frozen proposed-reference task-array SHA-256:
  `d9511d4d626e900faf570953fe6a80443217f086f00c9d62bb47ec2cff490b1c`.
- The evaluator checked the design SHA-256, frozen A-plus Git blob, selector
  fingerprint, source tree, and clean source fingerprint before generation.
  One disposable pinned snapshot was used. Its HEAD, tree, status, and source
  fingerprint were unchanged afterward.
- Production A and frozen A-plus were generated once per task, with the same
  task, snapshot, and A baseline. The scoring rules and synthetic tests were
  established before any candidate locator output was generated.

A cited span counts as *precisely navigable* only when one same-path hint has
an intersecting literal line range and the exact qualified symbol. All spans
in one alternative must pass; any complete alternative completes an area.
Whole-file/class overlaps are diagnostic only. This measures structural
navigation, not whether an answer would be correct. Partial-reference tasks
have span diagnostics but no area or complete-task score.

## Per-task results

`A/+` is the estimated full appendix token count; `P`, `R`, `S`, and `X`
are A/A-plus counts of cited spans with a targeted path, intersecting range,
exact symbol somewhere on that path, and precise navigation respectively.
These are local estimates, not provider usage. `Areas` is completed proposed
areas under the predeclared rule; `partial` means no completeness score.
Each locator's exact SHA-256, skip reasons, and supplement metadata are in the
JSON receipt.

| Task | Reference | A/+ | Delta | Hints | New files | P | R | S | X | Areas A/+ |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| AP-N01 | complete | 187/249 | 62 | 3 | 2 | 3/3 | 3/3 | 1/1 | 1/1 | 1/1 of 3 |
| AP-N02 | complete | 206/248 | 42 | 2 | 2 | 4/4 | 2/2 | 0/0 | 0/0 | 0/0 of 2 |
| AP-N03 | complete | 266/307 | 41 | 2 | 2 | 2/2 | 2/2 | 0/0 | 0/0 | 0/0 of 2 |
| AP-N04 | complete | 113/182 | 69 | 3 | 1 | 4/4 | 2/3 | 1/2 | 1/2 | 0/0 of 2 |
| AP-M01 | complete | 103/155 | 52 | 2 | 2 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 of 3 |
| AP-M02 | complete | 296/346 | 50 | 2 | 2 | 2/2 | 1/1 | 0/0 | 0/0 | 0/0 of 3 |
| AP-M03 | complete | 458/497 | 39 | 2 | 0 | 5/5 | 2/3 | 1/2 | 1/2 | 0/0 of 3 |
| AP-M04 | complete | 307/358 | 51 | 3 | 2 | 0/1 | 0/1 | 0/1 | 0/1 | 0/0 of 4 |
| AP-T01 | partial | 333/381 | 48 | 2 | 2 | 0/0 | 0/0 | 0/0 | 0/0 | partial |
| AP-T02 | partial | 334/381 | 47 | 2 | 2 | 0/2 | 0/2 | 0/2 | 0/2 | partial |
| AP-T03 | complete | 452/494 | 42 | 2 | 0 | 7/7 | 3/3 | 1/2 | 1/2 | 0/0 of 3 |
| AP-T04 | complete | 487/508 | 21 | 1 | 0 | 3/3 | 2/2 | 0/0 | 0/0 | 0/0 of 3 |
| AP-G01 | partial | 164/203 | 39 | 2 | 2 | 6/6 | 1/1 | 0/0 | 0/0 | partial |
| AP-G02 | partial | 62/103 | 41 | 2 | 2 | 0/0 | 0/0 | 0/0 | 0/0 | partial |
| AP-G03 | partial | 444/491 | 47 | 2 | 2 | 4/4 | 1/1 | 0/0 | 0/0 | partial |
| AP-G04 | partial | 216/278 | 62 | 3 | 2 | 0/0 | 0/0 | 0/0 | 0/0 | partial |

Across the ten complete-reference tasks there are 28 proposed areas. A and
A-plus each complete only AP-N01's CSV failure-row area (1/28); neither
completes any full task. On 52 distinct cited spans, targeted paths rise
30 to 31, intersecting ranges 17 to 20, exact symbols 4 to 8, and precise
navigation 4 to 8. The four extra precise spans occur in AP-N04, AP-M03,
AP-M04, and AP-T03, but none completes an additional area. There are zero
lost areas. Whole-file and class-range hint counts remain 18 and 27.

The six partial tasks remain in the study. Their 35 cited spans are
*partial diagnostics only*: targeted paths 10 to 12, range intersections
2 to 4, exact symbols 0 to 2, and precise spans 0 to 2. Both new precise
spans are in AP-T02. Their unresolved interpretations remain in the JSON;
these figures are excluded from all area and task completeness claims.
They do not support a claim about broad/ambiguous task performance.

## Additions, safety, and limitations

All 16 appendices are within 512 locally estimated tokens. Totals are 4,428
for A and 5,181 for A-plus, an additional 753. There are 35 supplements and
25 new-file additions across tasks. Per-task maxima are three hints and two
new files. No A baseline was already over budget; appendix-budget skips still
occurred in AP-M03, AP-T03, and AP-T04. Other candidate abstentions and counts
are preserved per task in the JSON. A text, order, paths, and explicit path
anchors were preserved; no unsafe path, stale span, unredacted locator text,
source excerpt, or source mutation passed evaluation.

Every supplement's path, exact function/method symbol, and line interval was
checked against pinned source. Six directly match a cited span and two are on
a cited path with a different symbol. The remaining 27 are **UNKNOWN**, not
automatically irrelevant: several are supporting tests or integration paths.
The post-result AI source review identified provisional *potentially
misleading* additions, including:

- AP-N02: a scheduler budget test for a question about `OutputCompactor`.
- AP-M02: simulator prefix-cache/ownership tests for an MCP source-delivery
  follow-up question.
- AP-M04: a Claude runtime stream fixture for production Codex telemetry.
- AP-G03: a Claude benchmark snapshot test for MCP context continuation.

These are source-checked concerns, not independent blinded judgments. The
condition of **no materially misleading additions** is therefore unverified,
not a pass. An unreferenced hint may still be relevant; the receipt retains
`UNREFERENCED_UNKNOWN` rather than assigning it a false-negative label.

## Frozen acceptance conditions

| Condition | Exploratory diagnostic |
| --- | --- |
| No lost production areas | Met: zero lost complete areas. |
| No lost explicit anchors | Met: zero lost supplied-path anchors. |
| No materially misleading additions | Unverified; provisional off-task concerns above. |
| At least two additional complete areas across two archetypes | Not met: zero additional complete areas. |
| Full appendix at most 512 when A fits | Met: 16/16; no over-budget A. |
| Source and repository integrity | Met: pinned clean snapshot before and after. |

The **official confirmatory gate is NOT EVALUABLE**: two independent human
reviews were not completed; six references are partial; and the broad/ambiguous
archetype has no complete references. Human reviews remain pending. The local
span gains do not overcome zero area gains, 753 additional estimated tokens,
and unresolved off-task additions. A-plus is neither accepted nor promoted;
production remains unchanged. Codex benchmark inference calls: 0. Claude
benchmark calls: 0. Provider usage: not observed.

## Local verification

- Full pytest: **599 passed, 3 skipped**.
- `git diff --check`: passed; staged diff also checked before commit.
- Frozen design SHA-256, corpus/reference task-array hashes, A-plus Git blob,
  selector fingerprint, pinned commit/tree/source fingerprint: matched.
- Calibration files and receipts were unchanged from starting HEAD; all four
  frozen Phase 22 result-file SHA-256 values matched their recorded values.
- Production A, A-plus, selector, and other production implementation files
  were unchanged. The study made no external model calls.
