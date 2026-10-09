# Navigation-only shadow rule (frozen before development evaluation)

Status: research only. This candidate is not part of production AUTO or Codex prompt
construction. It makes no inference calls.

## Inputs and selection

Use the pinned source commit `0680a1cb8812d35b17ebd628de7ffba95798da7f`
(tree `6276b4a959bc93df8bb82cdde0bfc371d2c99770`) and the unchanged
production `RelevanceEngine.find` scores and order with `top_k=50`. The query is
the same redacted/effective query used by the Context Pack. Do not rerank, add
weights, use source-excerpt costs, run source allocation, or apply task-cluster
affinity. No task ID, reference label, or evaluator citation enters selection.

Walk the 50 candidates in rank order. Use at most one hint per distinct path.
If a candidate has matched indexed symbols, choose the first exact-symbol signal
in production signal order when present; otherwise choose its first lexically
ordered matched symbol. Use that symbol's verified indexed start/end lines and
qualified name. If no matched indexed symbol is available, use `1-line_count`
as a file-level location without a symbol label. Validate repository-relative
path confinement, physical file existence, line bounds, identifier format, and
production secret redaction before formatting. Unsafe paths fail closed; unsafe
symbol labels fall back to a source-free file-level location. No source text is
read by the candidate after the existing relevance/indexing stage, and no source
text is emitted.

Format each hint as one production-compatible `- path:start-end (symbol)` line,
or `- path:1-end` for file fallback. Reuse production's appendix wrapper and
heuristic token estimator. For each development task, the baseline audit's
`model_visible_appendix_estimated_tokens` is the fixed maximum. Greedily accept
each candidate only if the whole appended text remains at or below that maximum;
otherwise skip it and continue to later ranked candidates. Record each valid
path skipped for budget. This is a prompt-size constraint, not source-token
compression. Candidate order and one-hint-per-path behavior are deterministic.

## Decision fixed in advance

Evaluate only N01, M02, C02, T01, G02, E01 using the existing proposed
source-grounded navigation evaluator. Baseline navigable areas are respectively
3/3, 1/4, 1/3, 0/3, 0/2, 1/1, totaling **6/16**. An offline candidate passes
only if **all** of these hold:

1. More than six complete navigable development areas.
2. No previously navigable area is lost.
3. N01 retains 3/3; E01 retains 1/1 and its explicit anchor.
4. Test-focused reference path targeting and navigation are not weakened.
5. No task's candidate appendix estimate exceeds its own baseline estimate.
6. No safety, redaction, or pinned-repository integrity regression occurs.

Failure of any condition rejects this frozen candidate. A passing offline result
would warrant further independent investigation only, never automatic production
activation. Reserved references remain sealed. N01 ownership and G02 selection
alternative remain proposed errata, not changed labels. These structural proxies
do not measure Codex behavior, correctness, or provider token savings.
