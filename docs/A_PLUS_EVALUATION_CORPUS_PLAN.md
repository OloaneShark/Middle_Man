# Prospective A-plus evaluation corpus

Status: **task text frozen; independent human review pending; candidate evaluation unrun**.

The machine-readable corpus is
[`tests/fixtures/a_plus_prospective_corpus.json`](../tests/fixtures/a_plus_prospective_corpus.json).
Its 16 tasks cover four preregistered archetypes: narrow explicit-anchor,
multi-file architecture, test-focused, and broad/ambiguous (four each). Tasks
span lab workload generation, simulation/reporting, output compaction, MCP
progressive delivery, and production Codex telemetry/audit. They are developer
navigation questions, not reference answers or selector probes.

The source is the clean `8a6dca9e3cfadd144f14e860d182ec44ac0faedc`
snapshot, tree `467f280dfc781897099d726085974223cf9d6754`, source
fingerprint `bf192a20ad175d0714ddaeee4927c034f452fed5fb93c396acb0a94d515e3c9c`
from `middle_man.gateway.codex_benchmark.tasks.source_fingerprint`. A
disposable clone was used for read-only inspection; tracked `AGENTS.md`, clean
status, commit, and tree were checked. Future references must be derived from
this exact source, not the older development snapshot or the repository's
post-corpus HEAD.

Task wording was drafted from source and tests without invoking production A
or A-plus. For originality, only the wording of the 24 historical task prompts
in `tests/fixtures/locator_shadow_corpus.json` was inspected. No reserved
reference labels were opened. The validator also rejects exact historical
prompt matches, but close-paraphrase review remains a human judgment.
The prompts were not selected or tuned using locator behavior.

Each task stores its exact UTF-8 wording, SHA-256, source pin, authoring paths,
explicit supplied anchors, and ambiguity note. `corpus_sha256` hashes the
canonical JSON `tasks` array with sorted keys, no extra whitespace, and UTF-8
encoding. Authoring paths record why the task is answerable; they are **not**
reference judgments and should be withheld from reviewer packets. Any change
to frozen task text or corpus checksum needs a new versioned corpus, never an
in-place adjustment after candidate observation.

[`A_PLUS_HUMAN_REVIEW_PROTOCOL.md`](A_PLUS_HUMAN_REVIEW_PROTOCOL.md) and
[`a_plus_review_template.json`](a_plus_review_template.json) prepare two
independent, source-grounded reviews and disagreement adjudication. Both human
slots are blank and `PENDING`. No implementation-area references, semantic
rubrics, candidate outcomes, navigation scores, or human approvals exist yet.
This phase makes no confirmatory A-plus claim and does not authorize offline
candidate evaluation or external model calls.
