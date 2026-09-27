# Middle_Man

Standing between the request and the model.

Middle_Man is planned as an educational LLM serving simulator and coding-agent context optimization layer. This repository currently implements only Phases 1-4 of the roadmap:

- project skeleton
- typed configuration
- deterministic clock
- request lifecycle model
- block-based KV allocator
- scheduler policies with token budgeting and chunked prefill
- simulation engine
- simulated model runner

Later roadmap items such as continuous batching, preemption, prefix caching, benchmarks, visualization, Agent Gateway, MCP tools, Codex integration, and Claude Code integration are not implemented yet. Configuration flags for preemption and prefix caching default to disabled.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m middle_man simulate
```

On macOS or Linux, activate with `source .venv/bin/activate`.

## Current Lab Flow

```text
requests
   |
   v
admission
   |
   v
scheduler plan
   |
   v
KV block allocation
   |
   v
simulated runner
   |
   v
virtual clock + request updates
```

The simulator uses virtual time. It does not load a model, sleep, require PyTorch, require CUDA, or call an external API.

## CLI

```bash
python -m middle_man
python -m middle_man simulate --requests 8 --token-budget 64 --kv-blocks 128
```

The bare command displays help. The `simulate` command prints actual values from the run: request count, scheduler iterations, elapsed simulated milliseconds, prompt tokens processed, and output tokens generated.

## Honesty About Scope

This is an early implementation slice. Simulated timing is not real GPU performance. No context-token savings or provider usage reductions are claimed by the current code.
