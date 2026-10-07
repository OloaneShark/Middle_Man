# Local locator quality diagnosis

This is a pre-run diagnostic comparison, not a new A/B or a routing change. Reproduce with `.venv\Scripts\python.exe scripts/measure_locator_quality.py` from HEAD `bdd471f19bc4ffb9a0548cfcfdf54f4abdce6731`. The command uses two temporary Git snapshots, makes no model calls, disables index-cache writes, and prints JSON metadata only (no source excerpts). It verifies Git integrity plus the historical path lists and locator hashes before reporting. The Task A source-tree fingerprint also matches its frozen artifact. The temporary checkout sets `core.autocrlf=false`: Windows CRLF conversion changed the source bytes and locator selection in a trial checkout, whereas LF-byte checkout reproduces both historical locators exactly.

## Locked outcomes (post-run observations)

- Phase 22 Task A v4, frozen source fingerprint `a548097a4294fd67b2d42a5ab616c19b8ab226d702a406fa36f588873d0a0c1b`: baseline 86,515 vs locator 38,269 Codex-reported input tokens (48,246 fewer, 55.8%); interactions 10 -> 3; elapsed 26.378s -> 17.957s. Locator SHA-256 `14587213a088bcc66d0304ee0473fc23000bd01e2f13042c714a14550da62e97`.
- Production read-only loss, HEAD `bdd471f19bc4ffb9a0548cfcfdf54f4abdce6731`, task SHA-256 `55b50254c5eaadb5ef239ce14f0b25b3f3beee78eed7c596eb0062603f38a7eb`: Middle_Man first 520,777 vs baseline second 419,071 input tokens (+101,706, +24.27%); cached 441,856 vs 354,816; elapsed 115.003s vs 65.374s. Both runs passed runtime, semantic, isolation, and repository-integrity checks. Native calls 34 vs 34; searches 32 vs 31; content searches 8 vs 10. Locator SHA-256 `6be069352e2f897b9eea765fbc15516c6e4029ecd8651dc14191041e5d72d379`. This result is specific to this task and order.

## Pre-run comparison

"Useful" terms here are task terms appearing in at most `max(3, floor(0.3 * indexed_file_count))` indexed path/symbol records. This is an analysis definition, not an existing routing threshold. Direct evidence means at least one `explicit_path`, `trace_path`, `exact_symbol`, `filename_term`, or `symbol_term` signal on a selected path. The graph cluster metric uses only import/test edges between selected paths. Local token counts are heuristics and are not Codex provider usage.

| Metric | Task A win | Production loss |
| --- | ---: | ---: |
| Candidate source tokens | 33552 | 139640 |
| Selected source tokens | 5983 | 5999 |
| Locator tokens (local estimate) | 159 | 214 |
| Candidate paths | 41 | 50 |
| Selected paths | 12 | 13 |
| PRIMARY / RELATED | 12 / 0 | 13 / 0 |
| Test / non-test selected | 2 / 10 | 5 / 8 |
| Range phases REQUIRED / COVERAGE / DEPTH / REPAIR | 2 / 8 / 2 / 1 | 11 / 5 / 0 / 0 |
| Path phases REQUIRED / COVERAGE / DEPTH / REPAIR | 2 / 8 / 2 / 1 | 8 / 5 / 0 / 0 |
| Useful / rare query terms | 35 / 8 | 48 / 7 |
| Supported / direct-supported useful terms | 28 / 19 | 34 / 28 |
| Useful / direct term coverage | 0.8 / 0.5429 | 0.7083 / 0.5833 |
| Weak-only supported terms | 9 | 6 |
| Paths with no novel covered terms | 2 | 2 |
| Direct-evidence paths / ratio | 12 / 1 | 13 / 1 |
| Weak-only paths / ratio | 0 / 0 | 0 / 0 |
| Graph-expanded RELATED paths | 0 | 0 |
| Unique exact-symbol paths | 2 | 5 |
| Ambiguous-only exact-symbol paths | 0 | 3 |
| Top / median / minimum selected score | 246 / 156 / 74 | 449 / 183 / 115 |
| Selected within 50% / 75% / 90% of top | 0.6667 / 0.1667 / 0.0833 | 0.3077 / 0.1538 / 0.0769 |
| Selected / candidate source | 0.1783 | 0.043 |
| Locator / selected source | 0.0266 | 0.0357 |
| Directories / dispersion | 2 / 0.1667 | 6 / 0.4615 |
| Induced graph clusters | 1: 12 | 3: 10, 2, 1 |

### Signal counts

| Signal kind | Task A win | Production loss |
| --- | ---: | ---: |
| changed_relevant | 0 | 0 |
| exact_symbol | 2 | 9 |
| explicit_path | 0 | 0 |
| family_term | 27 | 26 |
| filename_term | 8 | 8 |
| import_neighbor | 10 | 8 |
| import_term | 38 | 31 |
| path_term | 0 | 3 |
| related_test | 2 | 5 |
| reverse_import_neighbor | 9 | 13 |
| source_term | 8 | 9 |
| symbol_term | 35 | 61 |
| tested_source | 8 | 8 |
| trace_path | 0 | 0 |

Task A's 12 selected paths form one import/test-connected lab cluster, with two test files and two specific unique exact-symbol hits (`InferenceRequest`, `WorkKind`). The loss pack spans six directories and three induced clusters; five of 13 paths are tests, including Claude and historical benchmark tests. Its top-scored path is a Claude test file, and only 4/13 selected paths score at least half of the top candidate. Four indexed files define `CLI`, so several high-scoring test selections share an ambiguous exact-symbol match. The loss also has unique exact-symbol evidence, however; uniqueness alone is not a valid gate.

Neither direct-evidence ratio nor broad term coverage distinguishes the outcomes: direct evidence is 100% in both, and the loss has *higher* direct-term coverage (0.5833 vs 0.5429). The larger candidate pool and stronger compression in the loss may be symptoms of a broad task, not proof of low quality. All selected paths were PRIMARY in both cases; graph-expanded RELATED ratio is zero despite graph signals on many paths. Raw test count, directory names, and raw score are also not sufficient on their own.

The production prompt asked for the production CLI, context selection, AUTO, isolated execution, event parsing, audit, and integrity enforcement. The pack includes the CLI and offline locator, but its five test selections and Claude runtime probe consume hints while `middle_man/gateway/codex_runner/runner.py`, `events.py`, `execution.py`, and `audit.py` are not selected. This is a pre-run topical observation, not an assertion that a different pack would have lowered provider input.

## Production-loss selected paths (pre-run only)

Each entry lists the complete selected candidate matched-term and matched-symbol metadata, signal kinds, and selector coverage keys. A phase and its covered keys explain selection; `anchor` keys identify required anchors, not evidence of subsequent native reads. "Novel" refers to query-term coverage credited in selection diagnostics, not semantic relevance.

### `tests/test_phase_23_claude.py`

- Role/score/phase: PRIMARY; 449; REQUIRED (test).
- Matched terms: appended, audit, auto, cli, codex, command, free, isolated, locator, only, path, read, rejected, reports, result, source, task, user.
- Matched symbols: CLI, task, test_ancestor_memory_rejected, test_cli_discovery_version_help_only, test_cli_dry_run_and_report_never_spawn_claude, test_cli_missing, test_cli_refuses_inference_even_with_confirmation, test_command_profiles_model_and_turns, test_command_requires_documented_flags_and_valid_turns, test_large_edit_auto_bypass_exact_prompt_and_zero_tokens, test_message_usage_fallback_only_observed_fields, test_optional_max_turns_absent_is_recorded_and_rejected, test_preflight_reports_existence_not_memory_contents, test_snapshot_memory_rejected, test_snapshots_source_identical_committed_clean_and_without_mcp, test_task_a_auto_locator_source_free_and_no_hidden_tests, test_user_memory_audit_reads_existence_only.
- Direct: exact_symbol, symbol_term. Weak: family_term, import_term, source_term. Graph: related_test, reverse_import_neighbor. Exact-symbol indexed path frequencies: CLI=4, task=1.
- Why selected (covered keys): anchor:tests/test_phase_23_claude.py, symbol:CLI, symbol:task, term:appended, term:audit, term:auto, term:cli, term:command, term:free, term:isolated, term:locator, term:only, term:rejected, term:reports, term:result, term:source, term:task, term:user. Novel terms: appended, audit, auto, cli, command, free, isolated, locator, only, rejected, reports, result, source, task, user.

### `tests/test_codex_live_runner.py`

- Role/score/phase: PRIMARY; 368; REQUIRED (test).
- Matched terms: appended, audit, cli, codex, command, context, event, execution, failures, final, integrity, locator, offline, only, path, production, read, remain, task, unchanged.
- Matched symbols: CLI, LARGE_TASK, test_cli_gate_and_dry_run_cannot_launch, test_dirty_read_only_worktree_is_accepted_if_unchanged, test_live_cli_prints_summary_and_final_answer, test_live_read_only_locator_and_usage_are_single_call, test_locator_reads_and_search_targets_stay_separate, test_locator_reads_and_search_targets_stay_separate.locator_preview, test_missing_usage_fields_remain_unknown, test_opt_in_audit_omits_prompts_commands_and_final_answer, test_read_only_mutation_is_invalid_even_on_zero_exit, test_save_audit_requires_live_confirmation, test_unexpected_mcp_event_invalidates_product_run.
- Direct: exact_symbol, filename_term, symbol_term. Weak: family_term, import_term, source_term. Graph: related_test, reverse_import_neighbor. Exact-symbol indexed path frequencies: CLI=4.
- Why selected (covered keys): anchor:tests/test_codex_live_runner.py, fileterm:codex:test, term:event, term:failures, term:final, term:integrity, term:production, term:read, term:remain, term:unchanged. Novel terms: codex, event, failures, final, integrity, production, read, remain, unchanged.

### `tests/test_codex_runner.py`

- Role/score/phase: PRIMARY; 336; REQUIRED (test).
- Matched terms: appended, auto, cli, codex, command, context, isolated, locator, offline, only, path, production, read, remain, starts, task, when.
- Matched symbols: CLI, TASK, test_cli_redacts_task_and_never_starts_exec, test_codex_discovery_checks_documented_help, test_command_has_no_benchmark_or_mcp_injection, test_dry_run_required_and_arbitrary_task_recognized, test_feature_probe_fails_closed_when_apps_remain_enabled, test_large_read_only_uses_existing_locator_exactly, test_repository_validation_and_task_validation, test_shared_baseline_command_uses_identical_isolation, test_small_read_only_bypasses_without_mutation.
- Direct: exact_symbol, filename_term, symbol_term. Weak: family_term, import_term, source_term. Graph: related_test, reverse_import_neighbor. Exact-symbol indexed path frequencies: CLI=4.
- Why selected (covered keys): anchor:tests/test_codex_runner.py, term:starts, term:when. Novel terms: starts, when.

### `tests/test_phase_22_v4.py`

- Role/score/phase: PRIMARY; 298; REQUIRED (test).
- Matched terms: appended, before, cli, codex, context, local, original, path, production, rejected, remain, selection, source, starts, task.
- Matched symbols: TASK, test_pinned_v4_source_contract, test_pinned_v4_source_contract.source, test_run_all_dry_run_starts_with_v4_without_external_call, test_v3_historical_values_remain_rejected_without_rescoring, test_v4_expected_metadata_does_not_enter_production_selector, test_v4_local_recall_and_direct_gateway_stdio_parity, test_v4_task_schema_and_invocation_are_versioned, test_v4_version_mixing_rejected_before_external_preflight.
- Direct: exact_symbol, symbol_term. Weak: family_term, import_term, source_term. Graph: related_test, reverse_import_neighbor. Exact-symbol indexed path frequencies: test_pinned_v4_source_contract.source=1.
- Why selected (covered keys): anchor:tests/test_phase_22_v4.py, symbol:test_pinned_v4_source_contract.source, term:before, term:local, term:original, term:selection. Novel terms: before, local, original, selection.

### `tests/test_phase_23_2_runtime.py`

- Role/score/phase: PRIMARY; 215; REQUIRED (test).
- Matched terms: appended, before, cli, failures, integrity, path, result, starts.
- Matched symbols: CLI, test_cli_exits_nonzero_after_failed_runtime_probe, test_dry_run_never_starts_claude, test_memory_contamination_stops_before_model_call, test_observed_receipt_is_not_raw_stream_or_benchmark_result.
- Direct: exact_symbol, symbol_term. Weak: family_term, import_term, source_term. Graph: related_test, reverse_import_neighbor. Exact-symbol indexed path frequencies: CLI=4.
- Why selected (covered keys): anchor:tests/test_phase_23_2_runtime.py. Novel terms: (none).

### `middle_man/mcp/gateway.py`

- Role/score/phase: PRIMARY; 214; REQUIRED.
- Matched terms: appended, context, execution, locator, original, production, selection, source.
- Matched symbols: MAX_CONTEXT_TOKENS, MCPGateway._locator_payload, MCPGateway.changed_context, MCPGateway.context, MCPGateway.context_pack, MCPGateway.context_stats, MCPGateway.expand_context, MCPGateway.explain_selection, MCPGateway.find_context.
- Direct: exact_symbol, symbol_term. Weak: family_term, import_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: MCPGateway.context=1.
- Why selected (covered keys): anchor:middle_man/mcp/gateway.py, symbol:MCPGateway.context, term:context, term:execution. Novel terms: context, execution.

### `middle_man/gateway/source.py`

- Role/score/phase: PRIMARY; 180; REQUIRED.
- Matched terms: path, read, source.
- Matched symbols: SourceFile, SourceReader, SourceReader.read, StaleSourceError, UnsafeSourceError.
- Direct: exact_symbol, filename_term, symbol_term. Weak: import_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: SourceReader.read=1.
- Why selected (covered keys): anchor:middle_man/gateway/source.py, fileterm:source:source, symbol:SourceReader.read. Novel terms: source.

### `middle_man/gateway/git_diff.py`

- Role/score/phase: PRIMARY; 165; REQUIRED.
- Matched terms: appended, path, read, starts.
- Matched symbols: GitDiffReader.read.
- Direct: exact_symbol, symbol_term. Weak: family_term, import_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: GitDiffReader.read=1.
- Why selected (covered keys): anchor:middle_man/gateway/git_diff.py, symbol:GitDiffReader.read. Novel terms: (none).

### `middle_man/gateway/codex_benchmark/runner.py`

- Role/score/phase: PRIMARY; 183; COVERAGE.
- Matched terms: appended, auto, codex, context, failures, isolated, local, locator, offline, path, read, reports, source, task.
- Matched symbols: CodexBenchmarkPair, CodexBenchmarkRun, CodexBenchmarkSuite, OFFLINE_ANCHOR_TASK_IDS, OFFLINE_LOCATOR_TASK_IDS, OFFLINE_MODES, _TASK_A_V2_EXPECTED, _codex_executable, _codex_version, classify_native_locator_reads, classify_native_read_coverage, validate_initial_context_budgets.
- Direct: symbol_term. Weak: family_term, import_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): term:codex, term:offline. Novel terms: codex, offline.

### `middle_man/gateway/codex_benchmark/offline_auto.py`

- Role/score/phase: PRIMARY; 141; COVERAGE.
- Matched terms: auto, codex, context, locator, offline, selection, source.
- Matched symbols: MIN_CANDIDATE_SOURCE_TOKENS, OfflineLocatorDecision, decide_offline_locator.
- Direct: filename_term, symbol_term. Weak: family_term, import_term, path_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): fileterm:auto:source, fileterm:offline:source. Novel terms: auto, offline.

### `middle_man/gateway/claude_benchmark/runtime_probe.py`

- Role/score/phase: PRIMARY; 130; COVERAGE.
- Matched terms: appended, cli, event, integrity, path, read, source.
- Matched symbols: READ_SENTINEL, _event_shape, _safe_path, _source_files.
- Direct: symbol_term. Weak: family_term, import_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): term:path. Novel terms: path.

### `middle_man/cli/codex_run.py`

- Role/score/phase: PRIMARY; 126; COVERAGE.
- Matched terms: audit, cli, codex, command, execution, failures, isolated, path, production, unchanged.
- Matched symbols: add_codex_run_command, run_codex_command, run_codex_preview.
- Direct: filename_term, symbol_term. Weak: family_term, import_term, path_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): fileterm:codex:source. Novel terms: codex.

### `middle_man/gateway/codex_benchmark/offline_locator.py`

- Role/score/phase: PRIMARY; 115; COVERAGE.
- Matched terms: appended, codex, context, execution, locator, offline, selection.
- Matched symbols: LOCATOR_HEADING, OfflineLocator, append_offline_locator, build_offline_locator.
- Direct: filename_term. Weak: family_term, import_term, path_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): fileterm:locator:source. Novel terms: locator.

## Task A selected paths (pre-run only)

### `middle_man/lab/request.py`

- Role/score/phase: PRIMARY; 246; REQUIRED.
- Matched terms: allocation, block, enum, field, generated, inference, output, preempted, preemption, recomputation, request, requests.
- Matched symbols: InferenceRequest, InferenceRequest.mark_preempted, InferenceRequest.remaining_output_tokens, InferenceRequest.total_allocated_block_count, RequestState.
- Direct: exact_symbol, filename_term, symbol_term. Weak: family_term, import_term. Graph: import_neighbor, tested_source. Exact-symbol indexed path frequencies: InferenceRequest=1.
- Why selected (covered keys): anchor:middle_man/lab/request.py, fileterm:request:source, symbol:InferenceRequest, term:allocation, term:block, term:generated, term:inference, term:output, term:preempted, term:preemption, term:recomputation, term:requests. Novel terms: allocation, block, generated, inference, output, preempted, preemption, recomputation, request, requests.

### `middle_man/lab/work.py`

- Role/score/phase: PRIMARY; 186; REQUIRED.
- Matched terms: enum, kind, recomputation, requests, scheduler, work.
- Matched symbols: WorkItem, WorkKind.
- Direct: exact_symbol, filename_term, symbol_term. Weak: family_term, import_term. Graph: import_neighbor, tested_source. Exact-symbol indexed path frequencies: WorkKind=1.
- Why selected (covered keys): anchor:middle_man/lab/work.py, fileterm:work:source, symbol:WorkKind, term:kind, term:scheduler. Novel terms: kind, scheduler, work.

### `tests/test_phase_7_preemption.py`

- Role/score/phase: PRIMARY; 176; COVERAGE (test).
- Matched terms: allocation, generated, inference, memory, output, preempted, preemption, preservation, preserved, recomputation, request, requests.
- Matched symbols: pressure_requests, test_disabled_preemption_keeps_clear_allocation_failure, test_preemption_decisions_and_timing_are_deterministic, test_pressure_preempts_rebuilds_and_preserves_output, test_request_larger_than_physical_memory_fails_cleanly.
- Direct: filename_term, symbol_term. Weak: family_term, import_term, source_term. Graph: related_test, reverse_import_neighbor. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): anchor:tests/test_phase_7_preemption.py, fileterm:preemption:test, term:preservation, term:preserved. Novel terms: preemption, preservation, preserved.

### `middle_man/lab/memory_control.py`

- Role/score/phase: PRIMARY; 175; COVERAGE.
- Matched terms: allocation, block, control, controller, inference, kind, kv, memory, policy, preemption, recomputation, request, victims, work.
- Matched symbols: MemoryController, PreparedWork.
- Direct: filename_term, symbol_term. Weak: family_term, import_term, source_term. Graph: import_neighbor, reverse_import_neighbor. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): fileterm:control:source, fileterm:memory:source, term:controller. Novel terms: control, controller, memory.

### `tests/test_phase_4_engine_runner.py`

- Role/score/phase: PRIMARY; 169; COVERAGE (test).
- Matched terms: across, allocation, generated, inference, kind, memory, output, release, request, requests, scheduler, work.
- Matched symbols: RecordingScheduler, test_engine_chunks_prefill_across_iterations_before_decode, test_engine_completes_requests_and_releases_memory, test_zero_output_request_completes_after_prefill_and_releases_memory, test_zero_prompt_and_zero_output_request_terminates_without_work.
- Direct: symbol_term. Weak: family_term, import_term, source_term. Graph: related_test, reverse_import_neighbor. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): graph:test, term:across, term:memory, term:release, term:request, term:work. Novel terms: across, memory, release, request, work.

### `middle_man/lab/engine.py`

- Role/score/phase: PRIMARY; 161; DEPTH.
- Matched terms: block, control, controller, generated, inference, kind, kv, memory, policy, preemption, recomputation, release, request, requests, scheduler, work.
- Matched symbols: SimulationEngine._release_completed, SimulationEngine._release_request, SimulationEngine._scheduler_from_config.
- Direct: symbol_term. Weak: family_term, import_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): (none). Novel terms: (none).

### `middle_man/lab/memory.py`

- Role/score/phase: PRIMARY; 151; COVERAGE.
- Matched terms: allocation, block, kv, memory, release, request, requests, selection.
- Matched symbols: AllocationError, KVBlockManager, KVBlockManager._release_block_ref, KVBlockManager.block_ref_count, KVBlockManager.free_block_count, KVBlockManager.release_cache_blocks, KVBlockManager.release_request, KVBlockManager.request_blocks, KVBlockManager.used_block_count, MemorySnapshot.
- Direct: filename_term, symbol_term. Weak: family_term. Graph: import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): term:selection. Novel terms: selection.

### `middle_man/lab/preemption.py`

- Role/score/phase: PRIMARY; 124; COVERAGE.
- Matched terms: block, inference, kv, memory, policy, preempted, preemption, request, requests, victim, victims.
- Matched symbols: LargestPrivateOwnerPolicy, LargestPrivateOwnerPolicy.choose_victim, PreemptionPolicy, PreemptionPolicy.choose_victim.
- Direct: filename_term, symbol_term. Weak: family_term, import_term. Graph: import_neighbor, reverse_import_neighbor. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): fileterm:preemption:source, term:policy, term:victim, term:victims. Novel terms: policy, preemption, victim, victims.

### `middle_man/lab/scheduler.py`

- Role/score/phase: PRIMARY; 122; COVERAGE.
- Matched terms: inference, kind, policy, preempted, recomputation, request, scheduler, work.
- Matched symbols: BalancedScheduler, DecodePriorityScheduler, SchedulerPolicy.
- Direct: filename_term, symbol_term. Weak: family_term, import_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): fileterm:scheduler:source. Novel terms: scheduler.

### `middle_man/lab/metrics.py`

- Role/score/phase: PRIMARY; 109; DEPTH, COVERAGE.
- Matched terms: block, generated, inference, kv, memory, recomputation, request, requests.
- Matched symbols: KVSample, MetricsCollector._request_metrics, RequestMetrics.
- Direct: symbol_term. Weak: family_term, import_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): term:kv. Novel terms: kv.

### `middle_man/lab/workloads.py`

- Role/score/phase: PRIMARY; 94; COVERAGE.
- Matched terms: enum, inference, interaction, request, requests, scheduler.
- Matched symbols: RequestSpec, RequestSpec.create_request, WorkloadSpec.create_requests.
- Direct: symbol_term. Weak: family_term, import_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): term:interaction. Novel terms: interaction.

### `middle_man/lab/trace.py`

- Role/score/phase: PRIMARY; 74; REPAIR.
- Matched terms: preempted, recomputation, work.
- Matched symbols: WORK_EVENTS.
- Direct: symbol_term. Weak: family_term, source_term. Graph: import_neighbor, reverse_import_neighbor, tested_source. Exact-symbol indexed path frequencies: (none).
- Why selected (covered keys): (none). Novel terms: (none); repair: underrepresented_query_evidence.

## Post-run exploration (excluded from pre-run scores)

Production locator paths explicitly read: 0/13. The following exact locator paths were targeted by native searches (3/13); 7 non-locator paths were also searched. A directory-wide search is not counted as a read of any member file. These facts cannot enter a pre-run AUTO decision.

| Production selected path | Exact path searched? |
| --- | --- |
| `tests/test_phase_23_claude.py` | No observed exact-path target |
| `tests/test_codex_live_runner.py` | No observed exact-path target |
| `tests/test_codex_runner.py` | Yes |
| `tests/test_phase_22_v4.py` | No observed exact-path target |
| `tests/test_phase_23_2_runtime.py` | No observed exact-path target |
| `middle_man/mcp/gateway.py` | No observed exact-path target |
| `middle_man/gateway/source.py` | No observed exact-path target |
| `middle_man/gateway/git_diff.py` | Yes |
| `middle_man/gateway/codex_benchmark/runner.py` | No observed exact-path target |
| `middle_man/gateway/codex_benchmark/offline_auto.py` | No observed exact-path target |
| `middle_man/gateway/claude_benchmark/runtime_probe.py` | No observed exact-path target |
| `middle_man/cli/codex_run.py` | Yes |
| `middle_man/gateway/codex_benchmark/offline_locator.py` | No observed exact-path target |

In the frozen optimized Task A run, eight locator paths were explicitly read. These are read observations, not a pre-run signal; the available record is not being used here to infer per-path search targets.

| Task A selected path | Explicitly read? |
| --- | --- |
| `middle_man/lab/request.py` | Yes |
| `middle_man/lab/work.py` | Yes |
| `tests/test_phase_7_preemption.py` | Yes |
| `middle_man/lab/memory_control.py` | Yes |
| `tests/test_phase_4_engine_runner.py` | No observed explicit read |
| `middle_man/lab/engine.py` | Yes |
| `middle_man/lab/memory.py` | Yes |
| `middle_man/lab/preemption.py` | Yes |
| `middle_man/lab/scheduler.py` | Yes |
| `middle_man/lab/metrics.py` | No observed explicit read |
| `middle_man/lab/workloads.py` | No observed explicit read |
| `middle_man/lab/trace.py` | No observed explicit read |

## Interpretation and next step

The 263 heuristic model-visible Middle_Man tokens in the production run cannot themselves explain +101,706 Codex-reported input tokens. A locator could alter search choices, command output volume, tool trajectory, turn/context replay, or cache behavior. The pair does not isolate which mechanism caused the difference, and similar native call counts do not establish similar output sizes.

Candidate *production-only* confidence inputs, ranked for investigation rather than assigned thresholds:

1. Evidence specificity: discount exact-symbol matches common across indexed files and inspect whether task-specific terms/symbols reach the intended implementation area. The observed `CLI` repetition is illustrative, not a disqualifier by name.
2. Concentration and coherence together: score distribution, test/source balance relative to task intent, and induced graph connectivity. These differ here, but broad cross-module tasks can validly disperse.
3. Coverage provenance: whether selected files add distinct useful terms through direct evidence versus generic lexical family/source matches or depth fill. Current direct ratio and direct-term coverage alone are not discriminating.
4. Compression and graph-expansion ratios as context, not standalone gates; both can move with repository/task size.

Reject task IDs, fixed directory blacklists, test-file bans, the raw candidate-token floor, and thresholds chosen to separate only these two points. The current AUTO criterion (read-only + selected paths + candidate source >= 10,000 heuristic tokens) demonstrably has no locator-quality term. A future additive production gate could combine size with validated confidence signals only after a broader, locked retrospective sample and prospective shadow-mode evaluation. Do not modify frozen Phase 22 AUTO or select a numeric threshold now.

### Native output-size telemetry feasibility

The current production and shared JSONL parsers retain completed command names/counts, searches, and usage, but not per-command output length. The checked fixtures contain command strings without output fields; the sanitized frozen event records also omit output. `stderr_length_bytes` measures the Codex process stderr, not native command output. Thus the current stored evidence cannot reliably calculate `native_command_output_bytes_total/max` or `search_output_bytes_total/max`. A future parser could count UTF-8 bytes of a documented, consistently emitted completed-command output field *in memory*, aggregate by safe command class, and persist only counts/buckets, after schema/version fixture validation. Do not persist output content, source text, full commands, or search terms. If the runtime JSONL never exposes complete output, mark these metrics unavailable rather than estimate them from provider tokens.
