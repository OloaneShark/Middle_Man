# Real Codex A/B Context Benchmark

Phase 22 measures whether Middle_Man changes Codex's repository exploration **without lowering correctness**. Phases 22.1 and 22.2 are local candidate optimization passes; only the earlier Task A v2 pair has been tested against real Codex. It is separate from simulated Lab benchmarks and local Context Pack quality fixtures. It does not measure plan quota or billing.

## Run It

```powershell
.venv\Scripts\python.exe -m middle_man codex benchmark list
.venv\Scripts\python.exe -m middle_man codex benchmark preflight --repo . --json
.venv\Scripts\python.exe -m middle_man codex benchmark preflight --repo . --windows-sandbox unelevated --snapshot-root "C:\path\outside\Middle_Man" --json
.venv\Scripts\python.exe -m middle_man codex benchmark run-all --repo . --dry-run
.venv\Scripts\python.exe -m middle_man codex benchmark run-all --repo . --confirm-external-service
.venv\Scripts\python.exe -m middle_man codex benchmark report <run-id> --repo .
.venv\Scripts\python.exe -m middle_man codex benchmark report <run-id> --repo . --json
.venv\Scripts\python.exe -m middle_man codex benchmark overlap <run-id> --repo .
```

Live runs send repository-derived context to Codex's external service and require the explicit confirmation flag. Normal pytest and `--dry-run` never call Codex. The default invocation explicitly requests `gpt-6-sol` with high reasoning effort; the selected model/effort remain marked **not event-verified** unless a Codex event reports them. `codex exec --json` is the documented structured event surface, including `turn.completed.usage`: [OpenAI Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Per-run `--ignore-user-config` is also documented there.

## Isolation and Tasks

Each task gets two independently committed working copies in a fresh directory under system temp by default, or under an explicitly configured `--snapshot-root` outside this repository. The preflight rejects any snapshot parent that inherits an `AGENTS.md`; a repository-local ignored directory is not a valid baseline location while the root `AGENTS.md` applies. Sanitized reports live under Git-ignored `.middle_man_cache/codex_benchmarks/<run-id>/`; temp working copies are retained for inspection. The source files have a common SHA-256 fingerprint, excluding only the intentional `AGENTS.md` routing difference. The architecture task uses `git show HEAD` from committed Middle_Man, never uncommitted Phase 22 code. Edit tasks use deterministic standalone fixtures.

Baseline has no project `AGENTS.md` and launches Codex with `--ignore-user-config`, so it should explore natively. Optimized has the normal Middle_Man `AGENTS.md` and explicitly configures a snapshot-scoped local MCP command. Both sides use the same task prompt, Codex version, model, reasoning effort, sandbox, timeout, and default network policy. Run order alternates: A baseline/optimized, B optimized/baseline, C baseline/optimized. `run-all` selects A v3, B, and C; A v1/v2 remain individually addressable for historical compatibility and cannot be aggregated with v3. A baseline MCP call invalidates the pair. An optimized run without snapshot-scoped Middle_Man usage records also invalidates it. The runner runs a no-inference infrastructure preflight before any pair, and stops after an infrastructure-invalid pair. Both sides explicitly request the same `windows.sandbox` implementation (`elevated` by default); `unelevated` requires the explicit CLI choice. No danger-full-access or unsandboxed fallback is used. The local preflight checks CLI version, a quoted-space/apostrophe path, baseline invocation isolation, exact optimized MCP config, a real snapshot-scoped stdio MCP call, primary-log non-contamination, sandboxed read, read-only write denial, and workspace-write. Model/effort remain unverified until a real Codex event reports them.

- **A v1, preemption (historical):** Read-only conceptual prompt, but a literal-marker evaluator. Its valid pair remains FAIL/FAIL and is never rescored.
- **A v2, preemption (historical):** Read-only prompt explicitly asks for concrete symbols/components, without revealing expected values. Both sides receive the same `--output-schema` JSON object. Exact structured fields, a nonempty explanation, and unchanged Git state gate correctness.
- **A v3, preemption (future run-all default):** The same engineering prompt and structured fields use evaluator v3, which accepts qualified identifier segments and normalized test paths without substring loopholes. No real v3 pair has run.
- **B, OAuth expiry:** A fixture callback accepts expired state. Visible tests fail initially; hidden boundary/replay/skew tests run after each Codex attempt. Production and tests must be updated.
- **C, uploads:** Add a configurable, case-insensitive filename-extension allowlist across configuration, shared validation, service, and tests. Hidden behavior tests check allowed, rejected, custom, size-limit, and duplicate cases.

For edit tasks, deterministic tests and requested-file changes gate correctness. A lower-read optimized run is **not** a win if it fails behavior tests. No composite score is used. Git status is captured before and immediately after Codex; evaluator tests are added only afterward.

## Measurements

The parser counts completed Codex JSONL command and MCP events, recognizes explicit native read commands and search/listing/Git inspections, and records unique explicit file paths and rereads where observable. Shell syntax, failed commands, and hidden tool activity can limit this count; missing observations are not guessed. `turn.completed.usage` supplies Codex-reported input, cached-input, output, and reasoning-output tokens when present. A direct total-token field remains `null` if absent. Cached input is not added to input again.

For every Context Pack, the local metadata log stores pack fingerprint, candidate/selected source estimates, result estimate, and sanitized excerpt path/content-hash/line ranges with per-line byte lengths, **not source text**. Across packs, `(path, content hash, line number)` identifies the same delivered source line. First delivery counts toward unique bytes; every later delivery counts toward repeated bytes. Overlap ratio is `repeated / (unique + repeated)` bytes. Estimated tokens use `ceil(UTF-8 bytes / 4)`. When delivery ranges are available, non-source overhead is `sum(result estimates) - estimated actually delivered source bytes / 4` (rounded up); it includes JSON/result wrappers and metadata, so it is not an exact provider-token charge. The unique-source delivery ratio is estimated unique source tokens divided by estimated Context Pack result tokens. These are Middle_Man estimates, separate from Codex-reported usage.

## Native Windows Infrastructure Check

On this machine, the installed CLI is `codex-cli 0.155.0-alpha.16.3`. Its `codex doctor --json` reports `sandbox.helpers` failed: elevated provisioning recorded `helper_unknown_error`; the remediation is to repair or reinstall the Codex CLI from an approved distribution. Microsoft Defender interference is a warning, not a proven cause. The explicit elevated preflight fails with `apply deny-read ACLs` even for a repository-local read, so this is not solely a `%TEMP%` path problem. OpenAI recommends elevated native Windows sandbox and documents one-time administrator-approved setup for sandbox users, firewall rules, and logon rights: [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox), [configuration basics](https://learn.chatgpt.com/docs/config-file/config-basic). Do not treat elevated as working until it passes the preflight after repair/setup.

The documented `unelevated` fallback starts, but the original `%TEMP%` location denied access to Python-created disposable files. An explicitly chosen sibling snapshot root outside Middle_Man's `AGENTS.md` ancestry passed the read, read-only-denial, write, and local stdio MCP/root-log checks. The preflight creates children with `Path.mkdir`, matching the benchmark snapshot creation; `TemporaryDirectory` produced a different Windows ACL and was unsuitable here. This is local infrastructure validation, not a valid A/B benchmark result. Use `--windows-sandbox unelevated --snapshot-root <absolute-existing-parent>` only as an explicit choice after reviewing the weaker sandbox boundary.

If neither native sandbox is reliable, [OpenAI's WSL2 guidance](https://learn.chatgpt.com/docs/windows/wsl) is the secondary path. This machine currently lists only the `docker-desktop` WSL distribution, not a development distro. A WSL2 migration would need Linux Codex and Python dependencies, `bubblewrap`, a Linux-path Middle_Man MCP command, Linux Git snapshots, and a repo under the Linux filesystem (recommended over `/mnt/c`), with stdio and root isolation retested. No migration has been made.

## Valid Task A v1 Result

The first infrastructure-valid A/B pair used the v1 prompt/evaluator and explicit Windows `unelevated` sandbox. Both sides were infrastructure-valid and left their snapshots and the primary repository clean. The stored result is **FAIL / FAIL**; neither answer supplied all five literal evaluator markers. The answers may be substantively useful, but historical results are immutable and are not rescored.

| Metric | Baseline | Optimized |
| --- | ---: | ---: |
| Native tool calls | 16 | 12 |
| Explicit file reads (manual sanitized-trace audit) | 9 | 10 |
| Unique files / rereads | 9 / 0 | 10 / 0 |
| Search / listing calls | 6 / 1 | 2 / 0 |
| Middle_Man MCP calls | 0 | 4 |
| Codex-reported input tokens | 144,903 | 391,753 |
| Cached input tokens | 118,656 | 345,600 |
| Output / reasoning-output tokens | 4,041 / 1,891 | 3,576 / 1,825 |
| Elapsed seconds | 92.9 | 95.8 |

The optimized run reduced native calls and search/listing operations, **but increased file reads and Codex input tokens substantially**. Its one Context Pack had candidate/selected estimates of 11,133/5,117. Overlap was unavailable because the historical snapshot imported its own older MCP implementation, which lacked delivery-range records. The old native parser also missed doubled-backslash Windows paths; 9 baseline unique files were recovered by manual trace audit. Neither issue changes the frozen outcome. **No Middle_Man token-saving claim follows.**

An earlier suite attempt was infrastructure-invalid because the elevated Windows sandbox failed with `apply deny-read ACLs`, optimized MCP used the primary repository root, and a baseline called another MCP server. It is diagnostic only, not an A/B result.

## Phase 22.1: Local Candidate Optimization

The benchmark runner now pins the current MCP server implementation with isolated Python and an explicit source root, while serving the historical target snapshot. Usage schema v2 records package version, schema version, a code fingerprint, and source-free delivery ranges. A local SDK subprocess test places an intentionally incompatible `middle_man` package in the target snapshot and confirms that the current server still runs. Optimized future runs use the `codex-core` profile, and results record tool profile plus task/evaluator version. Mixed Task A versions are rejected before a live suite starts.

The default Codex-core profile exposes five tools: `middleman_context`, `middleman_expand_context`, `middleman_session_handoff`, `middleman_compact_output`, and `middleman_project_state`. The full profile preserves all ten preexisting tools. `middleman_context` directly builds a bounded, redacted Context Pack, avoiding a mandatory find-then-pack sequence. Its smaller model-visible representation omits duplicated ranking, hashes, and metrics while preserving the canonical pack and source. Session-local metadata tracks delivered path/hash/line identity; identical requests return an unchanged marker with no source unless `force_replay` is requested, and core expansion returns only new ranges. The ledger stores no raw source. Diagnostic `middleman_find_context` remains in full.

Run the repeatable local measurement without Codex:

```powershell
.venv\Scripts\python.exe scripts\measure_phase22_1.py
```

On the committed Task A v1 source snapshot, using the same BALANCED pack for both representations, the official MCP SDK tool-list estimate was **1,643** tokens for ten full definitions and **835** for five core definitions (49.2% less). The selected source estimate was **4,918** tokens in both responses; fingerprint, source path/ranges/text, warnings, and selected-token metrics matched. Full/core result estimates were **14,125 / 5,710** tokens, with estimated metadata overhead **9,207 / 792** (91.4% less). The old local route's three successful result payloads (project state, find, full pack) totaled **18,549** estimated tokens; the handoff call returned an error and its result size is not included. The new one-call core result was **5,710**. An identical second core request returned zero excerpts (71 estimated response tokens); overlap metadata was available. These values are `ceil(UTF-8 bytes / 4)` heuristics from a fresh temporary snapshot, **not Codex-reported input tokens**. The historical 11,133/5,117 estimates are from a different query/mode/invocation and must not be silently substituted for this simulation.

The optional experimental `codex debug prompt-input` diagnostic was skipped because its offline behavior was not established. No external Codex call was made for Phase 22.1. The authorized Task A v2 pair has since completed; its frozen result and the local Phase 22.2 candidate are documented below.

## Valid Task A v2 Result (Frozen)

Both Task A v2 sides were infrastructure-valid under the explicit Windows unelevated sandbox. The exact v2 structured evaluator marked **baseline FAIL / optimized FAIL**. It rejected qualified or composite identifiers even when they named relevant components; these answers and artifacts remain frozen and are not rescored.

| Metric | Baseline | Optimized |
| --- | ---: | ---: |
| Codex input / cached input tokens | 84,350 / 52,608 | 122,094 / 87,040 |
| Output / reasoning-output tokens | 755 / 210 | 1,209 / 476 |
| Elapsed seconds | 30.116 | 34.328 |
| Native calls / explicit reads / unique files / rereads | 5 / 7 / 7 / 0 | 8 / 6 / 6 / 0 |
| Search / listing calls | 1 / 1 | 1 / 0 |
| Middle_Man MCP calls | 0 | `middleman_context` x1 |

The optimized Context Pack estimated 17,866 candidate, 5,840 selected-source, and 7,015 MCP-result tokens. Unique delivered source was about 5,836 estimated tokens, with **zero repeated source and 0% overlap**; non-source result overhead was about 1,179. Nonetheless it omitted preemption, memory-control, and scheduling implementation evidence. Codex then made **six native fallback reads**. Optimized Codex input was higher, so **there was no real token saving**.

## Phase 22.2: Local Selection Candidate

Phase 22.2 adds structured match signals, conservative bounded-prefix lexical-family matching, frequency-aware query terms, capped graph contributions, verified source-term hints, and a two-pass coverage/depth allocator. Strong connected source anchors and the best directly related proving test receive priority; candidate cost matters, but exact path/symbol evidence remains stronger. Candidate-level diagnostics retain matched terms, symbols, proposed ranges, cost, covered signals, budget state, and omission reason in local/debug records. They are **not included in Codex-core**. The source budget remains 6,000 estimated tokens; the internal candidate pool is wider.

Task A v3 uses the v2-equivalent prompt and the same structured fields, but evaluator version 3 accepts whole qualified identifier segments and normalized test paths without substring matching. It is never aggregated with v1/v2. The seven required source units below are benchmark metadata only and never feed the selector: victim policy, memory controller, block release, scheduling recomputation, work enum, request output state, and proving test.

A local before/after run used the same frozen committed-source snapshot, BALANCED mode, and 6,000-token budget. These are fixture-based `ceil(UTF-8 bytes / 4)` estimates, **not Codex usage**:

| Local measure | Phase 22.1 selector | Phase 22.2 selector |
| --- | ---: | ---: |
| Candidates considered | 10 | 50 |
| Selected source tokens | 5,773 | 5,847 |
| Required file recall | 2/7 | 7/7 |
| Required identifier recall in delivered text | 2/7 | 7/7 |
| Selected required-source tokens | 1,346 | 4,187 |
| Selected non-required-source tokens | 4,427 | 1,660 |

The new pack includes `middle_man/lab/preemption.py`, `memory_control.py`, `memory.py`, `scheduler.py`, `work.py`, `request.py`, and `tests/test_phase_7_preemption.py`. Other selected files are engine, metrics, runner, trace, and events. Budget omissions and out-of-cluster candidates are visible in local diagnostics. Three unrelated bounded fixtures (authentication callback, queue cancellation, upload validation) all retained required files and symbols; Phase 15 quality fixtures remain green. The Codex-core profile remains five tools with an 835-token tool-definition estimate. **No external Codex inference occurred in Phase 22.2, and there is no new real A/B result or token-saving claim.**
