# Middle_Man Architecture

This document describes the implemented Lab through Phase 8. The existing Phase 1-4 request, clock, scheduler, allocator, runner, and CLI remain the foundation.

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

## Verification Boundary

The suite retains all 36 hardened Phase 1-4 tests and adds Phase 5-8 unit and engine integration coverage for admission order, measurements, memory pressure, recomputation, deterministic traces, prefix reuse, partial blocks, reference counts, and prefix/preemption interaction.

Phase 9 benchmarks and visualization are future work. Agent Gateway, repository indexing, MCP, Codex and Claude integrations, provider APIs, and real PyTorch execution are not implemented.