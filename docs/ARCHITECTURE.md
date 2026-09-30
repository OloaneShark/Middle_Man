# Middle_Man Architecture

This document describes the Lab through Phase 10, local Agent Gateway through Phase 19, MCP/Codex integration through Phase 21, and Phase 22 through its local 22.4 selector and fallback work. Lab behavior remains unchanged.

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

Agent Gateway indexing and relevance search are implemented through Phase 14, with local Context Packs, Git diff context, and output compaction through Phase 17. A local MCP server and Codex guidance are implemented in Phases 20-21. Claude integration, provider APIs, and real PyTorch execution are not implemented.

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

## Phase 20: Local MCP Server

`MCPGateway` adapts the existing index, relevance, verified-source ContextBuilder, Git reader, memory/handoff, compaction, and secret-redaction services to one explicit repository root. The canonical immutable `ContextPack` remains the source of truth. The optional official Python MCP SDK serves stdio; it is not needed by Lab or non-MCP Gateway commands.

`middle_man mcp serve --repo ROOT` defaults to `--tool-profile codex-core`: `middleman_context`, `middleman_expand_context`, `middleman_session_handoff`, `middleman_compact_output`, and `middleman_project_state`. `--tool-profile full` preserves the original ten tools, including diagnostic find-context, context-pack, change, stats, selection, and repo-map operations. Python `create_server(config)` defaults to full for API compatibility.

Core `middleman_context` invokes the same ContextBuilder as full `middleman_context_pack`; only serialization differs. It sends path/range/source/symbol/reason and a `complete_file` boolean, fingerprint/mode/generation, warnings, and compact metrics, not duplicated candidates, selected paths, content hashes, or verbose metrics. The session-local `DeliveryLedger` stores only fingerprint plus path/content-hash/line identities. After a successful usage-log write, it records delivered lines. Identical packs return an unchanged/no-source response, and different packs send only unseen lines; core expansion also sends only new ranges while the underlying ContextPack remains cumulative. `force_replay` is retained only in the direct Python Gateway for explicit diagnostics, not on the Codex-core tool. Full responses remain rich. Source remains verified and redacted; native reads are still needed when context is stale or insufficient.

`MCPUsageLog` schema v3 records timestamp, tool, success/error, input fingerprint, pack fingerprint/generation, metrics, delivered path/hash/line ranges and per-line UTF-8 sizes, plus package version, usage schema, and a SHA-256 fingerprint of selected current server implementation files. It also records a random per-Gateway `server_session_id`, monotonic `call_sequence`, ledger line counts before/after delivery, and requested/effective budget metadata. The ledger projects its post-call count before the successful usage write, then commits the identities; it never stores source. The log never persists task text, source excerpts, raw diffs, or known secret values. Historical v1/v2 usage logs remain readable by the summary command. All token counts here use a UTF-8-byte heuristic, not Codex billing or reported input usage.

## Phase 21: Codex Integration

The root `AGENTS.md` routes a fresh scoped task directly to `middleman_context`; continuation uses handoff, broad orientation uses project state only when needed, and expansion/compaction are conditional. Native search, reads, Git, and tests remain available. `docs/CODEX_SETUP.md` covers registration and protocol checks. The agent chooses whether to call MCP; Middle_Man does not replace native access.

## Phase 22: Real Codex A/B Benchmark

`middle_man.gateway.codex_benchmark` is separate from simulated Lab benchmarks and local context fixtures. It prepares independent committed snapshots, parses sanitized Codex JSONL events, gates correctness, and records official usage fields when exposed. Live runs require an explicit external-service confirmation; normal pytest and local measurement do not invoke `codex exec`. Baseline has no project AGENTS routing or Middle_Man MCP registration. Optimized uses the current isolated MCP server code against its historical target snapshot, records the `codex-core` profile and implementation identity, and writes usage only into that snapshot. A pair is invalid on MCP isolation/identity failure, source mismatch, or other infrastructure contamination.

Task A v1 remains a frozen literal-marker evaluator. Its first infrastructure-valid pair was **FAIL/FAIL**: optimized reduced native calls/search/listing but increased file reads and Codex-reported input tokens from 144,903 to 391,753. Historical overlap was unavailable because the snapshot's old MCP code shadowed the then-current implementation. An earlier suite attempt was infrastructure-invalid. Task A v2 adds an explicit request for concrete identifiers and the same `--output-schema` on both sides; its fields are checked exactly, including an explanation and Git cleanliness. The expected identifiers are not in the prompt or schema. Task/evaluator versions are recorded and cannot be aggregated across v1/v2. The OAuth and upload edit fixtures remain unchanged.

`native_reads.py` recognizes explicit PowerShell and Python reads and normalizes only existing in-root paths; arbitrary source filenames in search commands are not reads. `overlap.py` uses delivered path/hash/line identity to distinguish unique and repeated source. The read counters and MCP result sizes are observational or heuristic and are not interchangeable with Codex-reported tokens.

## Phase 22.1: Local Candidate Optimization

`scripts/measure_phase22_1.py` builds a fresh temporary committed Task A snapshot and measures official MCP SDK tool definitions and both result representations, with no external Codex call. At that time, full/core tool surfaces were 10/5 tools and 1,643/835 estimated definition tokens. A BALANCED Task A pack had identical fingerprint/source/warnings/selected estimate in both representations: full/core result estimates were 14,125/5,710, with 9,207/792 estimated metadata overhead. The old successful three-result routing flow totaled 18,549 estimated result tokens; the new direct core call was 5,710. The old handoff produced an error and its error payload was not estimated. Identical core replay sends no excerpts, and current usage records permit overlap accounting. These were **candidate local payload improvements only**; later real results are documented separately, and no real token saving is claimed.

## Current Boundary

The Lab remains locked through Phase 10 and Gateway through Phase 19. Task A v2 has a frozen valid FAIL/FAIL pair. The first v3 pair is invalid because baseline began dirty; later frozen-corpus v3 pairs are infrastructure-valid but FAIL/FAIL. Phase 22.6 is local-only; no new real Codex pair has run since the Phase 22.5 budget-control changes. Claude/provider adapters, external LLM summarization, and Phase 23+ are not implemented.

## Phase 22.2: Local Selection and Versioned Evaluation

`RelevanceEngine` now emits immutable `MatchSignal` records alongside human-readable reasons and matched query terms. Query terms that occur in much of the indexed metadata are filtered, graph boosts are capped per relationship kind, and verified source-text hints are limited to two terms per candidate. Lexical-family matching requires a six-character common prefix and at least 70% of the shorter term; it is weaker than exact path, filename, or symbol evidence. The verified read participates in the existing stale-source retry.

`ContextBuilder` considers a wider candidate pool but keeps the requested source budget. It proposes and merges atomic ranges as before, then selects required ranges, novel strong evidence per estimated cost, and finally deeper relevant context. Connected strong source anchors, one directly related proving test per anchor, and bounded direct import/importer support determine task-cluster affinity. Out-of-cluster source does not consume the depth budget. Complete symbols, source hashes, redaction, and required-over-budget warnings remain intact. `selection_diagnostics` on the immutable pack reports candidate-level ranges, costs, signals, budget state, and omission reasons. The MCP Codex-core response does not serialize diagnostics; it remains the same five-tool profile and one-call fresh-work route.

Benchmark-only `preemption-v3` retains the v2 engineering prompt and JSON fields, but uses evaluator version 3. It compares complete identifier segments and normalized test-path segments rather than substring or v2 exact-string equality. V1/v2 artifacts are immutable and cannot be aggregated with v3. Benchmark-only required-source units measure file and identifier recall plus fixture-based required/non-required selected-source estimates; these do not influence production ranking. The local BALANCED/6000 Task A check reached 7/7 required files and identifiers on a frozen committed-source snapshot. Authentication callback, queue cancellation, upload validation, and prior Phase 15 quality fixtures remain green. This is local evidence only, not a new Codex A/B result.

The historical Task A v2 pair was infrastructure-valid on both sides but **FAIL/FAIL** under its exact structured evaluator, which rejected qualified/composite identifiers. Baseline/optimized Codex input was **84,350 / 122,094** tokens: no real token savings. Optimized made one `middleman_context` call with zero repeated MCP source, but the pack omitted critical implementation source and six native fallback reads followed. V2 artifacts remain frozen.

## Phase 22.3: Stable Corpus and Query Diagnostics

Task A v1/v2/v3 task definitions now reference immutable Lab commit `284c4451ad9213f4f27f6d534eac8be2484c2f9a`. `tasks.py` verifies the exact object is a commit, materializes its tree with `git ls-tree`/`git show`, and never substitutes moving HEAD. This commit contains the seven evaluator-only preemption areas but predates Gateway, MCP, and benchmark machinery. Baseline and optimized source trees are byte-identical except optimized's added `AGENTS.md`; each is initialized and committed independently so both begin Git-clean. No primary checkout or branch change is involved.

`run_one()` is the sole repository-owned real Codex launcher. It checks the source fingerprint and Git porcelain status before constructing the invocation and checks status again immediately before spawning. A dirty baseline or optimized snapshot raises an infrastructure error and never reaches the process launcher. The authorized v3 run bypassed `run_one()` through a one-off recorder: it copied a snapshot containing tracked `AGENTS.md`, deleted that file on baseline, and invoked Codex despite the resulting ` D AGENTS.md`. Both calls finished before that clean-start violation was recognized. The historical v3 artifacts remain untouched and **INVALID_PAIR / diagnostic only**.

The optimized v3 answer passed its structured gate, but its Context Pack contained **0/7** benchmark-required areas; eight native source reads supplied the missing evidence. No context-quality or token-saving conclusion follows. Its historical usage entry has only query signature `2adb2f9fda5f05e1e4b5e4a641c283d24a24693911c16fb9dd3d0610a58dc05b`; the exact query text was not recorded and cannot be reconstructed. The moving-HEAD corpus and unobserved query reformulation were uncontrolled, plausible contributors, not individually proven historical causes.

The snapshot-scoped current MCP server receives explicit benchmark identity via `mcp serve` arguments. Only those launches emit source-free query and selection receipts under the snapshot cache: normalized redacted terms/identifiers, explicit arguments, query signature, source commit/fingerprint, selector/server fingerprints, candidate scores, selected/omitted paths, ranges, costs, and pack fingerprint. Phase 22.4 also permits a bounded redacted task string in these explicit benchmark receipts. Ordinary `mcp_usage.jsonl` stays metadata-only, with no raw prompts or source text. The production selector never consumes benchmark-required paths or identifiers. Codex-core tool guidance asks for a concrete engineering request; it does not force a verbatim prompt or alter ranking.

On the pinned corpus, local direct `ContextBuilder`, direct `MCPGateway.context`, and fresh stdio `middleman_context` calls (default and explicit BALANCED/6000 arguments) produce identical fingerprints, selected paths/ranges/text, warnings, source fingerprints, and 7/7 file/identifier recall. The pinned-corpus Phase 22.1 selector yields 4/7 files and identifiers at 4,693 selected tokens; Phase 22.2 yields 7/7 at 5,891. These are local heuristic context estimates only. See [Codex benchmarks](CODEX_BENCHMARKS.md) for query sensitivity and current-HEAD contamination counts.

## Phase 22.4: Local Coverage Repair

After required, novel-coverage, and depth allocation, `selection.allocate` makes one bounded deterministic repair attempt. It considers up to 12 omitted, in-cluster ranges with stronger uncovered term evidence or graph-supported high-confidence lexical-family evidence for a weakly represented concept. Weak-only repair stays in the anchored source package. Eviction is limited to at most two non-required, non-anchor depth ranges, protects mandatory tests and sole strong term evidence, and never grows the requested source budget. The accepted swap and before/after coverage strengths are recorded in source-free diagnostics, omitted from Codex-core.

On the pinned Lab corpus, a **receipt-derived query fixture** reconstructed from normalized valid-v3 receipt terms (not the unavailable exact raw query) moved from 6/7 files and identifiers at 5,960 estimated selected tokens to 7/7 at 5,952 by replacing `runner.py` (557) with `scheduler.py` (549). Exact prompt remains 7/7 at 5,891; behavior, reordered, and agent-style variants reach 7/7 at 5,475, 5,544, and 5,693. The short query gives 5/7 files and 3/7 identifiers at 3,521; the generic query gives 0/7 at 1,126. Three unrelated bounded allocator cases (auth, queue, upload) trigger the same one-way repair. These are local heuristics and not real Codex outcomes.

Codex-core still has five tools (currently 851 estimated definition tokens). Each excerpt adds a `complete_file` boolean; on the receipt-derived 16-excerpt pack this changes the compact JSON result estimate from 6,910 to 6,996 (+86), while selected source remains 5,952. `DeliveryLedger` still stores only path/hash/line metadata; duplicate context returns no source and full-file expansion after a partial excerpt sends only unseen lines. Guidance prefers expansion before a whole-file reread, while preserving native reads for exact/stale source and editing. Explicit benchmark receipts alone may store a bounded `redacted_task`; ordinary usage logs remain prompt-free. Benchmark run IDs are generated uniquely or passed explicitly from the suite, never inferred from a generic artifact directory name. No external Codex call was made in Phase 22.4.

## Phase 22.5: Benchmark Budget and Delivery Audit

`BenchmarkIdentity` carries a validated `BenchmarkPolicy` (initial context 6,000, expansion ceiling 12,000 by default). The benchmark harness passes both values explicitly to its snapshot-scoped server. Only benchmark-mode `middleman_context` calls normalize a valid requested budget to `min(requested, initial cap)` before building; a second context call is still capped. Normal sessions retain the 12,000 maximum. Explicit expansion uses its separate ceiling, so the cumulative canonical pack can grow beyond the initial cap. Benchmark receipts and compact core responses expose requested/effective/cap values; ordinary usage entries retain source-free budget metadata. The future runner invalidates an optimized run if a successful initial context has missing, mismatched, or over-cap effective-budget evidence. Requested values above the cap are valid when normalized.

The latest real Task A v3 pair remained infrastructure-valid but failed both structured answers (recomputation and output preservation). Its initial requests were 9,000 and 11,000, not the intended fixed 6,000. The first larger pack had 7/7 required file/identifier recall with no repair; those facts do not validate the 6,000-budget experiment. The second historical query signature reconstructs only with `force_replay=True`, which deliberately resends previously delivered lines. Local pinned-corpus tests reproduce repeated delivery with that flag and zero repeated delivery without it across different fingerprints in one Gateway instance. No persistent cross-process delivery state or selector retuning was added. Future reports expose all server session IDs and classify native-read paths as absent, partial, or complete in MCP delivery. Historical artifacts and the Task A v3 correctness evaluator are unchanged; no external run or token-saving claim resulted from Phase 22.5.

## Phase 22.6: Codex-core Tool-Surface Hardening

The five-tool Codex-core `middleman_context` schema no longer includes `force_replay` or a replacement replay argument. The direct `MCPGateway.context(..., force_replay=True)` path remains for internal diagnostics. Future optimized benchmark validity checks reject successful `middleman_context` usage records with replay enabled, even if produced outside the normal model-facing schema. Same-task expansion guidance and new-task context calls remain unchanged. The official local stdio MCP surface measures 824 heuristic definition tokens (851 before this change).

On the pinned Task A corpus, a single stdio server served the recorded first and second queries at requested/effective budgets 9,000/6,000 and 11,000/6,000. The first pack retained 7/7 required file and identifier recall at 5,891 selected tokens. Different pack fingerprints selected 176 identical source lines, but the delivery log measured zero repeated bytes across both contexts and two explicit expansions. A complete `preemption.py` reselection sent no source for that file; partial overlap in `engine.py` delivered only new lines. The same session ID and call sequences 1-4 appeared in metadata, with increasing ledger counts. Historical artifacts, relevance ranking, coverage repair, pinned corpus, and Task A v3 evaluator were not changed; this local result is not a new external benchmark or token-saving claim.
