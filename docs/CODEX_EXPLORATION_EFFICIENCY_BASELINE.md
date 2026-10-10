# Offline Codex exploration-efficiency baseline

This is a research-only accounting baseline, not a locator experiment or a
provider-token savings claim. Production AUTO, production locator selection,
A-plus, and archived calibration results remain unchanged. No Codex or Claude
process was launched for this analysis.

## What is already observable

The shared Codex JSONL parser counts completed native commands, explicit
reads, unique read files, rereads, searches, listings, Git inspections, and
unclassified commands. Production parsing separately records safe search
targets, content-producing/file-targeted/repository-wide searches, and
file-listing searches. A production run can compare read/searched paths with
locator-selected paths. Its optional sanitized audit saves aggregates, safe
repository-relative paths, provider-reported input/cached-input/output tokens,
elapsed time, status, and identity metadata. It deliberately omits raw
commands, search terms, source, full prompts, final answers, and event order.
An aggregate reread is a possible efficiency opportunity, not proof that
reopening the file was unnecessary.

## Frozen V2 observations

The four sanitized V2 receipts record the following. All four runtime statuses
were SUCCESS; semantic PASS was reported during human review but cannot be
reproduced from the receipts alone because answer/reviewer evidence was not
archived. Token values below are **provider-reported**, not local estimates.

| Call | Arm | Native | Reads | Unique | Rereads | Searches | Listings | Input | Cached input | Output | Seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Baseline A | 29 | 22 | 18 | 4 | 6 | 3 | 444,869 | 384,256 | 4,282 | 76.343 |
| 2 | Middle_Man A | 33 | 23 | 21 | 2 | 7 | 1 | 538,290 | 488,064 | 6,287 | 101.681 |
| 3 | Middle_Man B | 22 | 19 | 19 | 0 | 2 | 1 | 339,527 | 278,912 | 3,195 | 61.176 |
| 4 | Baseline B | 30 | 21 | 21 | 0 | 4 | 3 | 412,053 | 359,296 | 4,400 | 59.687 |

Both Middle_Man runs recorded `LOCATOR USED`, the same locator hash
`dbcba1d8d1737aac82f481643149283344a871a96d374ccc46dd2443e4c684c1`,
and 14 selected paths. Their locator paths explicitly read were 7 and 8;
locator paths searched were 8 and 6; non-locator paths searched were 8 and 3.
Their native calls, searches, rereads, and provider-reported input also differ.
The baseline arms had no locator, so locator/non-locator path splits do not
apply to them. The archived receipts provide aggregate counts and path sets,
**not ordered native-command history**. Chronological replay, exact repeated
search queries, and identification of truly redundant operations are
**UNAVAILABLE**. These four observations cannot attribute the variation to
the unchanged locator, establish a savings effect, or support a statistical
noise band.

## Ordered trace available for future supplied events

`middle_man/experiments/codex_exploration_trace.py` accepts an explicitly
supplied in-memory JSONL string or iterable of lines, including lines read by
the caller from a local synthetic fixture. It launches no process and writes
no files. It reuses production framing/counts, explicit-read extraction,
search-target classification, secret redaction, and repository path
confinement. For each completed native command it returns bounded metadata:
position, operation class, verified safe relative targets, explicit-read
count, previously read paths, revisited search targets, and unknown flags.
The input and output are capped; sensitive/ignored paths are suppressed.
Malformed event counts are retained with only a bounded line-number sample.
Neither command text nor terms, output, source, prompt, or answer appear in
the result.

The trace can flag a later read of the same safe path as a **possible**
efficiency opportunity. It can flag later searches targeting the same safe
path, even when the searches used different terms; it cannot call them
duplicate queries. Mixed, unsupported, malformed, or target-ambiguous commands
remain marked unknown. A completed command event does not establish whether
its action succeeded or whether a second read was necessary. Aggregate counts
remain those of the production parser; suppressing a sensitive target does
not silently rewrite production totals.

## Diagnostic next questions

The V2 aggregate rereads, extra searches, and larger non-locator search set
in Middle_Man A are concrete places to inspect for **possible** exploration
cost, not diagnosed waste. An ordered future stream could distinguish a
reopened path from a first read and repeated search targets from new targets.
It still could not determine query equivalence or necessity without additional
evidence. Questions about actual Codex usage, causal savings, answer quality,
or whether a particular repeat was avoidable require new, separately
authorized controlled Codex runs with provider usage and independent semantic
review. The V2 receipts cannot be replayed to answer them.

The analyzer is ready for offline synthetic testing and for a separately
authorized, privacy-reviewed future controlled trace experiment. It is not
activated by production `research_event_inspector`, does not change AUTO, and
does not propose a new selector or optimization rule.

## Verification

Eight synthetic trace tests passed; full pytest: **607 passed, 3 skipped**.
`git diff --check` passed. The selector fingerprint remained
`3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`.
All four frozen Phase 22 result hashes and all four archived V2 receipt hashes
matched. Existing tracked production, calibration, A-plus, and research files
had no diff from the starting HEAD.
