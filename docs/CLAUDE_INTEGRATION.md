# Claude Code Integration (Phase 23)

Phase 23 is local-only. The Claude benchmark command has no inference execution path, even with `--confirm-external-service`. No Claude A/B result or Claude token-saving claim exists.

## Commands

```bash
python -m middle_man claude benchmark list
python -m middle_man claude benchmark preflight
python -m middle_man claude benchmark run preemption-v4 --dry-run --model sonnet
python -m middle_man claude benchmark run large-edit-v1 --dry-run --optimized-mode offline-auto
python -m middle_man claude benchmark report <run-id>
```

`preflight` looks for `claude` on PATH and, if found, calls only `claude --version` and `claude --help`. It records observed flags and the local Windows/shell environment. A missing CLI is reported cleanly; synthetic tests and previews remain usable. The planned non-interactive shape is `claude -p <redacted prompt> --output-format stream-json --verbose --model <configured model> --tools <profile> [--max-turns N]`. Actual command arguments are emitted only when local help confirms all required flags. `--max-turns` has no implicit tiny default. Requested model is recorded; observed model remains unknown until a future real stream reports it. An optional `--setting-sources` argument is forwarded only if local help documents that flag. This is not proof that user memory has been isolated.

The read-only profile whitelists `Read,Glob,Grep`; it does not include Bash or edit tools. The workspace-write profile lists `Read,Glob,Grep,Edit,Write,Bash` under ordinary CLI permissions. Neither profile uses `--dangerously-skip-permissions`. These are CLI tool restrictions, not an OS sandbox; a future live benchmark must validate the installed CLI and its permission behavior independently.

## Offline Pair

The dry-run reuses frozen task definitions and the existing BALANCED/6000 source-free locator and AUTO decision. It creates independent, source-identical, committed, Git-clean disposable snapshots, does local preprocessing against the optimized copy, checks that neither snapshot changed, and removes the copies after the preview. No `.mcp.json` or Middle_Man MCP registration is generated. No source excerpts, selector diagnostics, hidden acceptance tests, or benchmark answers enter the optimized prompt. Baseline gets the original frozen task prompt only. Explicit `offline-locator` is a research condition; recommended `offline-auto` uses the locator only for substantial read-only tasks and bypasses all workspace-write tasks. Offline anchors are not exposed.

The preview JSON saved under `.middle_man_cache/claude_benchmarks/<run-id>/preview.json` stores only redacted command shapes, prompt hashes, local heuristic sizes, decision metadata, and a source fingerprint. It does not store the full prompt. Task A `preemption-v4` selects the locator; `large-edit-v1` AUTO bypasses with equal prompt hashes and zero model-visible Middle_Man tokens. Local byte/4 estimates are not Claude-reported tokens.

## Memory Isolation

Before a disposable pair is committed, Phase 23 rejects `CLAUDE.md` and `CLAUDE.local.md` in either snapshot root or any ancestor directory. Preflight reports ancestor memory for the planned snapshot parent. This protects against project/ancestor instruction contamination only. The installed CLI was absent during Phase 23 implementation, so no documented user-setting source isolation could be verified; user-level Claude memory remains an unresolved blocker for a real A/B. Do not edit the user's Claude configuration to work around it.

## Stream Parser

The synthetic-fixture parser accepts Claude-style stream-json lines, tolerates unknown fields, and raises with a line number on malformed JSON by default (or records a warning in non-strict mode). It captures session ID, final text/status, durations, turns, cost, optional usage fields, and observed model when present. `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` are populated only from observed event fields. Final-result usage takes precedence over assistant-message usage; cost is stored separately and never converted to tokens. Missing final result is `incomplete`; an explicit timeout is `timeout`.

Tool-use blocks classify `Read`, `Grep`, `Glob`, `Edit`, `MultiEdit`, `Write`, and `Bash`; unknown tools remain `other`. Unique paths and repeated explicit `Read` calls are counted. Bash command text is not heuristically reclassified as file reads. These are observed native events, not Codex event assumptions.

The next Phase 23 substep is to install or locate Claude Code locally, inspect its documented flags and user-memory isolation behavior, and validate read-only permission enforcement without inference. A real Claude A/B needs separate authorization. Phase 24 provider adapters are not started.
