# Middle_Man

Standing between the request and the model.

Middle_Man currently implements Phases 1-8 of the Lab roadmap: a deterministic LLM serving simulator with token-budgeted scheduling, continuous batching, physical KV blocks, structured metrics, preemption, and prefix caching. Model execution and timing are simulated. No model, GPU, PyTorch, or provider API is required.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
python -m middle_man simulate
```

On macOS or Linux, activate with `source .venv/bin/activate`.

## Simulate

```bash
python -m middle_man simulate --requests 2 --prompt-tokens 20 --output-tokens 1 --token-budget 4 --kv-blocks 16
python -m middle_man simulate --requests 2 --prompt-tokens 2 --output-tokens 3 --token-budget 2 --kv-blocks 3 --tokens-per-block 2 --preemption
python -m middle_man simulate --requests 2 --prompt-tokens 4 --output-tokens 1 --token-budget 4 --kv-blocks 8 --tokens-per-block 2 --prefix-cache --shared-prefix-tokens 4
```

The command prints measurements from the run, including throughput, latency percentiles, peak KV use, preemptions, and prefix reuse. `python -m middle_man` prints help. The installed `middle-man` command works when Python's Scripts directory is on `PATH`.

Requests with different arrival times can enter an active group as capacity opens. The engine schedules work up to a token budget each iteration. When preemption is enabled, allocation pressure can evict another request's KV state; that request later recomputes its context while retaining output already generated. The prefix cache is opt-in and reuses only complete KV blocks. Cached entries are released at the end of each run.

Programmatic callers receive `EngineResult.metrics` and `EngineResult.events`, as well as the existing counters and request objects. See [the architecture document](docs/ARCHITECTURE.md) for exact accounting and ownership rules.

## Scope

Phase 9 benchmarks, visualization, Agent Gateway, repository indexing, MCP, Codex and Claude integrations, and real model execution are not implemented. Simulated throughput is not real GPU throughput. The project makes no claim about provider token savings.