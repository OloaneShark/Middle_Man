# Middle_Man v0.1.0a1 Alpha Release Candidate

Proposed tag: `v0.1.0a1`. This candidate has not been tagged or published.

## Included

- **Lab:** deterministic LLM-serving simulation with token-budgeted scheduling, KV blocks, preemption, prefix caching, workloads, metrics, and optional plots. Its timings and throughput are simulated, not real GPU measurements.
- **Gateway:** local repository indexing and search, bounded and redacted Context Packs, Git-aware change metadata, output compaction, Project Memory, and Session Handoff. The optional stdio MCP server's `codex-core` profile exposes `middleman_context`, `middleman_expand_context`, `middleman_project_state`, `middleman_session_handoff`, and `middleman_compact_output`.

## Install

From the directory containing the release wheel (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".\middle_man-0.1.0a1-py3-none-any.whl[mcp]"
.\.venv\Scripts\middle-man.exe index --repo C:\path\to\project
.\.venv\Scripts\middle-man.exe context find "request scheduling" --repo C:\path\to\project
```

Use an MCP client to start `.\.venv\Scripts\python.exe -m middle_man mcp serve --repo C:\path\to\project --tool-profile codex-core`. The Gateway runs locally without an OpenAI API key, Codex login, or any model call. The alpha release smoke test covers Windows and Python 3.14; the declared Python `>=3.11` range and other operating systems have not received equivalent release validation.

## Safety and limitations

- Give the Gateway only a repository you intend to inspect. It can write index, memory, and usage metadata under that repository's `.middle_man_cache/`, but read-only MCP tools do not edit source files.
- Path confinement, ignore patterns, bounded source reads, and secret redaction are defenses, not a guarantee that every sensitive value will be detected. Review repository contents and the receiving MCP client before sharing context externally.
- Middle_Man's context-token figures are local estimates. They do **not** prove general provider-token savings, billing reductions, or answer quality. Historical A/B observations are task-specific; experimental A-plus work is not production functionality.
- A proposed live Codex exploration pilot remains blocked: the available Windows sandbox did not sufficiently isolate host files outside its disposable snapshot. Do not infer host-filesystem confinement from Codex read-only mode.
- Research scripts and frozen benchmark fixtures are maintained in the source repository; this alpha wheel validates the Lab and local Gateway, not source-checkout research workflows.

See [README](../README.md) for Lab and Gateway commands and [Codex setup](CODEX_SETUP.md) for optional client registration.
