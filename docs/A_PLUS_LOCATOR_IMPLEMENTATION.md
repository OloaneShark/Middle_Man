# A-plus locator research implementation

Status: research-only local implementation. The [frozen plan](A_PLUS_LOCATOR_PROSPECTIVE_PLAN.md)
and [manifest](a_plus_locator_prospective_design.json) are unchanged. This module
is not imported by production AUTO, does not create new evaluation references,
and has not been run on the future 16-task corpus or any historical labels.

## Design-to-code mapping

`middle_man/experiments/a_plus_locator.py` takes the production
`build_offline_locator` result as A. It verifies A's hash and selector
fingerprint, keeps the complete A hint text as the prefix, and appends only
separate production-compatible lines. The dry run builds A through the existing
production API with cache writes disabled. It never invokes a model or MCP.

Supplemental discovery calls the unchanged `RelevanceEngine.find` at top 100,
then includes indexed exact repository paths named in the task outside that
cap. It bypasses Context Pack source allocation and task-cluster exclusion
only for supplements. File and method evidence uses the redacted task, indexed
Python methods/functions, production term normalization, and the frozen three
priority tiers. Equal-best evidence abstains. The rule adds no more than three
hints, one per file, and two new files; duplicate/contained identical-symbol
hints abstain. The complete production-formatted appendix is estimated after
each proposed addition against the fixed 512 heuristic-token ceiling. An A
already above that ceiling is preserved and marked `BASELINE_OVER_BUDGET`.

Path confinement, symlink checks, file existence, SHA-verified source reads,
fresh Python parse parity, line spans, ownership, safe qualified labels, and
secret redaction gate supplemental hints. The dry run requires a clean pinned
Git HEAD, uses a no-write index, records its fingerprint, and compares HEAD,
status, and Git-visible content before and after. Its JSON receipt contains
hashes, estimates, counts, skip reasons, and integrity status, but no source
excerpt, full task, complete prompt, or complete locator. Example local entry
point: `python -m middle_man.experiments.a_plus_locator --repo PATH
--expected-head SHA --task "TASK"` on a clean synthetic Git fixture.

## Synthetic coverage and limits

`tests/test_a_plus_locator.py` covers A-byte preservation, same-file additions,
evidence priority, two-term matching, ambiguity, graph-only abstention, top-100
and exact-path exception, redundancy, both hint/file caps, full-appendix budget,
over-budget A, symlink and out-of-root paths, unsafe labels/paths, stale and
corrupt index data, deterministic metadata-only output, and a clean Git dry
run. These tests assert safety and rule behavior, not a favorable navigation
score.

The frozen design leaves several implementation details open. This code treats
"normalized terms" as exact matches from production `terms`, not lexical-family
near matches; an explicit path still needs at least one method-name term.
Evidence-bearing invalid indexed symbols abstain for the whole file. A baseline
with the production "No selected locations" sentinel receives no additions
because combining that sentence with hint lines would contradict the wrapper.
A stale source encountered during relevance ranking aborts the dry run rather
than returning partial hints. None of these choices modifies the frozen rule
or claims candidate quality. The fixed 512 ceiling and top-100 discovery pool
remain unvalidated; future independent source-grounded evaluation is still
required before any separately authorized Codex experiment.
