# Prospective locator-quality experiment: preregistration

**Status: design only. No Codex inference, Claude call, or A/B is authorized by this document.** [Machine-readable manifest](locator_quality_prospective_plan.json) is the immutable v1 record; exact task text comes only from the [committed shadow corpus](../tests/fixtures/locator_shadow_corpus.json). The source-grounded rubrics below are evaluator-only and must not enter either model prompt.

## Locked source and execution

- Pinned experiment source commit: `db187e0f48f54222dd250502a2e40b7f1fb16401`; Git tree: `c597226461db5975ffafd50a769404e03442fda6`; content fingerprint: `1a91d487a2629d4c82cbae7072ac873e8fcb516597fe954d53f74b649c4241fa`; selector fingerprint: `3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`. A later HEAD is a different experiment. Independently materialize clean, source-identical snapshots from this commit with LF bytes; verify HEAD/tree/content before **each** future call and require unchanged status/content afterward.
- Expected locally discovered Codex CLI version: `codex-cli 0.162.0-alpha.2`. Both arms must use the same version, `gpt-6-sol`, `high` effort, and 360s timeout. Abort rather than silently substitute a changed CLI or source.
- Baseline prompt: exact original UTF-8 task from the fixture. Middle_Man prompt: those same original bytes through the **current production AUTO** path; only its normal source-free locator may be appended. The task hash is the same in both arms. No evaluator rubric or hidden expected answer is appended.
- Both arms use `middle_man.gateway.codex_runner.runner.build_invocation` and its production isolation verifier: read-only sandbox, `features.apps=false`, `features.plugins=false`, `--ignore-user-config`, `--strict-config`, `--no-daemon`, `--ephemeral`, `-a never`, JSONL events, and no MCP registration. The future baseline must pass its unchanged prompt directly to the builder; the Middle_Man arm uses production preview/AUTO and the same builder. Do not replace this with the Phase 22 benchmark command builder.
- Current production AUTO is unchanged. It chooses `LOCATOR USED` for all four pinned tasks because each is read-only, has selected paths, and exceeds 10,000 heuristic candidate-source tokens. The shadow quality rule is **not** used for routing.

## Tasks, shadow decisions, and order

Order is not discretionary: an even final SHA-256 hex digit means baseline first; an odd one means Middle_Man first. This balances two pairs in each order.

| Task | Archetype | Locked task SHA-256 | Shadow decision and reasons | Arm order |
| --- | --- | --- | --- | --- |
| M01 | MULTI_COMPONENT_ARCHITECTURE | `380ce2cdd99f2d2ea66a2b9c4dfa417af8227b1af4402c51387d45fb9d13531d` | BYPASS (DISCONNECTED_SELECTION, AMBIGUOUS_EXACT_SYMBOL) | MIDDLE_MAN -> BASELINE |
| M02 | MULTI_COMPONENT_ARCHITECTURE | `99e572ef26121c9f2260a6d16994cb68bef999c41be79981405056b22cf109a8` | PASS | BASELINE -> MIDDLE_MAN |
| T03 | TEST_FOCUSED | `249495e619f0a94db0c9fa1283072e6dacc97ae616822a491ea21f88b7c39cc2` | UNCERTAIN (DISCONNECTED_SELECTION) | BASELINE -> MIDDLE_MAN |
| G04 | GENERIC_BROAD | `89b8827390c274d2c7bfade1248a5de0b4f5050aa1a4976725628bcb685ec673` | UNCERTAIN (AMBIGUOUS_EXACT_SYMBOL) | MIDDLE_MAN -> BASELINE |

M01 and M02 are both multi-component architecture questions, giving Batch 1 a same-archetype BYPASS/PASS comparison. T03 and G04 independently exercise the disconnected-only and ambiguous-only UNCERTAIN branches. Tasks, wording, hashes, rule, order, rubrics, and interpretation must not be edited after outcomes; any changed design needs a new version.

## Pre-run locator receipts

These are local heuristic estimates, **not Codex provider usage**. All locator hashes and selected paths below were recomputed from the pinned prospective source and cross-checked against production preview. Complete quality feature vectors and AUTO reasons are in the manifest.

| Task | Candidate source | Selected source | Paths | Locator tokens | Model-visible Middle_Man tokens | Largest cluster share | Ambiguous exact-symbol pressure | Locator SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| M01 | 138885 | 5999 | 14 | 227 | 276 | 0.5714 | 0.2857 | `dbcba1d8d1737aac82f481643149283344a871a96d374ccc46dd2443e4c684c1` |
| M02 | 133240 | 5973 | 17 | 348 | 397 | 1 | 0 | `452929883a8a0614fa22198d8d968b129067513862438b1bf553a6b2bc2cdd9f` |
| T03 | 119645 | 5940 | 10 | 259 | 308 | 0.4 | 0 | `9c6ec0d36ef656e973ba3f435dbe3ddb467e01794613677a8d80a42d40b2d6ef` |
| G04 | 124729 | 3484 | 7 | 87 | 136 | 1 | 0.2857 | `57bcd765a640b25bc53ee239ac61fc1ac3837f1df4810405d6692dd0e25975f1` |

Selected paths:

- **M01:** `tests/test_codex_live_runner.py`, `tests/test_codex_runner.py`, `tests/test_phase_23_claude.py`, `middle_man/mcp/gateway.py`, `tests/test_phase_23_2_runtime.py`, `middle_man/gateway/git_diff.py`, `middle_man/gateway/source.py`, `middle_man/gateway/codex_runner/execution.py`, `middle_man/gateway/codex_benchmark/infrastructure.py`, `middle_man/gateway/context_models.py`, `middle_man/gateway/codex_runner/infrastructure.py`, `middle_man/cli/main.py`, `middle_man/gateway/codex_runner/audit.py`, `middle_man/gateway/selection.py`.
- **M02:** `middle_man/mcp/gateway.py`, `tests/test_phase_22_v4.py`, `middle_man/gateway/context_models.py`, `middle_man/mcp/server.py`, `middle_man/gateway/codex_benchmark/runner.py`, `middle_man/gateway/codex_benchmark/preemption_v3.py`, `middle_man/mcp/benchmark_receipts.py`, `tests/test_gateway_context_packs.py`, `middle_man/gateway/selection.py`, `middle_man/gateway/codex_benchmark/infrastructure.py`, `middle_man/cli/mcp.py`, `middle_man/mcp/delivery.py`, `middle_man/gateway/locator_diagnostics.py`, `middle_man/gateway/source.py`, `middle_man/cli/main.py`, `middle_man/gateway/codex_benchmark/offline_auto.py`, `middle_man/gateway/handoff.py`.
- **T03:** `middle_man/lab/config.py`, `middle_man/lab/work.py`, `middle_man/gateway/source.py`, `middle_man/gateway/git_diff.py`, `tests/test_codex_runner.py`, `middle_man/cli/codex_run.py`, `middle_man/gateway/codex_runner/infrastructure.py`, `middle_man/gateway/codex_runner/isolation.py`, `tests/test_phase_4_engine_runner.py`, `middle_man/mcp/server.py`.
- **G04:** `scripts/measure_large_edit_v1.py`, `scripts/measure_offline_auto.py`, `tests/test_phase_22_11.py`, `middle_man/gateway/codex_benchmark/large_edit_v1.py`, `middle_man/gateway/codex_benchmark/offline_locator.py`, `middle_man/gateway/codex_benchmark/tasks.py`, `tests/test_phase_22_15.py`.

## Pair validity and stop rule

A pair is VALID only if **both** arms start at the pinned commit/tree/content state; use the same original task bytes, CLI/model/effort/timeout and isolation controls; launch, exit zero, yield parsed nonempty final answers without invalid malformed/failed events; have empty external-tool and MCP activity; leave pre/post HEAD, porcelain status, and Git-visible content identical; and pass the task-specific semantic review. No retry can replace a failed arm.

If arm 1 is runtime-valid but semantically FAILS, **still run arm 2**. Stop before arm 2 only for runtime/launch failure, isolation contamination, repository-integrity failure or unknown post-run state, or missing/unparseable final result. Review answers against the same rubric, blind to arm where feasible. A semantic PASS requires material coverage of all core concepts and major areas with no material errors; synonymous wording and different correct structures count. Omission of an optional identifier alone is not failure.

## Semantic rubrics

### M01 semantic review

Required concepts:
- Live read-only execution is confirmation-gated; local preview prepares context and checks repository state before process creation.
- Context selection builds a pack and offline locator; production AUTO uses read-only mode, selected paths, and at least 10000 heuristic candidate-source tokens, not the shadow quality rule.
- An AUTO bypass preserves the original task prompt; LOCATOR USED appends source-free navigation hints and records original task hash plus local heuristic estimates.
- The production invocation uses a read-only sandbox, ignored user config, strict config, disabled Apps/plugins, no daemon, ephemeral mode, and no MCP registration.
- Execution parses JSONL final answer, provider usage, native reads/searches, and failure signals; malformed or missing results and MCP/external activity invalidate the run.
- Pre/post HEAD, status, and Git-visible content checks reject read-only changes even on zero exit; sanitized audit does not persist raw prompts, source, or full commands.

Major areas: CLI and local preview/AUTO; production isolation and process execution; event/search parsing and validity; repository integrity and sanitized audit. Material errors: Claims the shadow quality rule is active in production AUTO or that all read-only tasks use a locator.; Claims the source-free locator itself supplies source excerpts, or treats searches as explicit file reads.; Claims a zero exit overrides a repository mutation or that the audit stores raw prompt/source/full commands.. Exact names in the [manifest](locator_quality_prospective_plan.json) are optional diagnostic precision, not required wording.

### M02 semantic review

Required concepts:
- The MCP server exposes a context tool that forwards bounded task, mode, budget, path, symbol, and error inputs to the gateway.
- The gateway constructs a query, applies request/budget constraints, and asks ContextBuilder for the context pack; benchmark delivery caps are optional policy, not universal behavior.
- ContextBuilder redacts task/error text, indexes repository files and Git changes, then ranks candidates using lexical, explicit path/symbol, and relationship evidence.
- Indexed source reads enforce repository confinement and content freshness; selection chooses source ranges under a context budget and redacts deliverable excerpts.
- Gateway delivery can return source excerpts, progressive seed, or locator-only metadata under its policy; its ledger avoids repeating delivered lines and response metadata records fingerprint, warnings, and token estimates.

Major areas: MCP server and gateway request handling; indexing and relevance; source validation and budgeted selection; redacted delivery and ledger. Material errors: Claims the gateway blindly sends whole repository files or selects context by calling an external model.; Claims explicit paths can escape repository confinement or that stale source hashes are ignored.; Claims every context call must return full source or that local heuristic token estimates are Codex provider usage.. Exact names in the [manifest](locator_quality_prospective_plan.json) are optional diagnostic precision, not required wording.

### T03 semantic review

Required concepts:
- Tests assert that production commands retain the read-only sandbox and isolation controls, with Apps/plugins disabled and no MCP injection.
- Dry-run, missing confirmation, and preprocessing mutation tests prove the Codex process is not launched before required preflight checks.
- Synthetic process tests show a read-only repository mutation fails integrity even when the process exits successfully.
- The repository check compares pre/post HEAD, status, and Git-visible file content; an initially dirty tree can still pass if unchanged.
- Tests reject unexpected MCP/external activity and invalid event outcomes, while native repository searches alone are not external-tool activity.

Major areas: command and isolation tests; live-run synthetic process tests; repository snapshot and execution checks; event/external-activity checks. Material errors: Claims zero process exit is sufficient for read-only validity despite changed repository content.; Claims a dirty but unchanged repository automatically fails, or that the tests actually invoke an external Codex model.; Treats ordinary native search as MCP activity or says no isolation/preflight test exists.. Exact names in the [manifest](locator_quality_prospective_plan.json) are optional diagnostic precision, not required wording.

### G04 semantic review

Required concepts:
- A benchmark case creates workload requests, KV memory, a virtual clock, and the simulation engine under a configuration; allocation or simulation failure becomes a structured failed case.
- Metrics track per-request first-token, completion, inter-token latency, preemption/recompute, and prefix-cache reuse information.
- Aggregate metrics summarize completed/failed requests, token throughput per second, latency percentiles, elapsed time, scheduler iterations, and current/peak KV utilization from samples.
- A suite compares later successful variants to its first case as baseline; comparison deltas are variant minus baseline and percentage is omitted when baseline is zero.
- Reporting presents scenario-specific summaries, failures, and comparisons and explicitly distinguishes simulated performance from real GPU performance.

Major areas: benchmark case and simulation engine; per-request and aggregate metrics; variant comparison; report formatting. Material errors: Claims the reported simulator measurements are real GPU performance, provider token billing, or external model usage.; Reverses comparison delta direction or treats a zero baseline percentage as an ordinary numeric percentage.; Claims benchmark failures are silently converted to successful metric results.. Exact names in the [manifest](locator_quality_prospective_plan.json) are optional diagnostic precision, not required wording.

## Measurement and interpretation

For **valid pairs only**, primary outcome is `Middle_Man input_tokens - baseline input_tokens`, with percentage `100 * delta / baseline input_tokens`. Negative favors Middle_Man; positive favors baseline. Report exact values without a pre-invented 5% or 10% material-effect threshold or statistical-significance claim. No billing or quota interpretation.

For both arms record provider input, cached input, output, reasoning-output tokens; elapsed time; native calls, explicit reads, unique files, rereads; search/listing and content/file-targeted/repository-wide/file-listing searches and searched paths; Git inspections/unclassified commands; event count/malformed lines; external/MCP activity; and pre/post HEAD/status/content state. For Middle_Man also record AUTO reason, heuristic source/locator/visible estimates, selected paths, locator hash, and locator-read/search overlap. `input_tokens - cached_input_tokens` is **DIAGNOSTIC ONLY - NOT BILLING OR QUOTA**. Elapsed time and exploration counts are secondary; they never replace the primary outcome.

Directional shadow expectations, not correctness labels: M01 BYPASS is contradicted by a negative input delta; M02 PASS is contradicted by a positive delta. A zero delta is neutral. T03 and G04 have no directional prediction and remain UNCERTAIN regardless of one pair. If M01 or M02 contradicts the rule, it is not ready for production. Even if both align, that is provisional support only and does not justify enabling it.

## Separately authorized batches

1. **Batch 1:** M01, then M02; at most four future model processes. Stop and review after these pairs.
2. **Batch 2:** T03, then G04; at most four further processes, only with separate authorization after Batch 1 review. Never start automatically.

This preregistration authorizes **zero** model processes. There are no observed model outcomes, token deltas, or fake results in the manifest. Production AUTO, selector/relevance, locator construction, prompts, event/search semantics, and frozen Phase 22 behavior are untouched.
