# Locked locator-quality shadow corpus

This phase is local-only diagnosis. The 24 fixed, unlabeled read-only questions are in [the corpus fixture](../tests/fixtures/locator_shadow_corpus.json). [The complete source-free result](locator_quality_shadow_results.json) records every task's full quality fingerprint, evidence category per selected path, locator hash, distribution, anchor position, and shadow decision. Reproduce it with `.venv\\Scripts\\python.exe -m scripts.measure_locator_shadow_corpus --save-full`; omit `--save-full` for stdout-only summary or add `--full` for complete stdout JSON. No Codex or Claude model call is made.

## Pins and labels

- Shadow source commit: `0680a1cb8812d35b17ebd628de7ffba95798da7f`; Git tree: `6276b4a959bc93df8bb82cdde0bfc371d2c99770`; content fingerprint: `6f360e98d7d87339129d0fde8725b6e26a03fcdf0f16f9a24d8c7a3f6a3db340`.
- Selector implementation fingerprint: `3a4213e19944220c02b1897e1a05a584d61bbd00e91cbf5a9e38cc07976bf555`. Selection mode is BALANCED, 6,000 heuristic context tokens, using the existing offline locator.
- Only two real outcome labels exist. `TASK_A_WIN`: frozen Task A, source `284c4451ad9213f4f27f6d534eac8be2484c2f9a`, content `a548097a4294fd67b2d42a5ab616c19b8ab226d702a406fa36f588873d0a0c1b`, locator `14587213a088bcc66d0304ee0473fc23000bd01e2f13042c714a14550da62e97`; baseline 86,515 vs locator 38,269 Codex input (-55.8%). `PRODUCTION_LOSS`: valid isolated read-only pair, source `bdd471f19bc4ffb9a0548cfcfdf54f4abdce6731`, content `3d5b58508f3b7791306af181ad284fa665802b83070f7d1aad797dc80b818b31`, locator `6be069352e2f897b9eea765fbc15516c6e4029ecd8651dc14191041e5d72d379`; baseline 419,071 vs Middle_Man 520,777 (+24.27%).
- The 24 new tasks have **no provider outcomes**. OAuth FAIL/FAIL, upload without a pair, workspace-write losses, timeouts, invalid pairs, Apps-contaminated pairs, and unpaired smokes are not quality labels here.

## Task corpus

Four tasks per archetype. The explicit-path/symbol flags indicate task text supplied such anchors, not that the selector found them. SHA-256 of each exact UTF-8 task string is locked in the fixture.

| ID | Archetype | Explicit path/symbol | Read-only engineering question |
| --- | --- | --- | --- |
| N01 | NARROW_COMPONENT | N/N | How does prefix-cache block ownership work when a second request reuses a prompt prefix, and when are those blocks released? |
| N02 | NARROW_COMPONENT | N/N | What does the memory controller do when a planned work item needs more KV blocks than are free? |
| N03 | NARROW_COMPONENT | N/N | How does the virtual clock advance during simulation when no request is currently runnable? |
| N04 | NARROW_COMPONENT | N/N | How does secret redaction protect source excerpts before context is returned to a caller? |
| M01 | MULTI_COMPONENT_ARCHITECTURE | N/N | Trace a read-only production Codex request from the CLI through local context selection, isolated execution, event parsing, audit creation, and repository integrity checks. |
| M02 | MULTI_COMPONENT_ARCHITECTURE | N/N | Explain the Agent Gateway context flow from an MCP request through indexing, relevance ranking, source selection, and response delivery. |
| M03 | MULTI_COMPONENT_ARCHITECTURE | N/N | How is a Context Pack built from a task query, and how are source ranges chosen and redacted before delivery? |
| M04 | MULTI_COMPONENT_ARCHITECTURE | N/N | Trace the Claude runtime probe from workspace preparation through tool restrictions, stream event parsing, and filesystem validation. |
| C01 | CROSS_CUTTING_FEATURE | N/N | How are project memory facts recorded and carried into a later session handoff without replacing source verification? |
| C02 | CROSS_CUTTING_FEATURE | N/N | How do indexed imports and tests influence relevance candidates and the final selection of context ranges? |
| C03 | CROSS_CUTTING_FEATURE | N/N | How do index caching and source hashing prevent stale repository content from being delivered as current context? |
| C04 | CROSS_CUTTING_FEATURE | N/N | Trace how the Codex CLI preview, execution, and audit stages preserve the original task and read-only repository state. |
| T01 | TEST_FOCUSED | N/N | Which tests demonstrate prefix-cache reference counting and release, and what implementation paths do they exercise? |
| T02 | TEST_FOCUSED | N/N | Which tests prove chunked prefill progresses across iterations before decode, and where is that behavior implemented? |
| T03 | TEST_FOCUSED | N/N | Which tests validate read-only Codex isolation and rejection of repository mutations, and how do those checks work? |
| T04 | TEST_FOCUSED | N/N | Which tests cover repository path confinement and secret redaction for context delivery? |
| G01 | GENERIC_BROAD | N/N | Explain the major parts of Middle_Man and how its simulation and repository-context tools fit together. |
| G02 | GENERIC_BROAD | N/N | How does Middle_Man decide what repository context is relevant to a user's question? |
| G03 | GENERIC_BROAD | N/N | What safeguards keep repository context requests from exposing sensitive or out-of-root files? |
| G04 | GENERIC_BROAD | N/N | How does the project measure and report simulator behavior and benchmark comparisons? |
| E01 | EXPLICIT_ANCHOR | Y/Y | In middle_man/lab/preemption.py, explain how LargestPrivateOwnerPolicy.choose_victim chooses a request under KV pressure. |
| E02 | EXPLICIT_ANCHOR | Y/Y | Trace build_offline_locator in middle_man/gateway/codex_benchmark/offline_locator.py and explain how its hints are assembled. |
| E03 | EXPLICIT_ANCHOR | Y/N | In middle_man/lab/prefix_cache.py, how are shared prefix blocks retained and released? |
| E04 | EXPLICIT_ANCHOR | N/Y | How does RepositoryIndexer.index collect symbols and import relationships for later context queries? |

## Feature definitions

All formulas below were fixed in code and synthetic tests before the first 24-task measurement. Ratios are rounded to four decimal places. Zero denominators yield zero. These are observations, not gates.

- `largest_cluster_share` = size of the largest selected-node import/test connected component / selected paths. A connected selection has 1.0; this does not prove semantic relevance.
- `median_to_top_score_ratio` = median selected candidate score / highest candidate score. The existing within-50/75/90% fractions remain unchanged.
- `ambiguous_exact_symbol_pressure` = selected paths with at least one `exact_symbol` appearing in multiple indexed files / selected paths. `ambiguous_only_exact_symbol_ratio` counts paths with ambiguous exact symbols but no unique exact symbol. Ordinary `symbol_term` matches do not count as exact symbols.
- `required_phase_path_ratio` = selected paths with a REQUIRED selected range / selected paths. `novel_coverage_efficiency` = distinct useful query terms credited as novel in selected diagnostics / selected paths; `novel_coverage_path_ratio` = paths credited at least one novel useful term / selected paths.
- Strongest evidence category per selected path uses precedence `VERY_STRONG > STRONG > AMBIGUOUS_DIRECT > WEAK > GRAPH > NONE`. VERY_STRONG: explicit path, trace path, or unique exact symbol. STRONG: filename or symbol term. AMBIGUOUS_DIRECT: repeated exact symbol (unless a stronger category applies). WEAK: path/import/source/family term. GRAPH: import/test relationship. This aggregation does not alter selector signal weights. In particular, STRONG can mask an ambiguous exact symbol, so pressure is recorded separately.
- `test_selected_path_ratio` and `unique_exact_symbol_path_ratio` normalize existing counts. The full vector flattens stable numeric diagnostic fields, selection phase counts, signal counts, evidence category counts/ratios, and term-list lengths. It excludes variable path-name maps and per-path source metadata from quantiles, though the full receipt retains the latter.

Quantiles below use Type-7 linear interpolation at `(n-1)*p` over **only the 24 unlabeled tasks**. Anchor cells show value and shadow counts `below/equal/above`. Anchors come from historical source states, so source-size-sensitive features are not directly exchangeable with the pinned shadow source.

## Notable distribution positions

| Metric | Shadow min / P25 / median / P75 / max | Task A | Production loss |
| --- | --- | --- | --- |
| Largest cluster share | 0.4 / 1 / 1 / 1 / 1 | 1 | 0.7692 |
| Median/top score | 0.1877 / 0.3206 / 0.384 / 0.4321 / 0.5865 | 0.6341 | 0.4076 |
| Ambiguous exact-symbol pressure | 0 / 0 / 0 / 0 / 0.2857 | 0 | 0.3077 |
| REQUIRED path share | 0 / 0.0769 / 0.1111 / 0.1467 / 0.5 | 0.1667 | 0.6154 |
| Directory dispersion | 0.1667 / 0.2452 / 0.3205 / 0.4286 / 0.6667 | 0.1667 | 0.4615 |
| Test path share | 0.0769 / 0.1111 / 0.1483 / 0.2 / 0.3571 | 0.1667 | 0.3846 |

Task A is unusually concentrated (median/top and within-50% exceed every shadow task) and fully connected, but its older, smaller source state limits transfer. The production loss has typical score concentration, not a notably low one. Its selection is split (10/13 in the largest component), has ambiguous exact-symbol pressure (4/13), a high REQUIRED share (8/13), and a test share above the shadow maximum (5/13). Two unlabeled tasks, M01 and C04, also combine disconnection with exact-symbol ambiguity. This is a plausible task-property pattern, not proof of token savings.

## Pairwise reading

- Concentration + coherence: Task A is high on both. The loss is disconnected but has ordinary concentration. A concentration-only gate would not explain this loss and might reject anchored shadow tasks.
- Concentration + ambiguity: repeated exact symbols occur in three shadow tasks; the loss is above their observed pressure, but its score concentration is not an outlier.
- Coherence + directory dispersion: the loss is split and above the dispersion P75. Legitimate cross-module tasks can also have many directories; graph connectivity is more interpretable than directory count.
- Specificity + concentration + coherence: the loss has `0.3846` VERY_STRONG-category paths versus Task A's `0.1667`. That category alone is misleading. Direct-evidence ratio is 1.0 for **both** labeled outcomes; broad term coverage and novel coverage also fail to separate them. Candidate/selected compression is confounded by the different source states.

## One shadow-only candidate

`coherence_and_exact_symbol_ambiguity` is a deliberately simple local counterfactual, **not enabled in AUTO**:

- No selected paths: BYPASS.
- Disconnected selection **and** any ambiguous exact-symbol path: BYPASS.
- Exactly one of those two conditions: UNCERTAIN.
- Neither: PASS.

It requires no learned weight or numeric percentile threshold. It treats the conjunction as suspicious, not as a proven predictor of provider input. Counterfactuals: Task A **PASS**; production loss **BYPASS**. Across the 24 **unlabeled** tasks: 20 PASS, 2 BYPASS, 2 UNCERTAIN. These are not correct/incorrect counts.

| Shadow task | Decision | Reasons |
| --- | --- | --- |
| N01 | PASS | - |
| N02 | PASS | - |
| N03 | PASS | - |
| N04 | PASS | - |
| M01 | BYPASS | DISCONNECTED_SELECTION, AMBIGUOUS_EXACT_SYMBOL |
| M02 | PASS | - |
| M03 | PASS | - |
| M04 | PASS | - |
| C01 | PASS | - |
| C02 | PASS | - |
| C03 | PASS | - |
| C04 | BYPASS | DISCONNECTED_SELECTION, AMBIGUOUS_EXACT_SYMBOL |
| T01 | PASS | - |
| T02 | PASS | - |
| T03 | UNCERTAIN | DISCONNECTED_SELECTION |
| T04 | PASS | - |
| G01 | PASS | - |
| G02 | PASS | - |
| G03 | PASS | - |
| G04 | UNCERTAIN | AMBIGUOUS_EXACT_SYMBOL |
| E01 | PASS | - |
| E02 | PASS | - |
| E03 | PASS | - |
| E04 | PASS | - |

### Manual-review cases

PASS with directory dispersion above shadow P75 or median/top below P25, and BYPASS despite an explicit path or unique exact-symbol hit, are flagged without changing decisions.

| Task | Decision | Review reason |
| --- | --- | --- |
| M01 | BYPASS | UNIQUE_EXACT_SYMBOL |
| M04 | PASS | HIGH_DIRECTORY_DISPERSION, LOW_SCORE_CONCENTRATION |
| C03 | PASS | LOW_SCORE_CONCENTRATION |
| C04 | BYPASS | UNIQUE_EXACT_SYMBOL |
| T01 | PASS | LOW_SCORE_CONCENTRATION |
| G01 | PASS | HIGH_DIRECTORY_DISPERSION |
| E01 | PASS | LOW_SCORE_CONCENTRATION |
| E02 | PASS | HIGH_DIRECTORY_DISPERSION, LOW_SCORE_CONCENTRATION |
| E03 | PASS | LOW_SCORE_CONCENTRATION |

M01 and C04 would be bypassed even though each has three unique exact-symbol paths. E02 passes despite both high dispersion and low concentration because the selected graph is connected and its exact-symbol pressure is zero; it also has explicit anchors. No explicit-path task was bypassed. These cases show why neither the rule nor a second policy is justified for production. A second candidate would mostly restate the same two anomalies or fit thresholds to two labels, so none is proposed.

## Full numeric distributions

Every fixed numeric feature has min, 25th percentile, median, 75th percentile, and max across the unlabeled corpus. Anchor cells include `value (shadow below/equal/above)`.

| Feature | Min | P25 | Median | P75 | Max | Task A | Production loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ambiguous_exact_symbol_paths` | 0 | 0 | 0 | 0 | 4 | 0 (0/21/3) | 4 (22/2/0) |
| `ambiguous_exact_symbol_pressure` | 0 | 0 | 0 | 0 | 0.2857 | 0 (0/21/3) | 0.3077 (24/0/0) |
| `ambiguous_only_exact_symbol_paths` | 0 | 0 | 0 | 0 | 4 | 0 (0/21/3) | 3 (22/1/1) |
| `ambiguous_only_exact_symbol_ratio` | 0 | 0 | 0 | 0 | 0.2857 | 0 (0/21/3) | 0.2308 (22/0/2) |
| `candidate_path_count` | 47 | 50 | 50 | 50 | 50 | 41 (0/0/24) | 50 (1/23/0) |
| `candidate_source_tokens` | 57892 | 101321.5 | 123024 | 133827.25 | 142783 | 33552 (0/0/24) | 139640 (22/0/2) |
| `direct_evidence_paths` | 2 | 7.5 | 10 | 13 | 17 | 12 (16/1/7) | 13 (17/2/5) |
| `direct_evidence_ratio` | 0.2857 | 0.625 | 0.8333 | 1 | 1 | 1 (17/7/0) | 1 (17/7/0) |
| `direct_query_term_coverage_ratio` | 0.1429 | 0.4533 | 0.5471 | 0.644 | 0.8462 | 0.5429 (12/0/12) | 0.5833 (15/0/9) |
| `direct_supported_query_terms_count` | 1 | 4.75 | 6 | 7 | 12 | 19 (24/0/0) | 28 (24/0/0) |
| `directory_dispersion` | 0.1667 | 0.2452 | 0.3205 | 0.4286 | 0.6667 | 0.1667 (0/1/23) | 0.4615 (21/0/3) |
| `distinct_newly_covered_useful_query_terms` | 3 | 5.75 | 7.5 | 10.25 | 17 | 26 (24/0/0) | 34 (24/0/0) |
| `evidence_specificity_path_counts.AMBIGUOUS_DIRECT` | 0 | 0 | 0 | 0 | 0 | 0 (0/24/0) | 0 (0/24/0) |
| `evidence_specificity_path_counts.GRAPH` | 0 | 0 | 0 | 0 | 1 | 0 (0/22/2) | 0 (0/22/2) |
| `evidence_specificity_path_counts.NONE` | 0 | 0 | 0 | 0 | 0 | 0 (0/24/0) | 0 (0/24/0) |
| `evidence_specificity_path_counts.STRONG` | 2 | 6 | 8.5 | 11 | 14 | 10 (15/2/7) | 8 (9/3/12) |
| `evidence_specificity_path_counts.VERY_STRONG` | 0 | 1 | 1 | 2 | 4 | 2 (15/4/5) | 5 (24/0/0) |
| `evidence_specificity_path_counts.WEAK` | 0 | 0 | 2 | 5 | 7 | 0 (0/7/17) | 0 (0/7/17) |
| `evidence_specificity_path_ratios.AMBIGUOUS_DIRECT` | 0 | 0 | 0 | 0 | 0 | 0 (0/24/0) | 0 (0/24/0) |
| `evidence_specificity_path_ratios.GRAPH` | 0 | 0 | 0 | 0 | 0.1 | 0 (0/22/2) | 0 (0/22/2) |
| `evidence_specificity_path_ratios.NONE` | 0 | 0 | 0 | 0 | 0 | 0 (0/24/0) | 0 (0/24/0) |
| `evidence_specificity_path_ratios.STRONG` | 0.2857 | 0.5 | 0.7183 | 0.8195 | 1 | 0.8333 (19/0/5) | 0.6154 (8/1/15) |
| `evidence_specificity_path_ratios.VERY_STRONG` | 0 | 0.0755 | 0.101 | 0.1295 | 0.4 | 0.1667 (20/0/4) | 0.3846 (23/0/1) |
| `evidence_specificity_path_ratios.WEAK` | 0 | 0 | 0.1667 | 0.3571 | 0.7143 | 0 (0/7/17) | 0 (0/7/17) |
| `graph_expanded_related_paths` | 0 | 0 | 0 | 1 | 5 | 0 (0/15/9) | 0 (0/15/9) |
| `graph_expanded_related_ratio` | 0 | 0 | 0 | 0.0728 | 0.5 | 0 (0/15/9) | 0 (0/15/9) |
| `largest_cluster_share` | 0.4 | 1 | 1 | 1 | 1 | 1 (3/21/0) | 0.7692 (3/0/21) |
| `locator_to_selected_source_ratio` | 0.025 | 0.035 | 0.0414 | 0.0522 | 0.0752 | 0.0266 (1/0/23) | 0.0357 (8/0/16) |
| `locator_tokens` | 87 | 180.5 | 237.5 | 306 | 445 | 159 (2/0/22) | 214 (10/0/14) |
| `median_selected_candidate_score` | 43.5 | 56.5 | 67.25 | 78.75 | 134 | 156 (24/0/0) | 183 (24/0/0) |
| `median_to_top_score_ratio` | 0.1877 | 0.3206 | 0.384 | 0.4321 | 0.5865 | 0.6341 (24/0/0) | 0.4076 (15/0/9) |
| `minimum_selected_candidate_score` | 25 | 32.75 | 46 | 57.25 | 71 | 74 (24/0/0) | 115 (24/0/0) |
| `non_test_selected_path_count` | 5 | 8 | 10 | 12 | 17 | 10 (10/5/9) | 8 (2/5/17) |
| `novel_coverage_efficiency` | 0.2143 | 0.4514 | 0.5833 | 0.7769 | 1.5 | 2.1667 (24/0/0) | 2.6154 (24/0/0) |
| `novel_coverage_path_ratio` | 0.1 | 0.3138 | 0.4167 | 0.5595 | 0.8 | 0.8333 (24/0/0) | 0.8462 (24/0/0) |
| `primary_selected_path_count` | 5 | 10 | 11.5 | 14 | 18 | 12 (12/3/9) | 13 (15/2/7) |
| `query_terms_count` | 7 | 10 | 12 | 13 | 19 | 38 (24/0/0) | 50 (24/0/0) |
| `rare_query_terms_count` | 0 | 1 | 1.5 | 4 | 6 | 8 (24/0/0) | 7 (24/0/0) |
| `related_selected_path_count` | 0 | 0 | 0 | 1 | 5 | 0 (0/15/9) | 0 (0/15/9) |
| `required_phase_path_ratio` | 0 | 0.0769 | 0.1111 | 0.1467 | 0.5 | 0.1667 (19/0/5) | 0.6154 (24/0/0) |
| `selected_directory_count` | 2 | 3 | 4 | 5.25 | 6 | 2 (0/4/20) | 6 (18/6/0) |
| `selected_induced_graph_cluster_count` | 1 | 1 | 1 | 1 | 4 | 1 (0/21/3) | 3 (21/1/2) |
| `selected_matched_query_terms_count` | 3 | 5.75 | 7.5 | 10.25 | 18 | 28 (24/0/0) | 34 (24/0/0) |
| `selected_matched_symbols_count` | 1 | 22.25 | 30 | 43 | 50 | 46 (18/1/5) | 92 (24/0/0) |
| `selected_path_count` | 7 | 10 | 12.5 | 14 | 19 | 12 (9/3/12) | 13 (12/3/9) |
| `selected_path_phase_counts.COVERAGE` | 1 | 3.75 | 4 | 5 | 9 | 8 (23/0/1) | 5 (15/6/3) |
| `selected_path_phase_counts.DEPTH` | 4 | 6.75 | 9 | 11.25 | 17 | 2 (0/0/24) | 0 (0/0/24) |
| `selected_path_phase_counts.REPAIR` | 0 | 0 | 0 | 0 | 1 | 1 (21/3/0) | 0 (0/21/3) |
| `selected_path_phase_counts.REQUIRED` | 0 | 1 | 1 | 2 | 7 | 2 (14/5/5) | 8 (24/0/0) |
| `selected_paths_without_novel_query_terms` | 2 | 5 | 6.5 | 9 | 13 | 2 (0/1/23) | 2 (0/1/23) |
| `selected_range_phase_counts.COVERAGE` | 1 | 3.75 | 4 | 5 | 9 | 8 (23/0/1) | 5 (15/6/3) |
| `selected_range_phase_counts.DEPTH` | 6 | 11 | 17.5 | 24.5 | 43 | 2 (0/0/24) | 0 (0/0/24) |
| `selected_range_phase_counts.REPAIR` | 0 | 0 | 0 | 0 | 1 | 1 (21/3/0) | 0 (0/21/3) |
| `selected_range_phase_counts.REQUIRED` | 0 | 1 | 2 | 4 | 9 | 2 (8/7/9) | 11 (24/0/0) |
| `selected_score_within_top_fraction.50_percent` | 0.0714 | 0.1511 | 0.2679 | 0.3885 | 0.5833 | 0.6667 (24/0/0) | 0.3077 (15/0/9) |
| `selected_score_within_top_fraction.75_percent` | 0.0526 | 0.0909 | 0.1111 | 0.1456 | 0.2857 | 0.1667 (20/0/4) | 0.1538 (18/2/4) |
| `selected_score_within_top_fraction.90_percent` | 0.0526 | 0.0755 | 0.0871 | 0.1111 | 0.1429 | 0.0833 (9/3/12) | 0.0769 (6/3/15) |
| `selected_source_tokens` | 3484 | 5795.25 | 5935.5 | 5953.5 | 5999 | 5983 (21/0/3) | 5999 (23/1/0) |
| `selected_to_candidate_source_ratio` | 0.0284 | 0.044 | 0.0478 | 0.0566 | 0.0976 | 0.1783 (24/0/0) | 0.043 (5/0/19) |
| `signal_counts.changed_relevant` | 0 | 0 | 0 | 0 | 0 | 0 (0/24/0) | 0 (0/24/0) |
| `signal_counts.exact_symbol` | 0 | 1 | 1 | 2 | 7 | 2 (14/5/5) | 9 (24/0/0) |
| `signal_counts.explicit_path` | 0 | 0 | 0 | 0 | 1 | 0 (0/21/3) | 0 (0/21/3) |
| `signal_counts.family_term` | 0 | 2.75 | 5 | 9.5 | 21 | 27 (24/0/0) | 26 (24/0/0) |
| `signal_counts.filename_term` | 0 | 2 | 3 | 4 | 8 | 8 (23/1/0) | 8 (23/1/0) |
| `signal_counts.import_neighbor` | 5 | 7.75 | 10 | 12 | 18 | 10 (10/4/10) | 8 (6/2/16) |
| `signal_counts.import_term` | 0 | 6 | 10.5 | 15.25 | 28 | 38 (24/0/0) | 31 (24/0/0) |
| `signal_counts.path_term` | 0 | 0 | 0 | 2 | 9 | 0 (0/15/9) | 3 (19/2/3) |
| `signal_counts.related_test` | 1 | 1.75 | 2 | 2 | 5 | 2 (6/15/3) | 5 (22/2/0) |
| `signal_counts.reverse_import_neighbor` | 4 | 7.75 | 9 | 11.25 | 17 | 9 (11/2/11) | 13 (19/2/3) |
| `signal_counts.source_term` | 0 | 4.5 | 8 | 11 | 18 | 8 (8/6/10) | 9 (14/1/9) |
| `signal_counts.symbol_term` | 0 | 10.5 | 12 | 17 | 31 | 35 (24/0/0) | 61 (24/0/0) |
| `signal_counts.tested_source` | 5 | 7 | 9 | 12 | 17 | 8 (7/4/13) | 8 (7/4/13) |
| `signal_counts.trace_path` | 0 | 0 | 0 | 0 | 0 | 0 (0/24/0) | 0 (0/24/0) |
| `test_selected_path_count` | 1 | 1.75 | 2 | 2 | 5 | 2 (6/15/3) | 5 (22/2/0) |
| `test_selected_path_ratio` | 0.0769 | 0.1111 | 0.1483 | 0.2 | 0.3571 | 0.1667 (13/3/8) | 0.3846 (24/0/0) |
| `top_candidate_score` | 97 | 156 | 183.5 | 236 | 389 | 246 (19/0/5) | 449 (24/0/0) |
| `unique_exact_symbol_path_ratio` | 0 | 0.0536 | 0.0909 | 0.1295 | 0.4 | 0.1667 (20/0/4) | 0.3846 (23/0/1) |
| `unique_exact_symbol_paths` | 0 | 0.75 | 1 | 2 | 4 | 2 (15/4/5) | 5 (24/0/0) |
| `useful_query_term_coverage_ratio` | 0.375 | 0.5958 | 0.7482 | 0.894 | 1 | 0.8 (14/0/10) | 0.7083 (10/0/14) |
| `useful_query_terms_count` | 6 | 9 | 11 | 13 | 19 | 35 (24/0/0) | 48 (24/0/0) |
| `weak_only_paths` | 0 | 0 | 2 | 5 | 7 | 0 (0/7/17) | 0 (0/7/17) |
| `weak_only_ratio` | 0 | 0 | 0.1667 | 0.375 | 0.7143 | 0 (0/7/17) | 0 (0/7/17) |
| `weak_only_supported_query_terms_count` | 0 | 1 | 2 | 3 | 7 | 9 (24/0/0) | 6 (22/1/1) |

## Limits and next prospective step

These 24 questions have no real token outcome. The two labeled outcomes use different historical source states from the shadow corpus. High scores, test-path counts, and apparent specificity can reward generic identifiers; graph links do not prove a path is needed. The shadow decision's manual-review cases remain unresolved. Keep production AUTO, prompt construction, selector, locator, event semantics, and frozen Phase 22 artifacts unchanged. The next step is to pre-register a small set of representative read-only tasks, review the flagged shadow cases, and seek separate authorization for prospective isolated A/B runs; only then consider a production-only quality policy. Native command-output-size telemetry remains deferred because existing JSONL evidence is insufficient.
