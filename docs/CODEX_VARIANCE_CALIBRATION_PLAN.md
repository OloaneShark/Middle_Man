# Codex M01 Run-to-Run Variance Calibration v1

**Preregistered only. No model process is authorized or run by this plan.** The machine-readable design is [codex_variance_calibration_plan.json](codex_variance_calibration_plan.json). A future run requires separate explicit authorization, at most four fresh processes, and no retries.

The valid [Batch 1 M01 result](LOCATOR_QUALITY_BATCH1_RESULT.md) differed by -2.35% in Codex-reported input tokens. That observation is excluded from this new sample. The calibration asks whether a difference of that magnitude looks smaller than, comparable to, or larger than natural same-task run-to-run variation. It does not choose a new locator policy, threshold, or A/B winner.

Use the exact committed M01 task from `tests/fixtures/locator_shadow_corpus.json` (SHA-256 `380ce2cdd99f2d2ea66a2b9c4dfa417af8227b1af4402c51387d45fb9d13531d`) and the unchanged v1 M01 semantic rubric. Pin source commit `db187e0f48f54222dd250502a2e40b7f1fb16401`, tree `c597226461db5975ffafd50a769404e03442fda6`, and content fingerprint `1a91d487a2629d4c82cbae7072ac873e8fcb516597fe954d53f74b649c4241fa`. Require CLI `codex-cli 0.162.0-alpha.2`, `gpt-6-sol`, high effort, a 360-second timeout, read-only sandbox, and identical production isolation controls on both arms. Baseline receives only the exact task; Middle_Man uses unchanged production AUTO. No MCP registration.

| Call | Arm | Replicate |
| ---: | --- | --- |
| 1 | Baseline | A |
| 2 | Middle_Man | A |
| 3 | Middle_Man | B |
| 4 | Baseline | B |

Prepare four independent, clean, committed pinned snapshots outside the primary repository. Verify all four before any inference and verify each after its arm. A runtime, isolation, result-preservation, or repository-integrity failure stops the remaining schedule; a runtime-valid but semantically incomplete answer is still recorded and does not change the order. No retry. A meaningful four-run comparison requires all four arms valid, including semantic PASS under the frozen M01 rubric.

Measure each arm's Codex-reported input, cached input, output, reasoning output, elapsed time, native exploration counts, external/MCP activity, and repository integrity. Compare signed and absolute within-arm A-to-B input differences, each arm's two-run mean, the Middle_Man-minus-baseline mean input delta, and the range of all four inputs. Report cached-input, elapsed, native-call, and search-count variation separately. Input-minus-cached is diagnostic only, not billing or quota.

Two observations per arm cannot establish statistical significance. Do not infer universal savings or retroactively weaken Batch 1's policy rejection. Any later practical equivalence band or new quality rule needs its own prospective plan, written after calibration results are reviewed.

The reusable local utility is `scripts/run_codex_pair_experiment.py`. It runs one explicitly confirmed arm at a time, checks the source pin and locked CLI, and requires `--call-number` plus preceding successful receipts for this ABBA plan. The operator must prepare and verify all four independent snapshots before call 1; the utility does not create them or grant model-call authorization. Each arm writes a new sanitized `call-N.json` receipt **outside** its source snapshot before rendering its final answer. Receipts exclude raw JSONL, task text, source excerpts, full commands, search terms, and answer text. Console-render errors are reported separately after the receipt survives. Do not invoke this utility for calibration without a new authorization.
