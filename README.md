# Middle_Man

Standing between the request and the model.

Middle_Man Lab implements Phases 1-10: a deterministic LLM serving simulator with token-budgeted scheduling, continuous batching, physical KV blocks, structured metrics, preemption, prefix caching, workloads, benchmarks, inspection traces, and optional plots. The separate Agent Gateway implements Phases 11-19: local repository indexing, incremental caching, explainable relevance search, Context Packs, Git diff-aware context, deterministic output compaction, factual Project Memory, and Session Handoff. Phases 20-21 add an optional local MCP server and Codex setup. No Middle_Man subsystem requires a model, GPU, PyTorch, or provider API.

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

The Gateway answers which repository files and symbols are relevant to a task and can assemble local, source-verified Context Packs. It does not send context to an agent. Python is parsed with the standard-library AST; other recognized text languages are represented accurately without claiming deep syntax parsing. File imports, test-to-source edges, symbol locations, Git state, and path/name matches inform ranking.

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

## Context Packs

```bash
python -m middle_man context pack "KV preemption memory pressure" --repo . --mode safe --max-tokens 8000
python -m middle_man context pack "SimulationEngine.run" --mode balanced --json benchmark_results/engine-pack.json
python -m middle_man context pack "prefix cache reference counting" --mode aggressive --output benchmark_results/prefix-pack.md
python -m middle_man context benchmark
```

`ContextBuilder` returns an immutable, structured `ContextPack`; formatting and JSON export are separate. SAFE (default) keeps more surrounding source, BALANCED narrows margins, and AGGRESSIVE keeps minimal margins and warns that context was reduced. Complete indexed Python symbols remain atomic when possible. Imports, parent class lines, referenced constants, related tests, and one-hop dependencies can accompany them. Small relevant files may be included whole. Ranges merge to avoid duplicate source. `builder.expand(pack, ExpansionRequest("full_file", "path.py"))` returns a new generation without modifying the old pack. File, symbol, related-import/test, next-candidate, and surrounding-line expansion are also available.

Each source read is confined to the repository, respects indexing/size/ignore rules, and verifies the current SHA-256 against the index. A source change during selection triggers one fresh index/selection attempt; a second race raises a clear stale-source error. The deterministic pack fingerprint covers the task, selected content hashes and ranges, mode, budget, and generation, but not timestamps or unrelated changed paths.

**Estimated context tokens** use `ceil(UTF-8 bytes / 4)` on source text, not rendered headings. The raw baseline is the complete current text of relevance candidates considered, not the entire repository. Metrics report candidate/selected bytes and estimated tokens, files/excerpts/lines, overlap avoided, and estimated reduction. Required exact context can exceed the budget with a warning; lower-priority context is omitted first. These estimates are **not provider billing tokens or Codex plan usage**.

Phase 22.2 adds frequency-aware terms and a coverage/cost allocator. Phase 22.3 pins Task A to immutable Lab commit `284c4451ad9213f4f27f6d534eac8be2484c2f9a` and enforces clean snapshots. Phase 22.4 adds bounded coverage repair, a core `complete_file` hint, and benchmark-only redacted task receipts. Local exact-prompt and receipt-derived checks reach 7/7 required files and identifiers, but short and generic queries remain weaker. These local results do **not** establish a real Codex token saving or answer-quality improvement.

## Git Changes and Output

```bash
python -m middle_man diff --repo .
python -m middle_man compact pytest tests-output.txt --max-tokens 1000
python -m middle_man compact docker docker.log --json benchmark_results/docker-compact.json
python -m middle_man compact git-diff --repo .
# Pipe stdin when no file is given:
python -m pytest -vv | python -m middle_man compact pytest
```

`GitDiffReader` combines staged and unstaged working-tree changes, records untracked paths, renames, deletions and binary changes, and maps changed Python hunk lines to their enclosing indexed symbols. Non-Git directories degrade gracefully. Diff paths boost only otherwise relevant files; unchanged dependencies and tests remain eligible.

`OutputCompactor` supports pytest, generic logs, Docker/Compose logs, Git status, and structured Git diffs. It condenses passing pytest lines and consecutive exact duplicate lines, preserves failure traces and changed paths, and marks any low-priority omissions. A too-small budget reports that required output exceeds it. Result models contain compacted text, lengths, counts, estimated tokens, warnings, and a fingerprint, but no full raw log copy.

Source excerpts and compacted output are sanitized before formatting or JSON export. The local redactor covers high-confidence assigned secrets, bearer tokens, credential URLs, and complete PEM private-key blocks; it reports categories without values. This is a best-effort safety layer, not a guarantee that every secret pattern is detected. The persistent index still contains no source copies. Local context-efficiency fixtures measure required file/symbol recall alongside estimated reduction; they make no claim about real agent usage.

## Project Memory

```bash
python -m middle_man memory refresh --repo .
python -m middle_man memory show --repo .
python -m middle_man memory status --repo .
python -m middle_man memory decision add "Keep Lab independent" --repo .
python -m middle_man memory decision list --repo .
python -m middle_man memory decision remove <id> --repo .
python -m middle_man memory issue add "Known local issue" --repo .
python -m middle_man memory issue list --repo .
python -m middle_man memory issue resolve <id> --repo .
```

Project Memory is **not AI-generated long-term memory**. Its derived facts come from the current repository index and Git diff: language counts, technologies with evidence paths and hashes, bounded important components/symbols, branch/HEAD, and changed files/affected symbols. Technology detection uses manifests, known configuration files, and observed imports; it is conservative and may omit a technology when evidence is insufficient. Decisions and issues are explicitly user supplied and labeled as such, never inferred from code. Refresh recomputes derived facts, preserves valid user notes and resolved issue state, and changes the timestamp-free fingerprint when meaningful state changes. Invalid/corrupt memory fails clearly without overwriting potentially recoverable user notes.

The versioned, atomic `.middle_man_cache/project_memory.json` stores compact metadata, not full source, diffs, Context Pack excerpts, or logs. User notes are sanitized with the existing best-effort `SecretRedactor` *before* persistence; redaction categories, not original values, are recorded. Default limits are 20 components and 40 symbols (configurable through `MemorySettings`). Size is reported in serialized bytes and heuristic estimated tokens.

## Session Handoff

```bash
python -m middle_man handoff create --task "Investigate login" --pytest-output pytest-output.txt --next-step "Check expired state" --repo .
python -m middle_man handoff create --task "Investigate login" --pytest-stdin --repo .
python -m middle_man handoff create --task "Investigate login" --context-pack benchmark_results/login-pack.json --tool-output build.log --issue "Known failure" --repo .
python -m middle_man handoff latest --repo .
python -m middle_man handoff list --repo .
python -m middle_man handoff show <fingerprint-or-unique-prefix> --json --repo .
```

A handoff requires an **explicit task**. It does not infer developer intent, test outcomes, unresolved bugs, or next steps from filenames. It records current Git changes and affected symbols, a refreshed Project Memory fingerprint, optional Context Pack metadata (never excerpts), actual supplied output compacted through Phase 17, explicit issues and next steps, and hashes of referenced files. Pytest stdin is read only with `--pytest-stdin`. Unresolved Project Memory issues may be carried into a handoff, but resolved issues are not. All free-form input is redacted before storage.

Handoffs are immutable versioned JSON records under `.middle_man_cache/handoffs/`, with a safe latest-ID pointer. Old records are retained. Reading compares branch, HEAD, referenced file hashes/existence, and Project Memory fingerprint; stale records remain readable and show `BRANCH_CHANGED`, `HEAD_CHANGED`, `FILE_CHANGED`, `FILE_REMOVED`, and/or `PROJECT_MEMORY_CHANGED`. Handoff size and the local reconstruction estimate use `ceil(UTF-8 bytes / 4)`. The baseline is the full current text of deduplicated changed/selected readable files plus raw **supplied** tool output. This is a local estimated context comparison, not provider billing or plan usage; a negative difference means the handoff is larger than that baseline. A configurable soft limit warns without truncating facts.

## MCP and Codex

Install the optional SDK and run the local stdio server for one repository:

```bash
pip install -e ".[mcp]"
python -m middle_man mcp serve --repo .
```

The default `codex-core` server exposes five bounded, read-only tools. A fresh scoped task can call `middleman_context` for redacted source; each excerpt marks whether it is a complete file. For missing detail on the same task, prefer `middleman_expand_context`; a materially new selection may need another context call. Same-session calls suppress already delivered lines even across different Context Pack fingerprints. `force_replay` remains available only through the internal Python Gateway for explicit diagnostics, not in the Codex-core MCP tool schema. Native reads remain valid for exact or stale source and editing. Use `--tool-profile full` for the original ten-tool diagnostic surface. This command speaks MCP on stdout; use it through an MCP client rather than as an interactive shell command. Codex registration, verification, fallback behavior, and usage accounting are in [docs/CODEX_SETUP.md](docs/CODEX_SETUP.md). The root [AGENTS.md](AGENTS.md) gives Codex short repository-specific guidance.

```bash
python -m middle_man mcp usage --repo . --json
```

Local usage records contain only metadata, input hashes, and sanitized excerpt range/size identity for benchmark overlap analysis, never source text. They also record a per-Gateway session ID, call sequence, ledger line counts, and requested/effective budgets. Normal sessions retain the 12,000-token context maximum; explicitly identified benchmark sessions cap each initial `middleman_context` build at 6,000 while explicit expansion may grow to 12,000. Reported token sizes are heuristic context estimates, not Codex plan usage or provider billing. Neither the server nor the Gateway sends repository content to an external service on its own.

## Real Codex Benchmark

Phase 22 adds an isolated, correctness-first A/B harness with versioned Task A and two edit fixtures. Task A now uses a fixed pre-Gateway Lab commit rather than moving HEAD; the OAuth and upload fixtures remain separate. Live runs require an explicit external-service confirmation; normal tests and dry runs do not call Codex.

```bash
python -m middle_man codex benchmark list
python -m middle_man codex benchmark run-all --repo . --dry-run
python scripts/measure_phase22_1.py  # local-only heuristic measurement
```

An early suite attempt was infrastructure-invalid. The first **infrastructure-valid** Task A v1 pair was **FAIL/FAIL**; the valid v2 pair was also **FAIL/FAIL** with higher optimized input. The first v3 pair is **diagnostic only / invalid** because baseline began dirty (` D AGENTS.md`). A later frozen-corpus v3 pair was infrastructure-valid but **FAIL/FAIL** (`TASK_FAILURE`): baseline/optimized input was 88,815/88,159, the optimized pack delivered 6/7 required areas, and four native fallback reads followed. The near-equal input counts and failed correctness do not establish a Middle_Man win. Historical artifacts remain frozen. Methodology is in [docs/CODEX_BENCHMARKS.md](docs/CODEX_BENCHMARKS.md).

The latest real frozen-corpus Task A v3 pair was also infrastructure-valid but **TASK_FAILURE** on both sides: recomputation and output preservation failed. Its optimized agent requested 9,000 then 11,000 initial-context tokens, so it did **not** execute the intended fixed-6,000 condition. The first larger pack covered 7/7 required files and identifiers without repair. Phase 22.5 now enforces the benchmark cap server-side and records session/delivery diagnostics, but has run **no new external pair**. Lower optimized input in that one failed, protocol-deviating pair is not a token-saving claim; details are in [docs/CODEX_BENCHMARKS.md](docs/CODEX_BENCHMARKS.md).

Phase 22.6 removes model-facing replay from Codex-core and rejects replay-enabled context usage in future optimized benchmarks. Local stdio tests confirm the five-tool surface and zero repeated delivery across two distinct pinned-corpus packs plus expansions. This is **not** a new real benchmark or token-saving result.

The latest controlled Task A v3 pair was infrastructure-valid but failed both answers' recomputation and output-preservation fields despite the optimized 6,000-budget pack delivering 7/7 required files and identifiers. Baseline/optimized Codex input was 83,780/186,395, so no token-saving claim follows. Task A v4 is a separate local-only prompt/schema/evaluator contract that specifies the abstraction expected in each structured field; v3 stays frozen. `run-all` now selects v4 for Task A, but no v4 external pair has been run. Its pinned-corpus BALANCED/6000 check reaches 7/7 files and identifiers at 5,983 estimated selected-source tokens with direct/Gateway/stdio parity. See [Codex benchmarks](docs/CODEX_BENCHMARKS.md).

## Scope

Claude integration and provider adapters are not implemented. The local server does not call a model or provider API; the explicit Phase 22 harness invokes the installed Codex CLI. No provider token, billing, or plan-usage savings are claimed.

Historical Task A v2 is frozen: both sides were infrastructure-valid but **FAIL/FAIL** under the exact structured evaluator, which rejected qualified/composite identifiers. Baseline/optimized Codex input was **84,350 / 122,094** tokens, so there was **no real token saving**. Optimized used one `middleman_context` call and resent zero MCP source, but its pack omitted relevant implementation evidence and Codex made six native fallback reads. The old artifacts are not rescored; see [Codex benchmarks](docs/CODEX_BENCHMARKS.md).
