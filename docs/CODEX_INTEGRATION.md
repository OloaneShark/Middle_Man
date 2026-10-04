# Production Codex Runner

`middle-man codex run` is the user-facing preparation path for a real repository and an arbitrary user task. In this phase it is **dry-run only**: there is no live Codex launcher or confirmation flag. `codex --version`, `codex --help`, and `codex exec --help` are inspected locally; no model inference runs.

```bash
middle-man codex run --repo . --read-only --dry-run "Explain how preemption works"
middle-man codex run --repo . --workspace-write --dry-run "Fix the scheduler bug and run tests"
```

Quote the positional task as one shell argument. Exactly one of `--read-only` and `--workspace-write` is required. `--dry-run` is required until a later, separately authorized live phase. `--model` defaults to `gpt-6-sol`; `--effort` defaults to `high` and accepts `low`, `medium`, `high`, or `xhigh`. `--json` emits a source-free local audit. No benchmark `TaskSpec` or frozen snapshot is involved.

The runner validates that `--repo` is a Git repository root, reads the existing BALANCED/6000 context selection, builds the existing source-free offline locator, and applies the locked AUTO decision. It disables index-cache writes and checks Git-visible file contents and porcelain state before and after preprocessing. For a read-only task, AUTO appends the locator only when candidate source is at least 10,000 heuristic tokens and selected paths exist. Otherwise it bypasses. Every workspace-write task bypasses, even when the candidate estimate crosses the threshold. A bypass leaves the UTF-8 task bytes unchanged; a used locator appends only the existing locator wrapper. There are no generated `AGENTS.md` files, MCP registrations, Context Pack source excerpts, benchmark footers, or offline edit anchors in this path. Codex itself may still see repository-authored guidance already present in a real repository; Middle_Man does not create or modify it.

The dry-run prints a redacted command shape, not the prompt. Its in-memory audit contains the repository root, SHA-256 task hash, UTF-8 task length, mode, CLI identity, model/effort, candidate/selected estimates, AUTO decision and reason, locator estimate/hash when used, selected paths, selector fingerprint, model-visible Middle_Man estimate, and `external_calls=0`. It does not persist the task, prompt, source excerpts, or audit by default. The heuristic estimates are not Codex-reported usage or billing tokens.

Installed Codex CLI `0.155.0-alpha.16.3` documents `--no-daemon`, `--ask-for-approval`, `--strict-config`, and the `exec` options `--ignore-user-config`, `-C`, `-s read-only|workspace-write`, `--ephemeral`, `-m`, and `-c`. The preview uses those flags and the established `model_reasoning_effort` config key. It contains no MCP configuration. Windows sandbox implementation behavior and actual live execution are **not** validated by this dry-run; enabling inference requires a separate phase and explicit authorization.

## Research Harness

`middle-man codex benchmark ...` remains the separate Phase 22 A/B system. It creates frozen disposable snapshots, versioned tasks and evaluators, and sanitized research artifacts. Its benchmark-only prompt footer and optional MCP/anchor modes do not enter `codex run`. Historical results and limitations remain in [Codex benchmarks](CODEX_BENCHMARKS.md).
