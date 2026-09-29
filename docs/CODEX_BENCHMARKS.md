# Real Codex A/B Context Benchmark

Phase 22 measures whether Middle_Man changes Codex's repository exploration **without lowering correctness**. It is separate from simulated Lab benchmarks and local Context Pack quality fixtures. It does not measure plan quota or billing.

## Run It

```powershell
.venv\Scripts\python.exe -m middle_man codex benchmark list
.venv\Scripts\python.exe -m middle_man codex benchmark run-all --repo . --dry-run
.venv\Scripts\python.exe -m middle_man codex benchmark run-all --repo . --confirm-external-service
.venv\Scripts\python.exe -m middle_man codex benchmark report <run-id> --repo .
.venv\Scripts\python.exe -m middle_man codex benchmark report <run-id> --repo . --json
.venv\Scripts\python.exe -m middle_man codex benchmark overlap <run-id> --repo .
```

Live runs send repository-derived context to Codex's external service and require the explicit confirmation flag. Normal pytest and `--dry-run` never call Codex. The default invocation explicitly requests `gpt-6-sol` with high reasoning effort; the selected model/effort remain marked **not event-verified** unless a Codex event reports them. `codex exec --json` is the documented structured event surface, including `turn.completed.usage`: [OpenAI Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Per-run `--ignore-user-config` is also documented there.

## Isolation and Tasks

Each task gets two independently committed working copies in a fresh system-temp directory, outside this repository's ancestor `AGENTS.md` scope. Sanitized reports live under Git-ignored `.middle_man_cache/codex_benchmarks/<run-id>/`; temp working copies are retained for inspection. The source files have a common SHA-256 fingerprint, excluding only the intentional `AGENTS.md` routing difference. The architecture task uses `git show HEAD` from committed Middle_Man, never uncommitted Phase 22 code. Edit tasks use deterministic standalone fixtures.

Baseline has no project `AGENTS.md` and launches Codex with `--ignore-user-config`, so it should explore natively. Optimized has the normal Middle_Man `AGENTS.md` and explicitly configures a snapshot-scoped local MCP command. Both sides use the same task prompt, Codex version, model, reasoning effort, sandbox, timeout, and default network policy. Run order alternates: A baseline/optimized, B optimized/baseline, C baseline/optimized. A baseline MCP call invalidates the pair. An optimized run without snapshot-scoped Middle_Man usage records also invalidates it. The runner stops after an infrastructure-invalid pair.

- **A, preemption:** Read-only explanation of victim selection, memory release, recomputation, and output retention from the committed Middle_Man snapshot. Required factual markers and a clean Git status gate correctness.
- **B, OAuth expiry:** A fixture callback accepts expired state. Visible tests fail initially; hidden boundary/replay/skew tests run after each Codex attempt. Production and tests must be updated.
- **C, uploads:** Add a configurable, case-insensitive filename-extension allowlist across configuration, shared validation, service, and tests. Hidden behavior tests check allowed, rejected, custom, size-limit, and duplicate cases.

For edit tasks, deterministic tests and requested-file changes gate correctness. A lower-read optimized run is **not** a win if it fails behavior tests. No composite score is used. Git status is captured before and immediately after Codex; evaluator tests are added only afterward.

## Measurements

The parser counts completed Codex JSONL command and MCP events, recognizes explicit native read commands and search/listing/Git inspections, and records unique explicit file paths and rereads where observable. Shell syntax, failed commands, and hidden tool activity can limit this count; missing observations are not guessed. `turn.completed.usage` supplies Codex-reported input, cached-input, output, and reasoning-output tokens when present. A direct total-token field remains `null` if absent. Cached input is not added to input again.

For every Context Pack, the local metadata log stores pack fingerprint, candidate/selected source estimates, result estimate, and sanitized excerpt path/content-hash/line ranges with per-line byte lengths, **not source text**. Across packs, `(path, content hash, line number)` identifies the same delivered source line. First delivery counts toward unique bytes; every later delivery counts toward repeated bytes. Overlap ratio is `repeated / (unique + repeated)` bytes. Estimated tokens use `ceil(UTF-8 bytes / 4)`. The non-source pack overhead estimate is `sum(pack result token estimates) - sum(selected source token estimates)`; it includes JSON/result wrappers and metadata, so it is not an exact provider-token charge. The unique-source delivery ratio is estimated unique source tokens divided by estimated Context Pack result tokens. These are Middle_Man estimates, separate from Codex-reported usage.

## First Attempt: Infrastructure-Invalid

Run `20260928T194542Z-5e9193e1` did **not** yield a valid A/B comparison. Two pairs completed and the third was stopped after its first side to avoid further usage. Codex's Windows command/edit sandbox repeatedly failed during startup with `apply deny-read ACLs`; neither edit task could be evaluated as a successful fix. The installed Codex host also reused the globally registered Middle_Man root despite a per-run arguments override: optimized MCP events occurred, but usage was written against the primary repository rather than the temp snapshot. One baseline used another MCP server. These failures invalidate the pairs; no correctness-preserving context reduction or token-saving claim follows from them.

After this diagnostic attempt, the harness was changed to use documented `--ignore-user-config` with an explicit snapshot-scoped MCP command, and to stop after the first infrastructure-invalid pair. That revised invocation has **not** been validated by a new real Codex run. The Windows sandbox ACL failure still needs resolution before a meaningful three-pair suite. The previous attempt's Codex usage values may be inspected as diagnostics, not compared as benchmark results. No private/undocumented usage or quota API was accessed.

This is a small, task-specific sample even when valid. Agent choices and cached input vary; fixture repositories do not represent every real codebase, and subscription allowance need not map linearly to tokens. Measure repeated payload delivery before considering a separate optimization pass; Phase 22 does not change Context Pack response semantics.
