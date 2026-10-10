# Navigation hint preservation feasibility

**Local-only cost study, not another selector experiment.** The reproducible
source-free measurements are in
[`navigation_hint_preservation_feasibility.json`](navigation_hint_preservation_feasibility.json).
The evaluator only reconstructs the committed A (production), B (independent
navigation), and C (precision variation) locator hints, checks their original
SHA-256 and appendix estimates, and measures fixed unions. It does **not** load
or score development reference labels or inspect reserved evaluation labels.
No model calls were made.

## Fixed method

The source commit is `0680a1cb8812d35b17ebd628de7ffba95798da7f`
(tree `6276b4a959bc93df8bb82cdde0bfc371d2c99770`). Corpus, reference
file, selector, task hashes, source fingerprint, and all three committed result
artifacts matched their pins. Every recorded hint path was checked against the
clean pinned snapshot with repository confinement and secret redaction. Original
A/B/C locator texts reconstructed byte-for-byte by SHA-256.

**B+C:** Keep every B location, in B path order, and add every distinct C
location or symbol in its existing file. **A+B+C:** Keep every A location in
A path order, then add all distinct B and C locations. Any B-only paths follow
the A paths in B order. Exact `(path, start, end, symbol)` duplicates are
removed; distinct symbols at the same coordinates remain distinct. Same-file
locations use the existing production-compatible `; ` syntax. No range was
replaced, broadened, manufactured, selected by reference coverage, or dropped
to meet budget. The appendix includes the unchanged production heading and
instructions; estimates use `HeuristicTokenEstimator`, not provider usage.

## Fixed-budget results

`Delta` is combined appendix minus the task's original A appendix budget.
Positive deltas are **infeasible at that fixed budget**. The last columns show
distinct paths/locations and exact duplicates removed for each union.

| Task | A budget | B | C | B+C / delta | A+B+C / delta | B+C paths/locations/dups | A+B+C paths/locations/dups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N01 | 228 | 223 | 225 | 259 / +31 | 401 / +173 | 9/11/7 | 14/26/7 |
| M02 | 397 | 393 | 397 | 437 / +40 | 704 / +307 | 19/23/15 | 27/54/15 |
| C02 | 339 | 338 | 339 | 359 / +20 | 556 / +217 | 18/20/16 | 19/50/16 |
| T01 | 375 | 371 | 375 | 405 / +30 | 691 / +316 | 15/18/12 | 23/54/12 |
| G02 | 288 | 284 | 284 | 284 / -4 | 425 / +137 | 15/15/15 | 18/41/15 |
| E01 | 220 | 220 | 220 | 220 / 0 | 355 / +135 | 10/10/10 | 16/27/10 |

**B+C fits only G02 and E01. A+B+C fits none.** In original supplemental
order, every distinct added hint for the four over-budget B+C tasks would
need more budget; none was silently omitted. The JSON records counts and
the complete safe coordinates/symbols. G02 and E01 have no distinct C addition
to B, so their B+C outputs are unchanged. The full A+B+C outputs retain A
even where A paths do not occur in B.

## Replacement versus path changes

- **M02:** C replaced B's `MCPGateway.context:266-320` with
  `MCPGateway.explain_selection:516-527`. B+C can represent both on the same
  path, but costs **40** tokens beyond A's fixed appendix estimate. This is a
  destructive within-file replacement, not a path-selection difference.
- **T01:** C's useful test and memory hints are additional same-path locations
  alongside B's originals. Keeping all of them costs **30** over A's budget.
  This measurement does not rescore the hints' quality.
- **C02:** B and C share the `ContextQuery` location rather than A's
  `RelevanceEngine.find`-covering location. That loss predates C's within-file
  substitutions. A+B+C retains A but is **217** tokens over budget; the full
  union also includes paths introduced by B. It is not a cost-free correction.
- **G02 and E01:** C adds no distinct location to B. A+B+C still exceeds each
  budget because it retains A's other paths and ranges as well.

## Where the bytes go

Across six complete B+C texts, path names contribute **2,706 bytes**,
range coordinates **552**, qualified-symbol labels **3,051**, production
separators **360**, and the fixed wrappers **1,176** (196 per task). For
A+B+C, those figures are **3,728 / 1,309 / 5,568 / 732 / 1,176 bytes**.
These are additive UTF-8 byte counts; estimated tokens apply the production
one-per-four-byte heuristic to the **whole** appendix, with rounding.

Production's semicolon grouping already prints a repository path once per
file, so repeated same-file ranges mainly add coordinates and often long
qualified symbols, not a second full path. The larger A+B+C unions add many
distinct paths as well. Fixed wrapper cost is real but unchanged across the
configurations; it does not explain their marginal overrun. Later supplemental
hints accumulate on appendices already close to A's ceiling. This is measured
in input order, not a quality-based choice of which hint to keep.

A future lossless representation might reduce repeated symbol qualification
or other metadata, but compatibility with the production parser, readability,
redaction, and exact-location semantics would need a separate prospective
analysis. No syntax or budget was changed here. Full preservation is
technically representable, but generally **not affordable within the fixed
production appendix budgets**. This does not declare a selector winner,
prove model behavior, or estimate provider token savings. The proposed N01
and G02 reference caveats and all previous experiment decisions remain intact.
