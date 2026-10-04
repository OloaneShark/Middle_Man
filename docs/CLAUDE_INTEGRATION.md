# Claude Code Integration (Phase 23.1)

Phase 23 is local-only. The Claude benchmark command has no inference execution path, even with `--confirm-external-service`. No Claude A/B result or Claude token-saving claim exists.

## Commands

```bash
python -m middle_man claude benchmark list
python -m middle_man claude benchmark preflight
python -m middle_man claude benchmark run preemption-v4 --dry-run --model sonnet
python -m middle_man claude benchmark run large-edit-v1 --dry-run --optimized-mode offline-auto
python -m middle_man claude benchmark report <run-id>
```

`preflight` looks for `claude` on PATH and, if found, calls only `claude --version` and `claude --help`. It records declared flags, documented option values, and the local Windows/shell environment. A missing CLI is reported cleanly; synthetic tests and previews remain usable. Command arguments are emitted only when help confirms the required flags and isolation semantics. Requested model is recorded; observed model remains unknown until a future real stream reports it.

### Local validation, 2026-10-04

Claude Code `2.1.289 (Claude Code)` was found at `%USERPROFILE%\.local\bin\claude.exe` on native Windows. This is an observation of one installed CLI, not a permanent version requirement. Its help documents `-p`, `--output-format` with `stream-json`, `--verbose`, `--model` (including alias `sonnet`), and `--tools`. `--tools <tools...>` accepts a comma-separated built-in list such as `Bash,Edit,Read`; Middle_Man's `Read,Glob,Grep` and `Read,Glob,Grep,Edit,Write,Bash` strings match that format. Help does not enumerate every built-in tool name, so individual availability beyond its examples is not runtime-verified. Help does not state that `--verbose` is required for `stream-json`; the builder retains it.

The same help documents `--allowedTools`/`--allowed-tools`, `--disallowedTools`/`--disallowed-tools`, `--permission-mode` (acceptEdits, auto, bypassPermissions, manual, dontAsk, plan), `--permission-prompts`, `--mcp-config`, `--strict-mcp-config`, `--safe-mode`, `--restricted`, `--setting-sources` (user, project, local), and `--no-session-persistence`. It does **not** document `--max-turns` in this version. The builder accepts a configured turn limit only when a future installed help documents that flag; a requested limit currently fails closed. It never supplies an artificially small default.

The validated construction shape is `claude -p <redacted prompt> --output-format stream-json --verbose --safe-mode --restricted --strict-mcp-config --no-session-persistence --model <configured model> --tools <profile>`. Both sides receive identical controls. No command of this shape has been executed. Neither `--dangerously-skip-permissions` nor a permission-mode value is used; help lists modes but does not explain enough runtime semantics to select one for the benchmark.

The read-only profile whitelists `Read,Glob,Grep`; it does not include Bash or edit tools. The workspace-write profile lists `Read,Glob,Grep,Edit,Write,Bash` under ordinary CLI permissions. `--restricted` confines file tools to working directories and removes code-running tools unless `--tools` names them; the write profile intentionally names Bash. These are documented CLI restrictions, **not** a proven OS sandbox or runtime permission test. A future live benchmark must separately validate that writes are blocked in the read-only profile and allowed appropriately in the edit profile.

## Offline Pair

The dry-run reuses frozen task definitions and the existing BALANCED/6000 source-free locator and AUTO decision. It creates independent, source-identical, committed, Git-clean disposable snapshots, does local preprocessing against the optimized copy, checks that neither snapshot changed, and removes the copies after the preview. No `.mcp.json` or Middle_Man MCP registration is generated. No source excerpts, selector diagnostics, hidden acceptance tests, or benchmark answers enter the optimized prompt. Baseline gets the original frozen task prompt only. Explicit `offline-locator` is a research condition; recommended `offline-auto` uses the locator only for substantial read-only tasks and bypasses all workspace-write tasks. Offline anchors are not exposed.

The preview JSON saved under `.middle_man_cache/claude_benchmarks/<run-id>/preview.json` stores only redacted command shapes, prompt hashes, local heuristic sizes, decision metadata, and a source fingerprint. It does not store the full prompt. Task A `preemption-v4` selects the locator; `large-edit-v1` AUTO bypasses with equal prompt hashes and zero model-visible Middle_Man tokens. Local byte/4 estimates are not Claude-reported tokens.

## Memory Isolation

Before a disposable pair is committed, Phase 23 rejects `CLAUDE.md` and `CLAUDE.local.md` in either snapshot root or any ancestor directory. Preflight reports ancestor memory for the planned snapshot parent and existence only for `%USERPROFILE%\.claude\CLAUDE.md`, `CLAUDE.local.md`, `settings.json`, `settings.local.json`, plus home-root memory files. It does not read or print their contents. On 2026-10-04, the two `%USERPROFILE%\.claude\CLAUDE*.md` files and home-root memory files were absent; `%USERPROFILE%\.claude\settings.json` existed. No user file was opened or changed.

Installed help says `--safe-mode` disables `CLAUDE.md` discovery, plugins, hooks, skills, and MCP customizations, while admin-managed policy still applies. `--restricted` ignores user/project/local settings, but managed settings and explicit `--settings` may still apply. The benchmark does not pass `--settings` or `--setting-sources`; the latter documents only `user,project,local`, not an empty-source value. `--strict-mcp-config` ignores inherited MCP and no `--mcp-config` is supplied. `--bare` was not selected because installed help says it requires API-key-style auth and avoids OAuth/keychain reads. An `auth status` subcommand was found in help but not run; authentication readiness is unresolved. Managed policy effects and runtime enforcement remain unverified. Do not edit the user's Claude configuration to work around them.

## Stream Parser

The synthetic-fixture parser accepts Claude-style stream-json lines, tolerates unknown fields, and raises with a line number on malformed JSON by default (or records a warning in non-strict mode). It captures session ID, final text/status, durations, turns, cost, optional usage fields, and observed model when present. `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` are populated only from observed event fields. Final-result usage takes precedence over assistant-message usage; cost is stored separately and never converted to tokens. Missing final result is `incomplete`; an explicit timeout is `timeout`.

Tool-use blocks classify `Read`, `Grep`, `Glob`, `Edit`, `MultiEdit`, `Write`, and `Bash`; unknown tools remain `other`. Unique paths and repeated explicit `Read` calls are counted. Bash command text is not heuristically reclassified as file reads. These are observed native events, not Codex event assumptions.

The next Phase 23 substep is a separately authorized, controlled validation of actual read-only/write permission behavior, tool availability, stream event shape, and any managed policy effects. The current harness remains dry-run-only and is **not yet safe enough to authorize a real Claude A/B** on local-help evidence alone. A real pair requires separate authorization. Phase 24 provider adapters are not started.
