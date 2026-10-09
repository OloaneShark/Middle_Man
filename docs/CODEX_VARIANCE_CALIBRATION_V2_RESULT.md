# Codex M01 Variance Calibration V2 Result

**Valid four-observation descriptive calibration, conditional on the reported human semantic reviews.** This report follows the unchanged [V2 preregistration](CODEX_VARIANCE_CALIBRATION_V2_PLAN.md); [machine-readable results](codex_variance_calibration_v2_result.json) and byte-identical, sanitized [receipts](codex_variance_calibration_v2_receipts/) are archived separately. The frozen manifest SHA-256 is `6606bdaf5e7fdd667c41e883e8c83569e49d3d5c2d66e12b7c223ba3608993d8`.

Four independent clean snapshots used source commit `db187e0f48f54222dd250502a2e40b7f1fb16401`, tree `c597226461db5975ffafd50a769404e03442fda6`, content fingerprint `1a91d487a2629d4c82cbae7072ac873e8fcb516597fe954d53f74b649c4241fa`, selector fingerprint `3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`, and the tracked `AGENTS.md` blob `0c8baf10e4f781c6b9eaa03c38a24b40d4e1978c`. All used the original M01 task SHA-256 `380ce2cdd99f2d2ea66a2b9c4dfa417af8227b1af4402c51387d45fb9d13531d`, CLI `codex-cli 0.162.0-alpha.2`, `gpt-6-sol`, high effort, read-only mode, and explicit `windows.sandbox="unelevated"`. This does not establish security equivalence to the elevated backend.

## Observations

| Call | Arm | Runtime | Reported semantic | Input | Cached input | Output | Reasoning output | Seconds | Native calls | Reads | Searches |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Baseline A | SUCCESS | PASS | 444,869 | 384,256 | 4,282 | 1,023 | 76.343 | 29 | 22 | 6 |
| 2 | Middle_Man A | SUCCESS | PASS | 538,290 | 488,064 | 6,287 | 2,010 | 101.681 | 33 | 23 | 7 |
| 3 | Middle_Man B | SUCCESS | PASS | 339,527 | 278,912 | 3,195 | 512 | 61.176 | 22 | 19 | 2 |
| 4 | Baseline B | SUCCESS | PASS | 412,053 | 359,296 | 4,400 | 779 | 59.687 | 30 | 21 | 4 |

All four receipts report zero process exit, nonempty rendered results, no malformed event lines, no external/MCP activity, and unchanged repository HEAD, porcelain status, and Git-visible content. Each retains only metadata and repository-relative paths, not raw source, complete prompts, raw JSONL, shell commands, search terms, or final answers. Their SHA-256 digests, in call order, are `b24e623825b24913669c71892ee36c1deb6bd4acfd7a864186cd430d7bc0020a`, `4dd3363d4b7f65fa7c51c5053fe1380248b7278538e88d36b99a01c4b8468a73`, `24aa2a76a401e37925d3888c15d26723da20cf97535de2de27fbc93a7782a316`, and `9d956850f47bd5af0a1659490082e1840657b0369195f9597c1b53e51f3eaa09`. The original receipts remain outside the repository.

**Semantic evidence limit:** PASS was reported after human review against the original M01 rubric during the run. The unmodified receipts have `semantic_review: null`; final answers and reviewer spans were not archived. The semantic judgments therefore cannot be independently reproduced from these receipts alone. Runtime and usage fields can be checked directly.

## Preregistered Analysis

Baseline input mean was **428,461**. Its B-minus-A difference was **-32,816** tokens, absolute **32,816**, or **7.6590%** of the baseline two-run mean. Middle_Man input mean was **438,908.5**. Its B-minus-A difference was **-198,763**, absolute **198,763**, or **45.2857%** of its two-run mean. The Middle_Man-minus-baseline mean difference was **+10,447.5 tokens (+2.4384%)**; the four-input range was **198,763**.

Within the same replicate, Middle_Man minus baseline was **+93,421** for A and **-72,526** for B. The opposite directions are a warning against declaring a winner from this small sample. Cached-input B-minus-A changes were **-24,960** for baseline and **-209,152** for Middle_Man. Elapsed changes were **-16.656 s** and **-40.505 s**; native-call changes **+1** and **-11**; search changes **-2** and **-5**, respectively.

Input minus cached input was **60,613; 50,226; 60,615; 52,757** in call order. **DIAGNOSTIC ONLY - NOT BILLING OR QUOTA.** These are derived from provider-reported usage, not Middle_Man heuristic token estimates.

## Exploration

The two Middle_Man calls used the same task and pinned source, `LOCATOR USED`, locator hash `dbcba1d8d1737aac82f481643149283344a871a96d374ccc46dd2443e4c684c1`, 14 selected paths, and 276 estimated model-visible Middle_Man tokens. Candidate, selected, and locator estimates were the same in both: 138,885; 5,999; and 227 tokens. Yet their Codex-reported input differed by 198,763 tokens.

| Middle_Man replicate | Unique files read | Locator paths read | Locator paths searched | Non-locator paths searched | Rereads | Native calls | Searches | Listings | Unclassified |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 21 | 7 | 8 | 8 | 2 | 33 | 7 | 1 | 1 |
| B | 19 | 8 | 6 | 3 | 0 | 22 | 2 | 1 | 0 |

A had more total native operations, searches, non-locator search targets, and rereads, consistent with a longer exploration. B actually read one more locator-selected path. These counts may help explain differing exploration, but the receipts do not prove what caused the input-token difference. Cached input also changed substantially; input-minus-cached moved in the opposite direction. No raw search terms or source content are needed for this comparison.

## Interpretation and Next Steps

V2 can describe variation under this one explicit runtime configuration, but two replicates per arm do not support statistical significance, a universal noise band, or a proof of Middle_Man overhead. The earlier valid M01 delta of **-8,219 input tokens (-2.3535%)** is historical context from a different backend, not a V2 replicate; the incomplete V1 baseline is excluded. Neither the rejected shadow locator rule nor any new policy is enabled. No savings threshold is defined.

A future study would be more informative with independent task families, repeated runs under one explicit runtime configuration, balanced order, predefined input-token and process budgets, and source-grounded semantic review retained in a privacy-safe form. Use provider-reported usage for comparisons and run deterministic offline diagnostics before spending more model calls. This is a recommendation, not a new preregistration or authorization.
