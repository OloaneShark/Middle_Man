# Codex M01 Variance Calibration V2

**Preregistered only. Zero model or calibration processes are authorized now.** The machine-readable design is [codex_variance_calibration_v2_plan.json](codex_variance_calibration_v2_plan.json). This is a distinct study, not a continuation or retry of [V1](CODEX_VARIANCE_CALIBRATION_PLAN.md), which remains stopped and incomplete after one runtime-successful, semantically failed baseline. Its other three calls never ran; none of its observations enters V2.

## Purpose and source

V2 describes natural same-task variation in Codex-reported input tokens, native exploration, cache use, and execution order under an explicitly selected research backend. It is not a locator-quality rule, performance threshold, winner-selection benchmark, or token-savings claim.

Use the original M01 task **verbatim** from `tests/fixtures/locator_shadow_corpus.json`, SHA-256 `380ce2cdd99f2d2ea66a2b9c4dfa417af8227b1af4402c51387d45fb9d13531d`. Review semantic correctness against the original M01 `semantic_rubric` in `docs/locator_quality_prospective_plan.json`; do not put evaluator facts into the model-visible task. Pin commit `db187e0f48f54222dd250502a2e40b7f1fb16401`, Git tree `c597226461db5975ffafd50a769404e03442fda6`, content fingerprint `1a91d487a2629d4c82cbae7072ac873e8fcb516597fe954d53f74b649c4241fa`, and selector fingerprint `3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`. Preserve the original tracked root `AGENTS.md` at blob `0c8baf10e4f781c6b9eaa03c38a24b40d4e1978c`; do not generate benchmark guidance.

## Execution lock

The reusable runner is `scripts/run_codex_pair_experiment.py`, backed by `middle_man/experiments/codex_pair.py`. Both arms use CLI `codex-cli 0.162.0-alpha.2`, `gpt-6-sol`, high effort, 360 seconds, explicit `windows.sandbox="unelevated"`, `-s read-only`, `--ignore-user-config`, `--strict-config`, `--no-daemon`, `--ephemeral`, `-a never`, `--json`, `features.apps=false`, and `features.plugins=false`. Register no MCP server. The baseline gets exact M01 task bytes and no locator. Middle_Man passes the same task through unchanged production AUTO, which may append its normal source-free locator. Both use the shared research execution, parser, and integrity checks. Production's Windows sandbox default is unchanged. **Unelevated success does not establish security equivalence to elevated mode.**

| Call | Arm | Replicate |
| ---: | --- | --- |
| 1 | BASELINE | A |
| 2 | MIDDLE_MAN | A |
| 3 | MIDDLE_MAN | B |
| 4 | BASELINE | B |

Each future call requires a fresh, clean, independently committed, source-identical pinned snapshot. Verify all four before call 1 and verify each after its arm. Never reuse or reorder snapshots. At most four future processes may be separately authorized; no retries. A runtime or infrastructure failure stops the remaining schedule. Record a semantic failure without replacing the observation; it does not independently authorize a new schedule. Analyze the complete calibration only when all four observations are valid.

Per-arm validity requires source, tree, content, selector and task pins, unchanged tracked guidance, locked CLI/model/effort/backend/isolation, zero exit, a parsed nonempty final answer, no malformed JSONL or failed turn, no unexpected external/MCP activity, unchanged HEAD/status/Git-visible content, semantic PASS under the frozen M01 rubric, and preservation of the completed sanitized observation.

## Measurements and interpretation

Capture Codex-reported input, cached input, output, and reasoning output tokens; elapsed time; native tool calls; explicit reads, unique files, rereads; total searches/listings; content, file-targeted, repository-wide, and file-listing searches; Git inspections; unclassified commands; malformed events; external/MCP activity; repository integrity; semantic result; backend; and output-rendering status. Capture normal locator metadata for Middle_Man. Keep local heuristic estimates separate from provider usage.

Let `B_A`, `B_B`, `M_A`, `M_B` be the four input-token observations. Report signed within-arm differences `B_B - B_A` and `M_B - M_A`, their absolute values, and `100 * absolute_difference / arm_two_run_mean`. Report each arm's two-run mean, Middle_Man-minus-baseline mean input delta and percentage relative to the baseline mean, and the four-observation input range. Separately compare cached-input variation, elapsed time, native calls, and search counts across replicates. For each observation, report `input_tokens - cached_input_tokens` as **DIAGNOSTIC ONLY - NOT BILLING OR QUOTA**. Two observations per arm do not support a significance claim.

The prior valid M01 A/B delta of `-8219` input tokens (`-2.3535%`) remains directional historical context, not a V2 replicate: it did not use the newly explicit unelevated backend. Do not pool it or the failed V1 baseline with V2. Do not invent a threshold, change the earlier rejected shadow policy, or retroactively reinterpret old results. A separately authorized run is required before any V2 observation can exist.
