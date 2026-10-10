# A-plus independent source review

Status: **protocol prepared; two human reviews and adjudication pending**.

1. Give each of two independent reviewers only the frozen task ID and wording,
   pinned source commit/tree, this protocol, and an unfilled copy of
   [`a_plus_review_template.json`](a_plus_review_template.json). Do not give
   them authoring provenance, production A or A-plus hints, candidate outputs,
   previous proposed references, or the other reviewer's judgments.
2. Each reviewer inspects the pinned clean source independently and records,
   per task, required implementation areas; source-relative paths; relevant
   qualified function/method symbols; inclusive source line intervals;
   complete alternative evidence options; supporting tests or integrations;
   unresolved interpretations; and source-grounded reasoning. An alternative
   must be sufficient as a whole, not merely an extra suggested file. Record
   uncertainty rather than forcing a unique interpretation of a broad task.
3. Submit both reviews before either reviewer sees any candidate locator
   output. Record reviewer identities and timestamps only when supplied by the
   actual humans; empty fields remain `null` and status remains `PENDING`.
4. Compare independent submissions and adjudicate disagreements against the
   same pinned source. Record each disagreement, the source-grounded decision,
   and unresolved issues in a versioned adjudication record. A reviewer may
   reject a fundamentally unanswerable task before candidate observation;
   resolve that by versioning the corpus, not by substituting a task after
   seeing experimental results.
5. Freeze human-validated references, ambiguity treatment, source/index and
   selector fingerprints, semantic rubrics, and the already-fixed acceptance
   gates before running A or A-plus. Without two independent human reviews and
   adjudication, later results are exploratory only. Codex-generated reference
   suggestions, if ever prepared, are `AI_PROPOSAL` and never a replacement
   for independent human validation.

The template intentionally contains no task judgments or candidate outputs.
The frozen prospective design in
[`a_plus_locator_prospective_design.json`](a_plus_locator_prospective_design.json)
remains authoritative for later evaluation. This protocol authorizes neither
offline candidate scoring nor external inference.
