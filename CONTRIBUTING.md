# Contributing to Middle_Man

Middle_Man is meant to be readable enough to study and structured enough to extend.

Good contribution areas include:

- scheduler policies
- preemption policies
- model runners
- benchmark workloads
- repository-language adapters
- context-selection strategies
- provider integrations
- MCP tools
- documentation and interview examples

Please keep changes focused and measurable. For simulator changes, add or update tests that protect the relevant invariant. For gateway changes, prefer local deterministic analysis before adding an LLM dependency.

## Development

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

On macOS or Linux, use `python3 -m venv .venv` and `.venv/bin/python` for the remaining commands.

## Design Expectations

- Keep Lab and Agent Gateway code paths separate.
- Do not fabricate benchmark results.
- Do not log secrets.
- Keep optional provider integrations clearly optional.
- Prefer clear state transitions over clever shortcuts.
