# Middle_Man Architecture

This document describes what exists in the repository after the Phase 1-4 implementation and hardening passes. Later roadmap items from the full Middle_Man specification are intentionally not implemented yet.

Implemented phases:

- Phase 1: project skeleton, typed configuration, deterministic clock, request model
- Phase 2: block-based KV allocator
- Phase 3: scheduler policies, token budgeting, chunked prefill
- Phase 4: simulation engine and simulated model runner

Not implemented in this pass:

- continuous batching as a claimed feature
- metrics framework
- preemption
- prefix caching
- benchmark suites
- visualization
- Agent Gateway
- MCP tools
- Codex or Claude integration

## Package Layout

```text
middle_man/
    __init__.py
    __main__.py
    cli/
        main.py
    lab/
        clock.py
        config.py
        engine.py
        memory.py
        request.py
        runner.py
        scheduler.py
        work.py
tests/
    test_phase_1_core.py
    test_phase_2_memory.py
    test_phase_3_scheduler.py
    test_phase_4_engine_runner.py
```

The current code is focused on Middle_Man Lab. Gateway directories are deliberately absent until their implementation phase begins.

## Phase 1: Core Model

### Configuration

`middle_man.lab.config` contains typed dataclass configuration:

- `LabConfig`
- `RunnerCostConfig`
- `SchedulerKind`

Configuration validation rejects non-positive token budgets, sequence limits, KV block counts, and block sizes. Runner cost values must be non-negative. The reserved preemption and prefix-cache switches default to `False` because those features do not exist yet.

### Clock

`middle_man.lab.clock` defines a `Clock` protocol and two implementations:

- `VirtualClock`: deterministic simulated time used by the engine and tests
- `WallClock`: optional real-time implementation

The engine uses the clock abstraction and does not call `time.time()` directly. An injected clock is allowed to continue forward across separate engine runs.

### Request Model

`middle_man.lab.request` defines `InferenceRequest` and `RequestState`.

A request tracks:

- request ID
- arrival time
- original prompt token count
- processed prompt tokens
- requested output tokens
- generated output tokens
- lifecycle state
- allocated block IDs
- first-token timestamp
- completion timestamp
- future-phase metadata such as preemption counters and prefix fields

The request object enforces local token bounds and lifecycle invariants. It cannot decode before prefill is complete, cannot process more tokens than declared, and cannot resume work after completion.

A request with no prompt enters decoding when admitted if it requests output. A request with no output completes as soon as prefill finishes. If both prompt and output counts are zero, admission completes it immediately. Completion uses the current simulation time supplied by the engine.

## Phase 2: KV Block Allocator

`middle_man.lab.memory.KVBlockManager` models KV memory as fixed-size physical blocks. It does not track only a scalar `memory_used` value.

Example:

```text
request req-1 -> blocks 0, 1, 4
request req-2 -> blocks 2, 3
```

The allocator supports:

- calculating required blocks from token counts
- allocating physical block IDs
- non-contiguous allocation after releases
- per-request block tables
- allocation exhaustion errors
- atomic failure when one allocation request cannot be satisfied
- releasing all blocks for a completed request
- reuse of released blocks
- utilization snapshots

Prefix sharing and preemption-aware release are future phases and are not implemented here.

## Phase 3: Scheduling

`middle_man.lab.work` defines scheduling work items:

- `PREFILL`
- `DECODE`

A `SchedulePlan` validates that scheduled tokens do not exceed the configured budget.

`middle_man.lab.scheduler` provides two policies:

- `DecodePriorityScheduler`: schedules one decode token per decoding request first, then uses the remaining budget for prefill.
- `BalancedScheduler`: gives decode work part of the budget while ensuring prefilling requests still make progress.

Chunked prefill emerges from the token budget. A 20-token prompt with a 4-token budget requires five prefill iterations before decode can begin.

Schedulers do not allocate memory and do not mutate request state. They only produce a plan.

## Phase 4: Engine and Simulated Runner

`middle_man.lab.runner.SimulatedModelRunner` computes deterministic elapsed time for a schedule. It does not load a model, sleep, require PyTorch, or require a GPU.

Execution cost comes from:

- configured prefill base cost
- configured prefill per-token cost
- configured decode base cost
- configured decode per-token cost
- current context length
- a bounded batch discount

`middle_man.lab.engine.SimulationEngine` coordinates the current Lab flow:

```text
requests
   |
   v
admit arrived requests
   |
   v
scheduler plan
   |
   v
KV capacity check/allocation
   |
   v
simulated runner
   |
   v
advance virtual clock
   |
   v
apply request progress
   |
   v
release completed request blocks
```

The engine returns an `EngineResult` with request objects, iteration count, elapsed simulated time, processed prompt tokens, and generated output tokens. Counters in each result describe only that invocation of `run()`; the clock itself is not reset between invocations.

## Current Invariants Covered by Tests

The Phase 1-4 tests verify:

- configuration validation and disabled future-feature defaults
- deterministic clock advancement
- normal and zero-token request lifecycle transitions
- decode-before-prefill rejection
- prompt and output token bounds
- completed requests cannot resume work
- block allocation, release, reuse, and mapping cleanup
- atomic allocation exhaustion
- used blocks never exceed total blocks
- non-contiguous block allocation after release
- capacity checks allocate only missing blocks
- scheduler token-budget enforcement across prefill, decode, and mixed workloads
- engine-level multi-iteration chunked prefill
- decode-priority ordering
- balanced scheduling behavior
- deterministic runner costs
- per-run counter isolation when an engine is reused
- `max_active_sequences` admission limits
- zero-output engine completion without idle loops
- final KV block release
- arrival-time advancement without sleeping
- clean CLI help with no subcommand

## Roadmap Boundary

The full Middle_Man specification remains the roadmap, but this hardening pass still stops at Phase 4. Phase 5 must add continuous batching deliberately, with its own behavior, tests, and documentation, instead of treating incidental engine admission behavior as a finished feature.
