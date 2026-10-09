# Navigation hint precision shadow rule

Frozen before development evaluation. Research only; never installed in AUTO or
the production locator. No model calls.

## Fixed inputs

Use source commit `0680a1cb8812d35b17ebd628de7ffba95798da7f`, tree
`6276b4a959bc93df8bb82cdde0bfc371d2c99770`, the original frozen task
corpus and proposed reference dataset, the production navigation audit, and
the rejected navigation-only shadow result. Evaluate only N01, M02, C02,
T01, G02, E01. Their prior B locator paths and ordering are immutable.

## One within-file rule

For each B-selected path, examine only that path's indexed Python functions
and methods with valid, safe qualified identifiers and in-file line spans.
The original task is the sole lexical input. A function/method whose qualified
name is explicitly written in the task or `ContextQuery.symbols` is an explicit
code anchor and outranks lexical matches. Otherwise use production `terms`
and `lexical_family` to match task words to **function/method name** words.
Score each symbol by the sum of the lengths of distinct matching task words.
The method-name score must be positive. Do not score enclosing class names,
file names, source bodies, reference citations, or evaluator outcomes.

Choose a replacement only if exactly one valid function/method has the
highest positive evidence score (explicit-anchor tier first). Equal top
scores, no evidence, unsafe labels, or invalid indexed spans retain the
original B hint. Never select a class just because its span covers more
lines. A valid replacement uses the indexed start/end lines and qualified
symbol label. Preserve the original production-compatible line format.

Walk B's selected paths in their existing order. Begin with every original
B line. For each proposed substitution, estimate the **entire** appendix
using production `append_offline_locator` and `HeuristicTokenEstimator`.
Apply it only if the estimate stays within that task's original production
appendix estimate; otherwise retain that path's B hint. Never add or remove
a path, re-rank candidates, alter the top-50 pool, change the path budget,
or change production source allocation. The rule is deterministic and
source-free at output.

## Acceptance fixed in advance

Accept for further research only if all conditions hold:

1. No production-baseline navigable core area is lost.
2. No B-shadow navigable core area is lost.
3. At least one additional navigable implementation area **or** one new,
   independently task-supported function/method symbol match is gained.
4. Existing correct explicit code anchors are preserved.
5. Every task's full appendix estimate stays within its production baseline.
6. C's selected path sequence exactly equals B's.
7. Redaction, path confinement, and pinned repository integrity hold.

Failure of any condition rejects this one candidate. Even passing would
permit further independent evaluation only, never production activation.
The proposed N01 ownership and G02 selection-alternative errata remain
unchanged. Structural navigation scores are not model correctness or token
savings. No post-result tuning or reserved-label evaluation is permitted.
