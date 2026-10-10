# Prospective A-plus source-free locator study

Status: **design only; not implemented, evaluated, or authorized for inference**. The
machine-readable design is [`a_plus_locator_prospective_design.json`](a_plus_locator_prospective_design.json).
Neither document changes production AUTO, the selector, or prompt construction.

## Evidence and question

The [production audit](SOURCE_FREE_LOCATOR_NAVIGATION_AUDIT.md) found 6/16 proposed
navigable areas on six development tasks. Source allocation under the internal
Context Pack budget excluded useful paths; one path fell beyond the top-50
candidate cap, and task-cluster filtering excluded relevant tests and lab code.
The [B navigation-only rule](NAVIGATION_ONLY_SHADOW_RULE.md) removed allocation
and cluster constraints, but [B was rejected](NAVIGATION_ONLY_SHADOW_RESULT.md):
8/16 aggregate areas hid a lost production area, and several ranges targeted
the wrong class, function, or method. The [C precision rule](NAVIGATION_HINT_PRECISION_RULE.md)
improved some ranges but [C was rejected](NAVIGATION_HINT_PRECISION_RESULT.md):
9/16 aggregate areas still hid a destructive replacement of an entry hint and
the prior loss remained. Neither rejected candidate is accepted here.

The [preservation feasibility study](NAVIGATION_HINT_PRESERVATION_FEASIBILITY.md)
showed that keeping all A, B, and C hints exceeded every original task-specific
appendix ceiling. Qualified symbols, ranges, and new paths consume real prompt
space, even with same-path grouping. The experiment below asks whether a *small,
high-confidence* supplement can improve navigation while retaining A, not whether
the complete A+B+C union can fit. Prior references were proposed rather than
independently validated. Calibration V2 showed large and direction-changing
same-arm input variation; offline navigation is not evidence of provider-token
savings or semantic correctness.

## Frozen candidate concept for future implementation

For a given task and pinned source, construct production A unchanged. Preserve
its entire hint block as an unchanged prefix, including every A path, range,
symbol, and ordering byte-for-byte. Supplemental discovery uses the same
redacted effective query and existing relevance ordering, without
Context Pack source allocation or task-cluster exclusion. Inspect at most the
top 100 ranked files, plus exact repository-relative paths explicitly named in
the task even if outside that cap. This cap is a prospective bound, not a
validated optimum. No reference labels, task IDs, expected answers, or evaluator
outputs enter selection.

A file needs direct task evidence: an explicit path or qualified symbol, or at
least two distinct normalized non-stop task terms matching a verified indexed
function/method name. Graph-only relevance is insufficient. Consider only
indexed Python functions/methods with valid bounded spans and safe qualified
labels. Prefer an explicit qualified-symbol match, then an explicit path with
a unique method matching at least one normalized task term, then a unique
two-term method-name match. Within
each tier, more distinct matching terms wins; an equal-best tie, absent method
evidence, or invalid span produces no supplemental hint for that file. Never
use a broad class/whole-file fallback to manufacture precision. Order eligible
file winners by evidence tier, distinct-term count, existing relevance rank,
then repository-relative path for deterministic cross-file ties.

Keep at most three additions per task, at most one per file, and at most two
previously absent files. Reject an exact `(path, start, end, symbol)` duplicate
or an addition whose range and symbol convey no new location beyond an A hint.
If a method lies inside an A broad range, it may still be added when its safe
qualified label gives a new exact method target. Additions are source-free
`path:start-end (symbol)` hint lines after the A hint block, in
production-compatible syntax; A hint text is never replaced, trimmed, or
reordered. Record candidate and skip reasons.

Use one fixed **512 estimated-token ceiling for the entire appended locator**,
including heading, instructions, paths, ranges, symbols, and separators, with
the production appendix formatter and heuristic estimator. This is a round,
bounded research allowance for sparse additions, not a cost optimum inferred
from the six old tasks. It is separate from the 6,000-token *internal source*
budget and from Codex-reported input tokens. Check each addition against the
whole appendix and skip over-budget additions in priority order. If A alone
exceeds 512, emit A unchanged, record `BASELINE_OVER_BUDGET`, add nothing, and
count the task as a feasibility failure in the confirmatory study; never remove
A, raise the limit for that task, or silently exclude it. No task-specific
historical appendix ceiling is reused.

Future implementation must verify the clean source commit/tree and index
identity, path confinement including symlinks, physical existence, exact line
bounds, safe identifiers, and existing secret redaction before formatting.
Unsafe candidates abstain. No source text appears in the appendix or result
metadata. Snapshot Git status and content must remain unchanged.

## Independent offline evaluation

Create **16 fresh tasks**, four each in narrow explicit-anchor, multi-file
architecture, test-focused, and broad/ambiguous archetypes. Do not reuse the
six development tasks for independent confirmation. Previously committed
reserved labels remain an operational holdout, not a blind benchmark; do not
open or use them to construct the rule. Pin a *future clean source commit/tree*
before authoring references. Freeze task wording and hashes, source/index and
selector fingerprints, source-grounded implementation-area alternatives,
rubrics, metrics, this rule, and acceptance gates before candidate outcomes.
Two human reviewers independently establish path, range, and symbol references
from source **without seeing A-plus output**; adjudicate disagreements in a
versioned record. AI-generated references, if any, are proposals only until
independently human-validated. Without that review, label results exploratory
and make no confirmatory acceptance claim.

Score A and A-plus on each task: referenced paths targeted; correct range
intersection and exact function/method symbol matches; complete navigable
areas (every reference in at least one approved alternative); baseline areas
retained; supplement relevance, including *materially misleading* hints by
blinded source review; and full-appendix bytes/heuristic tokens. An unreferenced
path is `UNKNOWN`, not automatically irrelevant. Require all 16 valid tasks,
zero lost A areas or explicit anchors, zero materially misleading additions,
and every full appendix at or below 512. Also require at least two *additional*
complete areas across at least two archetypes. Any failure rejects the frozen
candidate; invalid source/review evidence makes the study inconclusive. This
conservative gate cannot establish actual agent benefit. A passing offline
result only makes a separately authorized Codex validation eligible.

## Later Codex validation, not authorized here

If offline gates pass, preselect eight human-validated tasks (two per archetype)
before model results. Compare production A with A-plus in fresh, source-identical,
clean snapshots under one later-frozen CLI/model, read-only sandbox, task prompt,
output schema, and timeout. Use four calls per task, alternating `ABBA` and
`BAAB` across tasks: **32 maximum inference processes, no retries**. Set a
future aggregate cap of 24,000,000 provider-reported input tokens and 512,000
provider-reported output tokens, plus 360 seconds per process. Reserve an
allowance of 750,000 input and 16,000 output tokens before each call. These are
stop limits and accounting allowances, not guaranteed per-call usage bounds.
Stop before another call when the remaining budget cannot cover its allowance.
Stop immediately on missing usage, infrastructure invalidity, safety/integrity failure, or a
cap breach. Do not replace failed observations or change task order.

Record provider input, cached input separately, output, reasoning output,
elapsed time, native calls, explicit reads/unique files/rereads, searches and
listings, and before/after Git/source integrity. Preserve bounded, sanitized,
reviewable semantic answer claims and source-grounded reviewer spans/rationale,
with blinded independent review and adjudication. If evidence cannot be safely
retained, do not claim semantic PASS. Report paired per-task deltas and their
distribution, including same-arm spread and cache behavior. Calibration V2's
two-per-arm observations are not a universal noise band or significance
threshold. Navigation scores and heuristic estimates must never be presented
as Codex usage savings.

## Open questions

The 512 ceiling and top-100 pool may be too tight or too broad; neither is
retuned on the old six tasks. Exact method-name evidence may abstain on valid
work, while lexical overlap may still mislead. Independent reference review
and safe semantic-evidence retention have real cost. Any change to the frozen
rule after observing new outcomes requires a separately named study.
