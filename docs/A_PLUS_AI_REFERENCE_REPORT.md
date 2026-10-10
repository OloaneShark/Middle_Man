# Exploratory A-plus source references

Status: **AI_PROPOSED_SOURCE_GROUNDED_NOT_HUMAN_VALIDATED**.

This is one AI-assisted source-inspection pass for the 16 tasks in
[`a_plus_blinded_review_packet.json`](a_plus_blinded_review_packet.json),
not two independent human reviews or adjudication. Both human submissions
remain `PENDING`. The task wording, source pin, prospective design, selector,
and A-plus implementation were not changed. No production A or A-plus hints
were generated or inspected for these tasks, and no navigation scores or model
benchmark calls were made.

The references are in
[`a_plus_ai_proposed_references.json`](a_plus_ai_proposed_references.json).
Their source is commit `8a6dca9e3cfadd144f14e860d182ec44ac0faedc`,
tree `467f280dfc781897099d726085974223cf9d6754`. The canonical blinded
packet SHA-256 is
`a6cc580cbc71b88c55619095c39f322cec7180cdfed8368efff72518734eebdb`.
The frozen reference-task-array SHA-256 is
`d9511d4d626e900faf570953fe6a80443217f086f00c9d62bb47ec2cff490b1c`.
Each area records one or more complete proposed evidence options; every span
names a pinned Python class/function/method and its exact inclusive AST line
interval. Supporting tests are separate. An option's spans are jointly needed
for that area; multiple options are alternatives, not extra required files.

## Scope and uncertainty

Ten tasks have complete **proposed** generic references: `AP-N01` through
`AP-N04`, `AP-M01` through `AP-M04`, `AP-T03`, and `AP-T04`. Six have partial
proposals with unresolved interpretation or coverage:

- `AP-T01`: freshness is tested for repeated workload materialization, but
  direct cross-case object-identity coverage was not found in the inspected
  tests.
- `AP-T02`: JSON simulated/seed fields and both export files are tested;
  inspected tests do not directly assert CSV's simulated flag or seed field.
- `AP-G01`: no concrete benchmark case or numbers identify the surprising
  utilization/timing observation.
- `AP-G02`: the input type and actual failure evidence are unspecified; the
  proposed branches cover pytest and generic log compaction.
- `AP-G03`: no response metadata identifies why the MCP reply was sparse;
  progressive seeding is only one source-grounded possibility.
- `AP-G04`: no particular answer or source claims were supplied, so the
  recorded run cannot establish that answer's semantic correctness.

Other task-level scope qualifications are retained in the JSON even where a
generic reference proposal is complete. These are not scored as definitive
references for missing incident details. The dataset is frozen before any
future A-versus-A-plus comparison. With no independent human validation,
future use must remain **exploratory** and must not be described as satisfying
the prospective confirmatory acceptance gate.

## Validation method

Only the blinded packet and a disposable clean checkout of the pinned commit
were used to author judgments. The validator reads the pinned Git tree and
the cited source blobs, checks task hashes and dataset checksum, and verifies
each path, qualified symbol, and full line interval against Python AST nodes.
It does not import or invoke production A, A-plus, navigation scoring, or a
model service. Source-grounded explanations are AI judgments, not proof of
human agreement or of future locator performance.
