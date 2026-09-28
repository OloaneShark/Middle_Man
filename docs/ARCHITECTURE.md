# Middle_Man Architecture

This document describes the implemented Lab through Phase 10 and the separate local Agent Gateway through Phase 19. Lab behavior remains unchanged.

## Components

```text
arrivals -> engine admission -> scheduler -> memory controller -> simulated runner
               |                  |              |                  |
               |              token budget   KV allocator         virtual clock
               |                             prefix cache
               |                             preemption policy
               +------------------- structured events ---------------------+
                                      metrics collector
```

- `request.py` owns lifecycle and token invariants. Completed requests cannot resume work.
- `scheduler.py` produces bounded `PREFILL`, `DECODE`, and `RECOMPUTE` work. It does not allocate KV blocks.
- `memory.py` owns physical block IDs, free lists, per-request mappings, and reference counts.
- `memory_control.py` reserves blocks for plans and resolves pressure.
- `preemption.py` chooses victims through a replaceable policy.
- `prefix_cache.py` owns key/length mappings and cache-held block references.
- `runner.py` calculates deterministic simulated execution time.
- `clock.py` owns virtual time.
- `events.py` defines immutable trace records.
- `metrics.py` converts actual request state, events, and KV samples into structured results.
- `engine.py` coordinates these components and returns `EngineResult`.
- `workloads.py` describes immutable request inputs and deterministic presets.
- `benchmarks.py`, `suites.py`, and `comparison.py` run isolated cases and calculate measured differences.
- `reporting.py`, `serialization.py`, and `trace.py` present structured results and events.
- `visualization.py` renders optional headless plots from recorded data.

## Phase 5: Continuous Batching

At each iteration the engine admits arrived requests while `max_active_sequences` permits. When a short request completes, its slot can be filled at the next iteration even if another request remains active. A request is never admitted before its arrival time. There are no fixed batch boundaries. `REQUEST_ADMITTED` and `REQUEST_COMPLETED` events make this ordering testable.

With prefix caching enabled, simultaneous compatible requests wait for the first active request to publish their shared prefix. The waiting request then joins with reused blocks. This small cache-specific admission gate avoids computing the same prefix twice in the first plan.

## Phase 6: Metrics and Events

`EngineResult.metrics` contains per-request metrics, aggregate metrics, and timestamped KV samples. The aggregate includes completed/failed counts, actual prompt/output/recompute work, simulated throughput, TTFT and E2E averages and P50/P95/P99, iteration count, preemptions, KV current/peak utilization, cache hits/misses/reuse, and peak cache occupancy. Per-request metrics include arrival, first-token and completion times, prompt/output counts, TTFT, E2E, preemption/recompute counts, cache status, and average inter-token latency when at least two output timestamps exist.

TTFT is measured from arrival to the first generated output token; requests with no output have no TTFT. E2E is measured from arrival to completion. Percentiles use linear interpolation over observed values. Throughput divides executed token counts by the run's elapsed simulated seconds. Total work includes recomputation; prompt throughput includes only original prompt prefill executed by the runner. Zero elapsed time yields zero throughput, and empty populations have no latency percentile. KV samples record used, total, and cached block counts. These are simulator measurements, not GPU measurements.

Events record admissions, completed requests, executed prefill/decode/recompute work, KV allocation/release, preemptions, and prefix hits/misses. Events and metrics are scoped to each `run()` invocation. An injected clock continues forward across runs.

## Phase 7: Preemption

`preemption_enabled` remains `False` by default. With it disabled, failed allocation raises `AllocationError`. When enabled, `LargestPrivateOwnerPolicy` chooses the active non-terminal request with the most private blocks, breaking ties by request ID. It never selects the requester. The memory controller releases that victim's private and shared request references, records the event and physical blocks freed, and retries the allocation.

Preemption never reduces `prompt_processed` or `output_generated`. It creates `recompute_pending_tokens` equal to the context that must be rebuilt. The scheduler executes budgeted `RECOMPUTE` work before the victim resumes prefill or decode; those executed tokens increment `recomputed_tokens` and incur simulated prefill-style cost. A victim waits until the request that caused pressure completes, preventing immediate eviction cycles. If a requested context cannot fit in physical memory, or no victim can make progress, the engine raises a deterministic allocation error. Failed runs release their own KV holdings during cleanup.

## Phase 8: Prefix Caching

`prefix_cache_enabled` remains `False` by default. A request opts in with `prefix_key` and `shared_prefix_tokens`. Cache entries are matched by key and declared prefix length. An incompatible length under the same key is treated as a miss and computed privately. The simulator trusts callers to use one key only for identical prefix content; it does not inspect token values.

Only full prefix blocks are shareable. For 16-token blocks and a 20-token declared prefix, 16 tokens are reused; the remaining four are private prefill work. This prevents request-specific continuation from sharing the unused positions of a physical block.

Once a request processes the reusable prefix, the cache retains references to its prefix block IDs. A later compatible request attaches the same physical IDs and increments each reference count. Request release decrements only its ownership; cache ownership keeps the entry valid. Preemption releases a victim's references without destroying cache-held or other requests' references. On resumption, a still-valid cache entry may satisfy part of the rebuild debt. Cache entries are released at the end of a run, including failed runs; successful workloads leave no KV blocks owned by the run.

## Phase 9: Workloads and Benchmarks

`workloads.py` defines frozen `RequestSpec` and `WorkloadSpec` values. `WorkloadSpec.create_requests()` builds fresh mutable `InferenceRequest` objects for every run. Presets cover short chat, mixed chat, long context, burst traffic, memory pressure, shared prefixes, and decode/prefill competition. Generated variation uses a local seeded random generator; comparisons share one immutable workload and seed.

`benchmarks.py` runs each `BenchmarkCase` with a fresh engine, virtual clock, and KV manager. It returns structured metrics, event counts and trace events, configuration, seed, request count, and final KV ownership. Expected `AllocationError` and `SimulationError` cases become structured `BenchmarkFailure` values. Other exceptions propagate. `BenchmarkSuite` groups cases. `suites.py` defines scheduler, prefix-cache, memory-pressure, token-budget, active-sequence, and chunked-prefill comparisons, plus simple mixed and short-chat runs. The no-preemption constrained memory case intentionally reports a failure.

`comparison.py` computes absolute and percentage deltas against the first successful baseline, leaving percentage change undefined when the baseline is zero. It does not label a universal winner. A cache-enabled run may do less prompt work and finish sooner while retaining more KV blocks; throughput counts *executed* work, so its direction can also differ from elapsed-time improvement.

`serialization.py` writes JSON with complete structured results and CSV with flat case/aggregate rows. Exports include version, UTC timestamp, seed, workload, Lab configuration, failure details, and an explicit `simulated` marker. Output filenames are sanitized. The default `benchmark_results/` directory is Git-ignored; generated results are not committed by default.

## Phase 10: CLI, Traces, and Plots

`python -m middle_man simulate` remains supported. `--debug` formats the existing event stream into timestamped work, lifecycle, and memory sections with cumulative prompt progress; `--trace-json` exports the same events. No second trace source is maintained.

`python -m middle_man benchmark --list` lists suites without running them. `benchmark NAME` runs a suite and prints measurements with an explicit simulated-performance label. `--seed`, `--json`, `--csv`, `--output-dir`, `--verbose`, and `--plot` control benchmark output. The CLI delegates execution, formatting, and storage to separate Lab modules.

`visualization.py` imports matplotlib only when a plot is requested and uses a headless backend. It can save a request timeline from observed admission/work/preemption/completion events, KV utilization from recorded samples, a TTFT distribution, and a throughput comparison. The timeline connects actual lifecycle event times; work types are point markers because the simulator does not record per-item start intervals. Performance plots say `SIMULATED`. Install the optional `viz` extra for plotting; the core simulator and benchmark API have no matplotlib dependency.

## Verification Boundary

The suite preserves all 54 Phase 1-8 tests and adds workload, benchmark, determinism, failure, serialization, CLI, trace, and visualization coverage. Each completed benchmark case reports zero final KV blocks owned by its isolated memory manager.

Agent Gateway indexing and relevance search are implemented through Phase 14, with local Context Packs, Git diff context, and output compaction through Phase 17. MCP, Codex and Claude integrations, provider APIs, and real PyTorch execution are not implemented.

## Phases 11-14: Local Agent Gateway

```text
repository -> safe scanner -> parser registry -> immutable RepositoryIndex
                |                  |                  |
          ignore/size rules    Python AST        symbols/imports/tests
                |                                     |
                +--------> versioned JSON cache <----+
                                                      |
query + optional trace/changed paths -> relevance engine -> ranked reasons
```

`GatewayConfig` is separate from `LabConfig`. It validates a pathlib repository root, an in-root cache path, file-size and search limits, symlink behavior, Git use, and parsing mode. Paths are resolved against the root and stored as relative POSIX paths. The scanner does not traverse outside the root. Directory symlinks are skipped by default; even when following symlinks is enabled, external targets are rejected. Obvious secret-bearing names and generated/dependency directories are excluded before reading source. Root `.gitignore` and `.middlemanignore` use a conservative ordered glob subset, with Middle_Man rules applied last. This is not complete Git ignore behavior or content-based secret detection.

Every discovered non-ignored file has an immutable `IndexedFile` record with SHA-256 of actual bytes, size, mtime, language, text/binary status, test convention, parse status, and compact structural data. Oversized files remain visible but are not parsed. Python's built-in AST extracts classes, functions, async methods, decorator names (not call arguments), module constants, and imports. Other recognized text languages use `PlainTextParser` until richer adapters exist. Syntax failures stay local to the malformed file. `RepositoryIndex` exposes immutable records and read-only lookup maps for files, symbols, imports, reverse imports, and tests. Local Python imports resolve to repository module paths; `IMPORTS`, `TESTS`, and `CONTAINS_SYMBOL` relationships are rebuilt from current records each scan.

The indexer hashes files on every scan, then reuses cached parsed records when hashes match. A changed hash reparses only that file; deleted records and obsolete edges disappear. The cache stores metadata, symbols, and imports, not full source. `INDEX_SCHEMA_VERSION = 2` is independent of the package version. The JSON cache is written with an atomic replacement, and corruption, schema mismatch, root mismatch, or parsing-policy mismatch causes a safe rebuild. `cache clear` unlinks only Middle_Man's `index.json`. Identity includes normalized root, name, optional Git branch/HEAD, timestamp, and schema version. Git calls use subprocess argument arrays; Git is optional.

`RelevanceEngine` ranks exact paths and symbols most strongly, then filename, symbol, path, and import terms. One-hop imports, reverse imports, and test edges add smaller RELATED signals. Error trace paths/identifiers can contribute direct signals; changed files get a modest boost only after another relevance signal. CamelCase and snake_case terms are normalized while exact identifiers remain available. Weights live in one table, results carry factual reasons, and deterministic score/path ordering plus a minimum threshold excludes unrelated files. This ranks **which files and symbols matter**. Phase 15 then selects bounded source excerpts. No external model or API is involved.
## Phase 15: Context Packs

```text
ContextQuery -> RelevanceEngine -> candidate files -> SourceReader (root/hash checks)
                                               |             |
                                               |         indexed AST ranges
                                               v             v
                                        ContextBuilder -> immutable ContextPack
                                                           |            |
                                                     formatter     JSON export
```

`ContextPack`, `SourceExcerpt`, `ContextMetrics`, `ChangedContext`, and `ExpansionRequest` are immutable. The pack stores task, repository identity, ranked candidates and reasons, source ranges/text, related tests, relevant changed files, warnings, redaction categories, generation, and metrics. It does not use one giant prompt string as its internal form. `SourceReader` accepts only indexed in-root text files, applies symlink and size checks, and compares current bytes to the indexed SHA-256. A mismatch causes one fresh index-and-select attempt; repeated races raise `StaleSourceError`. Missing/changed prior ranges during expansion are not blindly reused.

`ContextBuilder` selects complete Python AST symbol ranges, including decorators, a parent class header, and referenced import/constant lines where deterministically identifiable. Small relevant files or ranges covering most of a file become complete-file excerpts. Nearby ranges merge. SAFE uses fuller surroundings, BALANCED narrower margins, and AGGRESSIVE minimal margins plus an explicit reduction warning. Exact paths/symbols and trace matches are required units under budget pressure; they remain complete and produce `BUDGET_EXCEEDED_FOR_REQUIRED_SYMBOL` if necessary. Lower-priority units are omitted with structured warnings. `expand` returns a new generation, merges prior ranges, supports explicit files/symbols, related imports/tests, next candidates and surrounding lines, and does not mutate the old pack.

The replaceable `TokenEstimator` currently uses `ceil(UTF-8 bytes / 4)`. Metrics count source text only, not Markdown framing. The raw baseline is complete current text for considered relevance candidates, not every repository file. Selected bytes/tokens are based on sanitized excerpts; avoided tokens and reduction percentages are estimates. Overlap-avoided bytes are measured from merged requested ranges. The fingerprint hashes normalized task inputs, selected source hashes/ranges/redacted text, mode, budget, and generation; timestamps and unrelated changed paths do not affect it. **Estimated context tokens are not provider billing tokens or Codex plan usage.**

## Phase 16: Git Diff-Aware Context

`GitDiffReader` uses argument-array Git subprocess calls. For repositories with HEAD, `git diff HEAD --unified=0 --find-renames` covers both staged and unstaged changes; initial repositories combine cached and unstaged diffs. Porcelain status adds untracked paths and statuses. Immutable `GitDiff`, `FileDiff`, `DiffHunk`, and `DiffLine` records retain paths, rename origin, additions/deletions, hunk coordinates and changed lines, with binary changes flagged. The diff command prints concise metadata, not raw patches. Non-Git roots return an empty non-Git result.

Changed new-line ranges map to the innermost enclosing indexed Python symbol. A Context Pack can then include that complete function rather than only edited lines. Changed-file paths feed the existing relevance engine's modest boost; they do not exclude unchanged dependencies or tests. `ChangedContext` in the pack stores affected symbols and hunk ranges without exporting raw diff lines.

## Phase 17: Output Compaction and Safety

`OutputCompactor` dispatches to pytest, generic/Docker log, Git-status, and structured Git-diff preparation. Exact consecutive duplicates collapse without reordering different messages. Pytest passing-test lines are counted and condensed while failures, tracebacks, assertions, warnings and final summaries remain. Generic budget trimming treats tracebacks as atomic blocks, keeps errors and warnings, and inserts explicit omission counts for dropped low-priority lines. Git status and structured diff preserve all changed paths even when this exceeds the requested budget. `CompactionResult` stores sanitized output, lengths, estimated tokens, omitted/repeated counts, warnings and a fingerprint, not a raw log copy. CLI supports files and piped stdin.

`SecretRedactor` runs before any source excerpt or compacted output enters an exportable result. It replaces high-confidence assigned values, bearer tokens, credential URLs and whole PEM private-key blocks with a marker; metadata records categories without values. Ordinary `token_count` and password-hashing code remain intact. This deterministic filter is intentionally conservative and cannot guarantee detection of every secret. The index cache still persists no full source or detected secret values.

Local quality fixtures measure required-file and required-symbol recall, irrelevant files included, and estimated token reduction against complete candidate files. A fixture succeeds only if required recall is 100% and selected estimated source tokens are lower than its raw candidate baseline. These are local context-efficiency measurements, not Codex or provider usage measurements.

## Phase 18: Project Memory

```text
RepositoryIndexer + GitDiffReader
              |
              v
      ProjectMemoryService -> immutable ProjectMemory -> formatter/CLI
              |
              v
 AtomicJsonStore(.middle_man_cache/project_memory.json)
```

`PROJECT_MEMORY_SCHEMA_VERSION = 1` is independent of the index schema. `MemoryFact` records controlled provenance (`INDEX`, `GIT`, `DIFF`, `USER`, `HANDOFF`, `TOOL_RESULT`) with optional evidence path/hash and an explicit user-supplied flag. Current derived fields include language counts, conservative technology detections with evidence, branch/HEAD, important components/symbols, and compact working-tree changes with statuses and affected symbols. Detection uses indexed file types, recognized config/manifest files and imports, not repo-name guesses. Component ranking uses local import connectivity, public class/function symbols, and generic entry/configuration roles. `MemorySettings` bounds components (20) and symbols (40) by default. No full source or diff is copied.

Decisions and known issues are explicit user notes. They are sanitized *before* being written; categories are retained but original secret values are not. Issues can be resolved, and replacement decisions can name a superseded ID. Refresh first validates the old record, recomputes all derived state, and preserves valid notes and resolution state. Malformed JSON, missing fields, schema/root mismatch or bad fingerprint stop refresh with a clear error so recoverable notes are not silently lost. The semantic fingerprint excludes timestamps. Serialized-byte and estimated-token counts are computed for the saved payload. `AtomicJsonStore` enforces in-root paths, rejects symlink destinations, writes a temporary JSON file and replaces atomically. `memory show/refresh/status/decision/issue` are presentation commands over the service.

Project Memory is **not AI-generated long-term memory**. Code structure is evidence of structure, not proof of developer intent.

## Phase 19: Session Handoff

```text
explicit task + current GitDiffReader + refreshed ProjectMemory
        + optional Context Pack metadata + supplied CompactionResult
                              |
                              v
                        HandoffService
                              |
                              v
    immutable SessionHandoff -> local JSON + latest ID pointer
                              |
                              v
                  HandoffView (current/stale reasons)
```

`HANDOFF_SCHEMA_VERSION = 1` is independent of both other schemas. A handoff requires caller task text. It captures current changed files/statuses/affected symbols, file hashes, current branch/HEAD, Project Memory fingerprint, explicit unresolved issues/next steps, optional Context Pack fingerprint/mode/query/selected paths/token estimate/warnings, and only actual supplied compacted test/tool outcomes. Context Pack excerpts and raw logs are not duplicated. No fabricated test status, intentions or next actions are recorded. All free-form input passes through `SecretRedactor` before persistence. `handoff create/latest/show/list` use local versioned records under `.middle_man_cache/handoffs/`; the latest pointer contains only a validated fingerprint ID, not an arbitrary path. Old records are never auto-deleted.

On read, the service reindexes and refreshes Project Memory to report `HEAD_CHANGED`, `BRANCH_CHANGED`, `FILE_CHANGED`, `FILE_REMOVED`, and `PROJECT_MEMORY_CHANGED`. Old records remain available. Semantic fingerprints exclude creation time. The payload reports serialized bytes and `ceil(UTF-8 bytes / 4)` estimated tokens; a configurable soft limit warns without silent truncation. The documented reconstruction baseline is the full current text of deduplicated changed/referenced readable files, plus raw supplied tool output. The handoff payload is compared to that baseline; the difference may be negative. These are local context estimates, **not** Codex/Claude billing or plan usage. CLI reads stdin only with `--pytest-stdin`.

## Current Boundary

The Lab remains locked through Phase 10. The local Gateway is implemented through Phase 19. MCP, Codex and Claude connections, provider adapters, external AI/API calls, external LLM summarization, and Phase 20+ are not implemented.