# Codex and Middle_Man

Middle_Man exposes its existing local Gateway over the optional Python MCP SDK. The stdio server is scoped to one explicit repository and does not require an OpenAI API key. It does not call a model. Codex itself requires its normal authentication to run.

Verified locally with `codex-cli 0.155.0-alpha.16.3` and Python MCP SDK `mcp 2.2.0`. The installed Codex CLI supports `codex mcp add NAME -- COMMAND ...`, `codex mcp get NAME --json`, and `codex mcp list --json`.

## Install and Register (Windows PowerShell)

From the Middle_Man repository root:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,mcp]"
$python = (Resolve-Path ".venv\Scripts\python.exe").Path
$repo = (Get-Location).Path
codex mcp add middle-man -- $python -m middle_man mcp serve --repo $repo --tool-profile codex-core
codex mcp list
```

Use an **absolute** path to `.venv\Scripts\python.exe` in the registration if invoking Codex from another working directory. The verified local registration uses that absolute executable and repository path. Codex launches the server on demand; do not start a second foreground server for normal use. To replace an old registration, use `codex mcp remove middle-man` and add it again. This alters Codex's user-level MCP configuration, not repository source.

On macOS/Linux, use `.venv/bin/python` instead. Install `pip install -e ".[mcp]"` when development test dependencies are not needed.

## Check the Connection

```powershell
codex mcp list --json
.venv\Scripts\python.exe -m pytest -q tests/test_mcp_protocol.py
.venv\Scripts\python.exe -m middle_man mcp usage --repo . --json
```

`codex mcp list` confirms registration, not a successful Codex tool call; the protocol tests exercise the actual stdio handshake. `mcp serve` writes protocol messages only to stdout. If the optional SDK is missing, it exits with an installation hint, while the Lab and local Gateway commands remain usable. For a manual stdio start, run `.venv\Scripts\python.exe -m middle_man mcp serve --repo .` from the repository root and connect an MCP client; it is not an interactive text command.

The root [AGENTS.md](../AGENTS.md) routes a fresh scoped task to one `middleman_context` call. The default `codex-core` profile offers five read-only tools: `middleman_context`, `middleman_expand_context`, `middleman_session_handoff`, `middleman_compact_output`, and `middleman_project_state`. Use `--tool-profile full` for the original ten-tool diagnostic surface, including `middleman_find_context` and `middleman_context_pack`. Core responses are bounded/redacted and omit redundant metadata; a repeated identical pack returns no source unless `force_replay=true`. Expansion returns only newly delivered ranges. Native reads remain the correctness fallback when source is stale, incomplete, or exact full text is needed.

## Local Usage Data

`mcp usage` reports call counts, errors, Context Packs, expansions, index cache reuse, and heuristic context-token estimates. The JSONL log at `.middle_man_cache/mcp_usage.jsonl` stores only metadata, query hashes, current-server implementation identity, and sanitized excerpt path/hash/range/line-byte identity for overlap analysis, not task text, source excerpts, compacted output, secrets, or raw diffs. It is local and Git-ignored. The token estimator is UTF-8 bytes divided by four, rounded up. These figures **cannot measure Codex plan usage, provider billing, or real token savings**. Compare equally scoped local context paths when evaluating efficiency, and verify answer quality separately.

For a quick local status check, run `codex --version`, `codex mcp get middle-man --json`, `.venv\Scripts\python.exe -c "import mcp"`, `Test-Path AGENTS.md`, and the protocol test above. These verify executable availability, registration, dependency, instructions, startup, and tool listing without sending repository context to Codex. If Codex cannot reach the MCP server, inspect those results and the registered executable path. Codex can still use native repository reads. Do not put secrets in tasks or logs on the assumption that pattern-based redaction will catch every form.


## Real A/B Benchmark

The separate [Phase 22 benchmark guide](CODEX_BENCHMARKS.md) covers snapshot isolation, explicit external-service confirmation, correctness gates, official Codex JSONL usage fields, and Middle_Man context-overlap estimates. An early suite attempt was infrastructure-invalid. A later valid Task A v1 pair was FAIL/FAIL and the optimized side used far more Codex-reported input tokens. Phase 22.1 provides local candidate optimizations only; a new Task A v2 A/B run requires separate authorization. Do not infer real token savings from the local estimates.
