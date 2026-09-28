# Middle_Man

Standing between the request and the model.

Middle_Man Lab implements Phases 1-10: a deterministic LLM serving simulator with token-budgeted scheduling, continuous batching, physical KV blocks, structured metrics, preemption, prefix caching, workloads, benchmarks, inspection traces, and optional plots. The separate Agent Gateway foundation implements Phases 11-14: local repository indexing, incremental caching, and explainable relevance search. Neither subsystem requires a model, GPU, PyTorch, or provider API.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
python -m middle_man simulate
```

On macOS or Linux, activate with `source .venv/bin/activate`. The installed `middle-man` command works when Python's Scripts directory is on `PATH`.

## Simulate and Inspect

```bash
python -m middle_man simulate --requests 2 --prompt-tokens 20 --output-tokens 1 --token-budget 4 --kv-blocks 16
python -m middle_man simulate --requests 2 --prompt-tokens 2 --output-tokens 3 --token-budget 2 --kv-blocks 3 --tokens-per-block 2 --preemption
python -m middle_man simulate --requests 1 --prompt-tokens 5 --output-tokens 1 --token-budget 2 --debug --trace-json benchmark_results/trace.json
```

`--debug` prints a readable timeline of admissions, prefill progress, decode, recomputation, memory changes, preemption, cache events, and completion. `--trace-json` saves the underlying immutable events. `EngineResult.metrics` and `EngineResult.events` remain available to Python callers.

## Benchmarks

Middle_Man Lab benchmarks use a deterministic simulation cost model. They compare scheduling and memory-management strategies *inside Middle_Man*; they are **not measurements of real GPU inference performance**.

```bash
python -m middle_man benchmark --list
python -m middle_man benchmark mixed
python -m middle_man benchmark scheduler-comparison
python -m middle_man benchmark prefix-cache --seed 7 --json --csv
python -m middle_man benchmark memory-pressure
python -m middle_man benchmark token-budget
python -m middle_man benchmark active-sequences
python -m middle_man benchmark chunked-prefill
```

Available workload presets are `short-chat`, `mixed-chat`, `long-context`, `burst-traffic`, `memory-pressure`, `prefix-heavy`, and `scheduler-mixed`. Each benchmark case creates fresh requests, a fresh clock, and fresh KV memory from immutable request specifications. A local seed controls generated variation; no global random state is changed.

Comparisons report measured deltas without declaring an automatic winner. Constrained memory without preemption is recorded as an expected failure when it cannot complete. Chunked prefill is compared across token budgets; no fake on/off switch is provided.

JSON and CSV files are written to `benchmark_results/` by default, which is Git-ignored. Override with `--output-dir`. The files include version, UTC timestamp, workload, seed, configuration, measured simulated metrics, and an explicit simulation marker.

The API is also usable without the CLI:

```python
from middle_man.lab.suites import build_suite

results = build_suite("prefix-cache", seed=7).run()
for case in results.cases:
    print(case.case_name, case.metrics.aggregate if case.metrics else case.failure)
```

## Optional Plots

```bash
pip install -e ".[dev,viz]"
python -m middle_man benchmark scheduler-comparison --plot
```

Plots are saved headlessly under `benchmark_results/` or `--output-dir`: an event-based request timeline, sampled KV utilization, TTFT distribution, and a throughput comparison when multiple cases succeed. Plots use only observed simulator events and metrics and are labeled **SIMULATED**. Matplotlib is not needed for simulation or benchmark reporting.

## Agent Gateway (Local)

The Gateway answers which repository files and symbols are relevant to a task. It does not yet package source snippets or send context to an agent. Python is parsed with the standard-library AST; other recognized text languages are represented accurately without claiming deep syntax parsing. File imports, test-to-source edges, symbol locations, Git state, and path/name matches inform ranking.

```bash
python -m middle_man index --repo .
python -m middle_man inspect --repo .
python -m middle_man context find "KV preemption" --repo .
python -m middle_man context find "SimulationEngine" --repo . --top-k 5
python -m middle_man cache status --repo .
python -m middle_man cache rebuild --repo .
python -m middle_man cache clear --repo .
```

The first scan writes a versioned JSON index to `.middle_man_cache/index.json`. Later scans hash file bytes and reuse parsed records with unchanged hashes. Changed and new files are parsed; deleted files and their relationships disappear. Cache corruption or schema/configuration mismatch triggers a rebuild. `cache clear` removes only the index file. Source files remain the source of truth; the cache stores metadata, symbols, and imports, not full source copies.

Default exclusions include `.git`, virtual environments, dependency/build/cache directories, `.env*`, private keys, and common secret-bearing filenames. Root `.gitignore` and `.middlemanignore` are supported with a conservative glob subset: patterns, directory patterns, and negation in order; `.middlemanignore` is applied after `.gitignore`. This is not full Git ignore semantics. Oversized files remain in the map with an `oversized` status but are not parsed. Filename filtering is only a safety foundation, not complete secret detection.

The search API returns ranked PRIMARY and RELATED files with explicit scoring reasons. It uses exact paths/symbols, normalized filename/symbol/import terms, one-hop import and test links, trace paths, and a modest changed-file boost only for already relevant files. It never calls an AI model or network API.

## Scope

Context Packs (Phase 15), MCP, Codex and Claude integrations, provider APIs, secret-value redaction, and real model execution are not implemented. The project makes no claim about provider token savings.