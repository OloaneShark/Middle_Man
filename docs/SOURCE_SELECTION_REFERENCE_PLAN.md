# Source-selection relevance references

This local-only phase freezes **proposed source-grounded judgments**, not human-validated ground truth or selector performance. The dataset is `docs/source_selection_reference_dataset.json`; the original 24-task corpus remains `tests/fixtures/locator_shadow_corpus.json`.

## Provenance and annotation

- Source commit: `0680a1cb8812d35b17ebd628de7ffba95798da7f`; tree: `6276b4a959bc93df8bb82cdde0bfc371d2c99770`.
- Corpus SHA-256: `6b1be495325413f5fc5e1e4bd53cbfc93a784c8f0365515e8f6a3e6d2ad803b5`. Each recorded task SHA-256 matches the original task text. The production selector fingerprint is recorded for integrity only.
- Codex inspected actual implementation and tests at that pinned commit, using the frozen task wording. Selector rankings, archived Codex search paths, candidate selections, and shadow results were not used to assign relevance. File paths, symbols, and source ranges are checked against a disposable pinned snapshot in tests.
- Core areas describe behaviors needed for an answer. Every area must have evidence; any complete option within an area suffices. An option may require multiple files. Supporting references add useful tests, integration, or detail without becoming mandatory. `unresolved` records scope ambiguity rather than fabricating a label.
- Development labels are N01, M02, C02, T01, G02, E01. Reserved evaluation labels are N04, M04, C04, T03, G04, E04 and require explicit evaluator opt-in. The other twelve frozen tasks are unlabeled. Reserved references should not be used to tune a future candidate.

## Evaluator contract

`middle_man/experiments/source_selection_reference_eval.py` is deterministic and local-only. It accepts a task ID, selected repository-relative paths, and a **caller-supplied local estimate** of selected source tokens. It neither invokes a model nor builds a Context Pack. Development is the default split; reserved tasks require `split="reserved", allow_reserved=True`.

It reports core-area coverage and misses, partial multi-file options, alternative-option satisfaction, supporting and test path coverage, explicit-anchor retention, unreferenced selected paths, unresolved notes, and selected source-token cost. Extra selected paths are **unreferenced**, not proven irrelevant. A selected path does not establish that the cited symbol or lines were actually delivered: all coverage values are path-level proxies. Future excerpt-level assessment must check delivered ranges against cited ranges before making stronger claims.

The dataset is frozen before any current-versus-candidate comparison. No selection changes, performance claims, or token-saving estimates are part of this phase. Independent human review is still required before treating these labels as ground truth. G02 and G04 explicitly retain scope ambiguity; G04 covers the simulator/benchmark-report interpretation, not an exhaustive Codex A/B report reference.
