# Single exploration-trace pilot: local preflight only

**Status: READY FOR SEPARATE AUTHORIZATION; PILOT NOT RUN.** No Codex or
Claude inference process was started in this phase. The proposed observation
is one descriptive Middle_Man production-AUTO run, not a baseline/optimized
pair, a savings measurement, or a selector experiment. A-plus remains
research-only and unchanged.

## Exact proposed observation

- Task, exact UTF-8 text: `Trace a read-only production Codex request from the CLI through local context selection, isolated execution, event parsing, audit creation, and repository integrity checks.`
- Task SHA-256: `380ce2cdd99f2d2ea66a2b9c4dfa417af8227b1af4402c51387d45fb9d13531d` (the historical M01 task).
- Source commit/tree: `db187e0f48f54222dd250502a2e40b7f1fb16401` /
  `c597226461db5975ffafd50a769404e03442fda6`.
- Filesystem source fingerprint: `1a91d487a2629d4c82cbae7072ac873e8fcb516597fe954d53f74b649c4241fa`;
  tracked `AGENTS.md` blob: `0c8baf10e4f781c6b9eaa03c38a24b40d4e1978c`.
- CLI: `codex-cli 0.162.0-alpha.17.2`; model `gpt-6-sol`, effort `high`.
- Mode `read-only`; explicit Windows sandbox `unelevated`; approval `never`;
  `--json --no-daemon --ignore-user-config --strict-config --ephemeral`;
  Apps/plugins disabled and no MCP registration. The unelevated backend is not
  established as security-equivalent to the elevated backend.
- Timeout: 360 seconds. **At most one inference process, no retry**, even if
  it fails or times out. No OAuth/upload/edit task or A/B arm is authorized.

Prepare one disposable, committed, clean snapshot outside the primary working
tree. Clone with `core.autocrlf=false`, then detach at the pinned commit;
preserve tracked `AGENTS.md`. A clone inheriting this Windows workspace's
`core.autocrlf=true` has the correct Git tree but a different filesystem
fingerprint and must fail before process creation. The local-only corrected
snapshot preflight passed: clean, source and selector pins matched, production
AUTO returned `LOCATOR USED`, locator hash
`dbcba1d8d1737aac82f481643149283344a871a96d374ccc46dd2443e4c684c1`,
and 227 *locally estimated* locator tokens. No model process was launched.

## Instrumentation and validity

The existing `research_event_inspector(stdout, root)` callback is sufficient
to receive the completed JSONL stream in memory. The research-only adapter in
`middle_man/experiments/codex_exploration_pilot.py` adds the missing pilot
contract without changing production parsing or AUTO. `prepare_pilot` checks
the exact source/selector pins, clean tracked files, no ignored or untracked
files, CLI version, and a local production preview. `run_once` is opt-in,
fixes the task/runtime/timeout, checks readiness again, marks its preparation
used before invoking `run_codex`, and permits no retry on that preparation.
It has no CLI entry point. Tests replace `_Popen` with a fake process.

The callback rejects repository changes (including new ignored files),
malformed events, external/MCP activity, failed or incomplete turns, oversized
event input, and absent provider input/cached-input/output fields. The
post-run `assess_pilot` also requires the production runner's SUCCESS,
zero exit, unchanged clean source, one process, matching task/runtime/locator
identity, and aggregate trace/parser parity. Production may still label a run
SUCCESS when usage is missing; **pilot assessment does not**. A failed pilot
is a stopped observation, never a zero-usage substitute. Transient changes
that are fully restored before post-run inspection cannot be proven absent.

Only bounded operation positions/classes, safe relative target paths, repeat
opportunities, unknown flags, and production aggregate/provider usage values
may be retained as pilot metadata. The adapter returns them in memory. It
does not save raw JSONL, commands, search terms, prompts, command output,
source excerpts, or the final answer. Do not serialize the full
`CodexRunResult`; its final answer exists transiently in memory. Any later
sanitized receipt must be written outside the source snapshot under separate
authorization and reviewed for leakage before publication.

## Exposure and approval boundary

The local locator estimate is **not** Codex usage. In the two historical V2
Middle_Man M01 runs with the same locator, Codex reported 339,527-538,290
input tokens, 278,912-488,064 cached input tokens, and 3,195-6,287 output
tokens. These are descriptive examples, not a forecast or cap: one future run
could consume more, and the 360-second timeout does not bound tokens. The
model would receive the task and source-light locator, and its native reads
may transmit committed pinned source to OpenAI. A clean clone excludes local
untracked/ignored secrets, but a separate secret scan of the committed pin
and sandbox file-access preflight are required before any authorized call.
The read-only sandbox does not by itself prove that native reads cannot reach
outside the snapshot; stop if confinement or isolation cannot be verified.

Running this pilot requires a **new, explicit user authorization** for exactly
one external `codex exec` process under the settings above, disclosure of
the pinned committed source as needed by that process, and any desired local
sanitized receipt. If the CLI version, task, source, selector, locator,
filesystem, isolation, secret scan, or preflight differs, stop before launch.
After launch, stop on timeout, nonzero exit, malformed/missing events or
usage, external tool activity, repository mutation, or failed pilot
assessment. Do not retry, run a second arm, infer savings, or implement an
optimization from this single observation.

## Local verification

- Full pytest: 618 passed, 3 skipped. Focused synthetic trace/pilot tests:
  19 passed. No real Codex process was started.
- `git diff --check` passed. No tracked production file changed.
- Selector fingerprint remained `3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`;
  all four frozen Phase 22 result hashes matched their recorded values.
