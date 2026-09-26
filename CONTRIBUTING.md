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

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Design Expectations

- Keep Lab and Agent Gateway code paths separate.
- Do not fabricate benchmark results.
- Do not log secrets.
- Keep optional provider integrations clearly optional.
- Prefer clear state transitions over clever shortcuts.
