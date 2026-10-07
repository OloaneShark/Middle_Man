# Locator Quality Prospective Experiment: Batch 1 Outcome

This is the historical outcome of the immutable [v1 preregistration](locator_quality_prospective_plan.json) at commit `ee15a1856839b0de407b8fda3c2613e2a67a7562`. The machine-readable record is [locator_quality_batch1_result.json](locator_quality_batch1_result.json). Neither v1 plan was edited after observation.

Four read-only Codex processes ran in the locked order: M01 Middle_Man, M01 baseline, M02 baseline, M02 Middle_Man. All used independently clean snapshots of `db187e0f48f54222dd250502a2e40b7f1fb16401`, `gpt-6-sol`, high effort, CLI `codex-cli 0.162.0-alpha.2`, a 360-second timeout, and production isolation controls. There were no retries or Claude calls. Final snapshot HEAD, tree, Git status, and Git-visible content matched pre-run values.

| Task | Pair | Middle_Man input | Baseline input | Delta (Middle_Man - baseline) | Interpretation |
| --- | --- | ---: | ---: | ---: | --- |
| M01 | VALID; both runtime and semantic PASS | 341,004 | 349,223 | -8,219 (-2.35%) | Contradicts preregistered BYPASS |
| M02 | INVALID_PAIR | Unknown | 345,861 | Unknown | No directional inference |

M01's input-minus-cached values were 64,652 (Middle_Man) and 65,447 (baseline), **diagnostic only, not billing or quota**. The observed M01 effect may reflect cache warmth, execution order, or stochastic exploration as well as the locator; a single pair does not establish universal savings.

M02 baseline completed, but its answer failed the frozen semantic rubric: task/error-text redaction, explicit source confinement, and delivery warning/token-estimate details were not materially covered. The M02 Middle_Man Codex child returned to the temporary helper; the helper then raised `UnicodeEncodeError` while printing the completed answer, losing the in-memory observation. Its runtime classification, usage, telemetry, answer, and semantic outcome are unknown. It was not retried or reconstructed. Even a preserved Middle_Man result could not make M02 valid given the baseline semantic failure.

Per the v1 interpretation, the valid M01 contradiction makes `coherence_and_exact_symbol_ambiguity` **rejected for production enablement**. It remains available only as a historical shadow diagnostic. Production AUTO is unchanged. Batch 2 (T03/G04) was not authorized or run: the candidate already failed its production-readiness criterion, and the harness exposed a result-preservation defect.
