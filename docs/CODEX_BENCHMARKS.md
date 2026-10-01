# Real Codex A/B Context Benchmark

Phase 22 measures whether Middle_Man changes Codex's repository exploration **without lowering correctness**. Task A v1/v2 were tested against real Codex. The first v3 pair was infrastructure-invalid and diagnostic-only; later frozen-corpus v3 pairs were infrastructure-valid but failed correctness on both sides. Task A v4 has one infrastructure-valid, correctness-passing real pair; Phases 22.8 and 22.9 are local-only follow-ups. This benchmark is separate from simulated Lab benchmarks and local Context Pack quality fixtures; it does not measure plan quota or billing.

## Run It

```powershell
.venv\Scripts\python.exe -m middle_man codex benchmark list
.venv\Scripts\python.exe -m middle_man codex benchmark preflight --repo . --json
.venv\Scripts\python.exe -m middle_man codex benchmark preflight --repo . --windows-sandbox unelevated --snapshot-root "C:\path\outside\Middle_Man" --json
.venv\Scripts\python.exe -m middle_man codex benchmark run-all --repo . --dry-run
.venv\Scripts\python.exe -m middle_man codex benchmark run-all --repo . --confirm-external-service
.venv\Scripts\python.exe -m middle_man codex benchmark report <run-id> --repo .
.venv\Scripts\python.exe -m middle_man codex benchmark report <run-id> --repo . --json
.venv\Scripts\python.exe -m middle_man codex benchmark overlap <run-id> --repo .
```

Live runs send repository-derived context to Codex's external service and require the explicit confirmation flag. Normal pytest and `--dry-run` never call Codex. The default invocation explicitly requests `gpt-6-sol` with high reasoning effort; the selected model/effort remain marked **not event-verified** unless a Codex event reports them. `codex exec --json` is the documented structured event surface, including `turn.completed.usage`: [OpenAI Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Per-run `--ignore-user-config` is also documented there.

## Isolation and Tasks

Each task gets two independently committed working copies in a fresh directory under system temp by default, or under an explicitly configured `--snapshot-root` outside this repository. The preflight rejects any snapshot parent that inherits an `AGENTS.md`; a repository-local ignored directory is not a valid baseline location while the root `AGENTS.md` applies. Sanitized reports live under Git-ignored `.middle_man_cache/codex_benchmarks/<run-id>/`; temp working copies are retained for inspection. The source files have a common SHA-256 fingerprint, excluding only the intentional `AGENTS.md` routing difference. Task A now uses exact Lab commit `284c4451ad9213f4f27f6d534eac8be2484c2f9a` instead of moving HEAD. The source commit and tree fingerprint appear in future run/pair JSON and human reports. Edit tasks use deterministic standalone fixtures.

Baseline has no project `AGENTS.md` and launches Codex with `--ignore-user-config`, so it should explore natively. Optimized has the normal Middle_Man `AGENTS.md` and explicitly configures a snapshot-scoped local MCP command. Both sides use the same task prompt, Codex version, model, reasoning effort, sandbox, timeout, and default network policy. Run order alternates: A baseline/optimized, B optimized/baseline, C baseline/optimized. `run-all` now selects A v4, B, and C; A v1/v2/v3 remain individually addressable for historical compatibility and cannot be aggregated with v4. A baseline MCP call invalidates the pair. An optimized run without snapshot-scoped Middle_Man usage records also invalidates it. The runner runs a no-inference infrastructure preflight before any pair, and stops after an infrastructure-invalid pair. Both sides explicitly request the same `windows.sandbox` implementation (`elevated` by default); `unelevated` requires the explicit CLI choice. No danger-full-access or unsandboxed fallback is used. The local preflight checks CLI version, a quoted-space/apostrophe path, baseline invocation isolation, exact optimized MCP config, a real snapshot-scoped stdio MCP call, primary-log non-contamination, sandboxed read, read-only write denial, and workspace-write. Model/effort remain unverified until a real Codex event reports them.

- **A v1, preemption (historical):** Read-only conceptual prompt, but a literal-marker evaluator. Its valid pair remains FAIL/FAIL and is never rescored.
- **A v2, preemption (historical):** Read-only prompt explicitly asks for concrete symbols/components, without revealing expected values. Both sides receive the same `--output-schema` JSON object. Exact structured fields, a nonempty explanation, and unchanged Git state gate correctness.
- **A v3, preemption (historical):** The same engineering prompt and structured fields use evaluator v3, which accepts qualified identifier segments and normalized test paths without substring loopholes. Its historical artifacts and evaluator remain frozen.
- **A v4, preemption (current run-all default):** A separately versioned prompt and schema ask for a specific abstraction in each field: victim policy class, memory controller component, scheduled WorkKind member, preserved request output counter, and proving test file. Its evaluator accepts bare or qualified whole identifiers, not related methods or composite prose. Its first real pair passed correctness on both sides but reported higher optimized input.
- **B, OAuth expiry:** A fixture callback accepts expired state. Visible tests fail initially; hidden boundary/replay/skew tests run after each Codex attempt. Production and tests must be updated.
- **C, uploads:** Add a configurable, case-insensitive filename-extension allowlist across configuration, shared validation, service, and tests. Hidden behavior tests check allowed, rejected, custom, size-limit, and duplicate cases.

For edit tasks, deterministic tests and requested-file changes gate correctness. A lower-read optimized run is **not** a win if it fails behavior tests. No composite score is used. Git status is captured before and immediately after Codex; evaluator tests are added only afterward.

## Measurements

The parser counts completed Codex JSONL command and MCP events, recognizes explicit native read commands and search/listing/Git inspections, and records unique explicit file paths and rereads where observable. Shell syntax, failed commands, and hidden tool activity can limit this count; missing observations are not guessed. `turn.completed.usage` supplies Codex-reported input, cached-input, output, and reasoning-output tokens when present. A direct total-token field remains `null` if absent. Cached input is not added to input again.

For every Context Pack, the local metadata log stores pack fingerprint, candidate/selected source estimates, result estimate, and sanitized excerpt path/content-hash/line ranges with per-line byte lengths, **not source text**. Across packs, `(path, content hash, line number)` identifies the same delivered source line. First delivery counts toward unique bytes; every later delivery counts toward repeated bytes. Overlap ratio is `repeated / (unique + repeated)` bytes. Estimated tokens use `ceil(UTF-8 bytes / 4)`. When delivery ranges are available, non-source overhead is `sum(result estimates) - estimated actually delivered source bytes / 4` (rounded up); it includes JSON/result wrappers and metadata, so it is not an exact provider-token charge. The unique-source delivery ratio is estimated unique source tokens divided by estimated Context Pack result tokens. These are Middle_Man estimates, separate from Codex-reported usage.

## Native Windows Infrastructure Check

On this machine, the installed CLI is `codex-cli 0.155.0-alpha.16.3`. Its `codex doctor --json` reports `sandbox.helpers` failed: elevated provisioning recorded `helper_unknown_error`; the remediation is to repair or reinstall the Codex CLI from an approved distribution. Microsoft Defender interference is a warning, not a proven cause. The explicit elevated preflight fails with `apply deny-read ACLs` even for a repository-local read, so this is not solely a `%TEMP%` path problem. OpenAI recommends elevated native Windows sandbox and documents one-time administrator-approved setup for sandbox users, firewall rules, and logon rights: [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox), [configuration basics](https://learn.chatgpt.com/docs/config-file/config-basic). Do not treat elevated as working until it passes the preflight after repair/setup.

The documented `unelevated` fallback starts, but the original `%TEMP%` location denied access to Python-created disposable files. An explicitly chosen sibling snapshot root outside Middle_Man's `AGENTS.md` ancestry passed the read, read-only-denial, write, and local stdio MCP/root-log checks. The preflight creates children with `Path.mkdir`, matching the benchmark snapshot creation; `TemporaryDirectory` produced a different Windows ACL and was unsuitable here. This is local infrastructure validation, not a valid A/B benchmark result. Use `--windows-sandbox unelevated --snapshot-root <absolute-existing-parent>` only as an explicit choice after reviewing the weaker sandbox boundary.

If neither native sandbox is reliable, [OpenAI's WSL2 guidance](https://learn.chatgpt.com/docs/windows/wsl) is the secondary path. This machine currently lists only the `docker-desktop` WSL distribution, not a development distro. A WSL2 migration would need Linux Codex and Python dependencies, `bubblewrap`, a Linux-path Middle_Man MCP command, Linux Git snapshots, and a repo under the Linux filesystem (recommended over `/mnt/c`), with stdio and root isolation retested. No migration has been made.

## Valid Task A v1 Result

The first infrastructure-valid A/B pair used the v1 prompt/evaluator and explicit Windows `unelevated` sandbox. Both sides were infrastructure-valid and left their snapshots and the primary repository clean. The stored result is **FAIL / FAIL**; neither answer supplied all five literal evaluator markers. The answers may be substantively useful, but historical results are immutable and are not rescored.

| Metric | Baseline | Optimized |
| --- | ---: | ---: |
| Native tool calls | 16 | 12 |
| Explicit file reads (manual sanitized-trace audit) | 9 | 10 |
| Unique files / rereads | 9 / 0 | 10 / 0 |
| Search / listing calls | 6 / 1 | 2 / 0 |
| Middle_Man MCP calls | 0 | 4 |
| Codex-reported input tokens | 144,903 | 391,753 |
| Cached input tokens | 118,656 | 345,600 |
| Output / reasoning-output tokens | 4,041 / 1,891 | 3,576 / 1,825 |
| Elapsed seconds | 92.9 | 95.8 |

The optimized run reduced native calls and search/listing operations, **but increased file reads and Codex input tokens substantially**. Its one Context Pack had candidate/selected estimates of 11,133/5,117. Overlap was unavailable because the historical snapshot imported its own older MCP implementation, which lacked delivery-range records. The old native parser also missed doubled-backslash Windows paths; 9 baseline unique files were recovered by manual trace audit. Neither issue changes the frozen outcome. **No Middle_Man token-saving claim follows.**

An earlier suite attempt was infrastructure-invalid because the elevated Windows sandbox failed with `apply deny-read ACLs`, optimized MCP used the primary repository root, and a baseline called another MCP server. It is diagnostic only, not an A/B result.

## Phase 22.1: Local Candidate Optimization

The benchmark runner now pins the current MCP server implementation with isolated Python and an explicit source root, while serving the historical target snapshot. Usage schema v2 records package version, schema version, a code fingerprint, and source-free delivery ranges. A local SDK subprocess test places an intentionally incompatible `middle_man` package in the target snapshot and confirms that the current server still runs. Optimized future runs use the `codex-core` profile, and results record tool profile plus task/evaluator version. Mixed Task A versions are rejected before a live suite starts.

The default Codex-core profile exposes five tools: `middleman_context`, `middleman_expand_context`, `middleman_session_handoff`, `middleman_compact_output`, and `middleman_project_state`. The full profile preserves all ten preexisting tools. `middleman_context` directly builds a bounded, redacted Context Pack, avoiding a mandatory find-then-pack sequence. Its smaller model-visible representation omits duplicated ranking, hashes, and metrics while preserving the canonical pack and source. Session-local metadata tracks delivered path/hash/line identity; repeated selections return only unseen lines, and core expansion returns only new ranges. The ledger stores no raw source. `force_replay` remains an internal direct-Gateway diagnostic option, not a Codex-core tool argument. Diagnostic `middleman_find_context` remains in full.

Run the repeatable local measurement without Codex:

```powershell
.venv\Scripts\python.exe scripts\measure_phase22_1.py
```

On the committed Task A v1 source snapshot, using the same BALANCED pack for both representations, the official MCP SDK tool-list estimate was **1,643** tokens for ten full definitions and **835** for five core definitions (49.2% less). The selected source estimate was **4,918** tokens in both responses; fingerprint, source path/ranges/text, warnings, and selected-token metrics matched. Full/core result estimates were **14,125 / 5,710** tokens, with estimated metadata overhead **9,207 / 792** (91.4% less). The old local route's three successful result payloads (project state, find, full pack) totaled **18,549** estimated tokens; the handoff call returned an error and its result size is not included. The new one-call core result was **5,710**. An identical second core request returned zero excerpts (71 estimated response tokens); overlap metadata was available. These values are `ceil(UTF-8 bytes / 4)` heuristics from a fresh temporary snapshot, **not Codex-reported input tokens**. The historical 11,133/5,117 estimates are from a different query/mode/invocation and must not be silently substituted for this simulation.

The optional experimental `codex debug prompt-input` diagnostic was skipped because its offline behavior was not established. No external Codex call was made for Phase 22.1. The authorized Task A v2 pair has since completed; its frozen result and the local Phase 22.2 candidate are documented below.

## Valid Task A v2 Result (Frozen)

Both Task A v2 sides were infrastructure-valid under the explicit Windows unelevated sandbox. The exact v2 structured evaluator marked **baseline FAIL / optimized FAIL**. It rejected qualified or composite identifiers even when they named relevant components; these answers and artifacts remain frozen and are not rescored.

| Metric | Baseline | Optimized |
| --- | ---: | ---: |
| Codex input / cached input tokens | 84,350 / 52,608 | 122,094 / 87,040 |
| Output / reasoning-output tokens | 755 / 210 | 1,209 / 476 |
| Elapsed seconds | 30.116 | 34.328 |
| Native calls / explicit reads / unique files / rereads | 5 / 7 / 7 / 0 | 8 / 6 / 6 / 0 |
| Search / listing calls | 1 / 1 | 1 / 0 |
| Middle_Man MCP calls | 0 | `middleman_context` x1 |

The optimized Context Pack estimated 17,866 candidate, 5,840 selected-source, and 7,015 MCP-result tokens. Unique delivered source was about 5,836 estimated tokens, with **zero repeated source and 0% overlap**; non-source result overhead was about 1,179. Nonetheless it omitted preemption, memory-control, and scheduling implementation evidence. Codex then made **six native fallback reads**. Optimized Codex input was higher, so **there was no real token saving**.

## Phase 22.2: Local Selection Candidate

Phase 22.2 adds structured match signals, conservative bounded-prefix lexical-family matching, frequency-aware query terms, capped graph contributions, verified source-term hints, and a two-pass coverage/depth allocator. Strong connected source anchors and the best directly related proving test receive priority; candidate cost matters, but exact path/symbol evidence remains stronger. Candidate-level diagnostics retain matched terms, symbols, proposed ranges, cost, covered signals, budget state, and omission reason in local/debug records. They are **not included in Codex-core**. The source budget remains 6,000 estimated tokens; the internal candidate pool is wider.

Task A v3 uses the v2-equivalent prompt and the same structured fields, but evaluator version 3 accepts whole qualified identifier segments and normalized test paths without substring matching. It is never aggregated with v1/v2. The seven required source units below are benchmark metadata only and never feed the selector: victim policy, memory controller, block release, scheduling recomputation, work enum, request output state, and proving test.

A local before/after run used the same frozen committed-source snapshot, BALANCED mode, and 6,000-token budget. These are fixture-based `ceil(UTF-8 bytes / 4)` estimates, **not Codex usage**:

| Local measure | Phase 22.1 selector | Phase 22.2 selector |
| --- | ---: | ---: |
| Candidates considered | 10 | 50 |
| Selected source tokens | 5,773 | 5,847 |
| Required file recall | 2/7 | 7/7 |
| Required identifier recall in delivered text | 2/7 | 7/7 |
| Selected required-source tokens | 1,346 | 4,187 |
| Selected non-required-source tokens | 4,427 | 1,660 |

The new pack includes `middle_man/lab/preemption.py`, `memory_control.py`, `memory.py`, `scheduler.py`, `work.py`, `request.py`, and `tests/test_phase_7_preemption.py`. Other selected files are engine, metrics, runner, trace, and events. Budget omissions and out-of-cluster candidates are visible in local diagnostics. Three unrelated bounded fixtures (authentication callback, queue cancellation, upload validation) all retained required files and symbols; Phase 15 quality fixtures remain green. The Codex-core profile remains five tools with an 835-token tool-definition estimate. **No external Codex inference occurred in Phase 22.2, and there is no new real A/B result or token-saving claim.**

## Phase 22.3: Frozen Task A Corpus and Local Parity

The authorized Task A v3 pair is **INVALID_PAIR / diagnostic only**. Its baseline had ` D AGENTS.md` before Codex execution, failing the benchmark's clean-start requirement. The one-off v3 recorder bypassed the existing `run_one()` status check: it copied tracked guidance into baseline, deleted it, and launched directly. Neither historical answer nor artifact is rescored or modified. The optimized side was individually infrastructure-valid and passed structured correctness, but its pack contained **0/7** required implementation areas. Codex then read `tests/test_phase_7_preemption.py` and seven Lab files (`preemption.py`, `scheduler.py`, `work.py`, `memory.py`, `request.py`, `engine.py`, `memory_control.py`) natively. The answer came from fallback, not the pack. Its candidate/selected/result estimates were 88,879/6,339/8,531; delivered source was 6,328 unique and zero repeated, with 0% overlap and 2,203 estimated result overhead. No valid A/B or token-saving conclusion follows.

Task A now extracts a fixed, verified pre-Gateway Lab commit: `284c4451ad9213f4f27f6d534eac8be2484c2f9a` (`feat: add Middle_Man Lab benchmarks and visualization`). Its tree contains victim policy, memory controller, KV release, scheduler recomputation, `RECOMPUTE`, request `output_generated`, and the Phase 7 proving test. It has no `middle_man/gateway/codex_benchmark/`, MCP/Gateway package, Phase 22 tests, or `docs/CODEX_BENCHMARKS.md`. Extraction validates the SHA as a commit and never substitutes HEAD. Baseline is materialized without `AGENTS.md`; optimized adds guidance before its own initial commit. Both start Git-clean, have identical source fingerprints, and report the source commit and source-tree fingerprint. The canonical `run_one()` checks Git status before command construction and immediately before process creation; tests spy on the launcher for deleted guidance, modified source, and untracked files on either side.

With the exact Task A v3 prompt on this pinned corpus, direct `ContextBuilder`, direct `MCPGateway.context`, and fresh stdio `middleman_context` calls with default and explicit BALANCED/6000 arguments agree on source fingerprint, pack fingerprint, selected paths/ranges/text, selected estimate, and warnings. All deliver **7/7 required files and 7/7 identifiers** at 5,891 estimated selected-source tokens. The stdio server uses the current Middle_Man implementation, not a historical snapshot package. On this same corpus, the historical Phase 22.1 selector at commit `886a687` delivers **4/7 files, 4/7 identifiers, 4,693 tokens**; Phase 22.2 delivers **7/7, 7/7, 5,891 tokens**. The earlier 2/7-vs-7/7 local comparison used a different frozen source and is not silently reused.

Query wording is a material variable even on the pinned corpus (file/identifier recall, estimated selected tokens):

| Local query | Files | Identifiers | Tokens |
| --- | ---: | ---: | ---: |
| Exact Task A v3 prompt | 7/7 | 7/7 | 5,891 |
| `Find the KV preemption implementation and tests` | 5/7 | 3/7 | 3,521 |
| `Need context for victim selection, KV release, recomputation, and output preservation` | 6/7 | 6/7 | 5,875 |
| `inspect the Middle_Man architecture` | 0/7 | 0/7 | 1,126 |

On **committed current HEAD** with the exact prompt, required recall is still 7/7, but its top 20 candidates include six Gateway files (two in `codex_benchmark/`), two MCP files, and zero Phase 22 test/docs files. Moving HEAD thus changes the candidate pool and includes self-benchmark machinery; it does not alone explain a 0/7 exact-prompt pack. The historical optimized v3 usage record contains only query fingerprint `2adb2f9fda5f05e1e4b5e4a641c283d24a24693911c16fb9dd3d0610a58dc05b`. Its exact query text and arguments were not retained, so we cannot establish which reformulation caused that specific pack. Corpus contamination and query reformulation were uncontrolled historical variables, not proven individual causes.

Phase 22.3's explicitly identified benchmark MCP launches wrote **benchmark-only** source-free receipts in the snapshot's ignored cache. They contained run/task/mode, normalized redacted query terms and identifiers, explicit arguments, query signature, repository/source/selector/server fingerprints, candidate scores, selected/omitted paths and reasons, line ranges, cost estimates, and pack fingerprint. At that phase, receipts contained neither prompt text nor source text; Phase 22.4 adds a bounded redacted task field for future benchmark-only sessions. Normal `mcp_usage.jsonl` remains metadata-only. Codex-core guidance asks for the concrete engineering request; production ranking receives no evaluator-only paths, identifiers, or answer metadata. No external Codex call occurred in Phase 22.3.

## Valid Frozen-Corpus Task A v3 Pair (Historical)

The later Task A v3 pair on source commit `284c4451ad9213f4f27f6d534eac8be2484c2f9a` and source fingerprint `a548097a4294fd67b2d42a5ab616c19b8ab226d702a406fa36f588873d0a0c1b` was **infrastructure-valid on both sides**, unlike the earlier invalid v3 diagnostic pair. The quality gate is **TASK_FAILURE**: both structured answers failed. Baseline missed memory control, recomputation, and output preservation; optimized missed output preservation. The evaluator and artifacts are unchanged.

| Metric | Baseline | Optimized |
| --- | ---: | ---: |
| Codex input / cached input tokens | 88,815 / 60,416 | 88,159 / 55,040 |
| Output / reasoning-output tokens | 685 / 183 | 930 / 398 |
| Elapsed seconds | 23.870 | 27.765 |
| Native calls / explicit reads / unique files / rereads | 9 / 7 / 7 / 0 | 5 / 4 / 4 / 0 |
| Search / listing calls | 1 / 1 | 1 / 0 |
| Middle_Man MCP calls | 0 | `middleman_context` x1 |

The optimized pack estimated 33,030 candidate, 5,960 selected-source, and 6,974 MCP-result tokens, with approximately 5,955 unique delivered source, zero repeated, and 1,019 non-source overhead. It covered **6/7 required files and 6/7 identifiers**: `middle_man/lab/scheduler.py` was omitted for the 6,000-token budget (estimated cost 549). Codex then read `scheduler.py`, `engine.py`, `tests/test_phase_7_preemption.py`, and `request.py` natively; the latter three had already been partially delivered. Input totals were nearly equal, and both answers failed correctness. **This is not a Middle_Man win or a real token-saving result.**

## Phase 22.4 Local-Only Follow-up

The raw optimized v3 query was not retained. The test suite labels its closest reconstruction from the receipt's normalized terms and identifiers as `RECEIPT_DERIVED_QUERY_FIXTURE`, not a historical exact query. With BALANCED/6000 on the same pinned corpus, the pre-repair selector gave 6/7 files and identifiers at 5,960 tokens, omitting `scheduler.py`. The final bounded repair pass now swaps out the 557-token `runner.py` range for the 549-token `scheduler.py` range, yielding 7/7 at 5,952. This is a local reproduction, not a re-run or rescore of the real pair.

| Local query variant | Files | Identifiers | Selected-source estimate |
| --- | ---: | ---: | ---: |
| Exact Task A v3 prompt | 7/7 | 7/7 | 5,891 |
| Short KV-preemption query | 5/7 | 3/7 | 3,521 |
| Behavior-focused | 7/7 | 7/7 | 5,475 |
| Receipt-derived fixture | 7/7 | 7/7 | 5,952 |
| Reordered phrasing | 7/7 | 7/7 | 5,544 |
| Agent-style phrasing | 7/7 | 7/7 | 5,693 |
| Generic architecture query | 0/7 | 0/7 | 1,126 |

The five behavior-preserving variants fit the 6,000-token budget and reach 7/7; the short query omits major behaviors, and the generic query remains intentionally weak. Repair swaps were: receipt-derived `runner.py` to `scheduler.py`; behavior `cli/main.py` to `preemption.py`; reordered `runner.py` to `work.py`; agent-style `cli/main.py` to `scheduler.py`. Exact, short, and generic made no swap. Three unrelated bounded auth, queue, and upload allocator fixtures each trigger a one-way repair; explicit-path and required-test negatives remain protected.

Codex-core remains five tools (851 estimated definition tokens, versus the historical 835 before changed guidance). A 16-excerpt receipt-derived core JSON result measures 6,910 estimated tokens without and 6,996 with the `complete_file` hint (+86); selected source is unchanged. Repeated initial context sends no excerpts, and core full-file expansion after a partial excerpt returns only unseen lines. Explicit benchmark receipts can now store up to 4,096 characters of redacted task text; ordinary usage logs and normal sessions do not. Run IDs are unique or passed explicitly by the suite, not inferred from `artifacts`. **No external Codex call occurred in Phase 22.4, no historical artifact changed, and no new real token-saving claim is made.**

## Phase 22.5: Local Budget-Control and Delivery Audit

The latest real pinned-corpus Task A v3 pair (after the earlier pair above) is frozen and **infrastructure-valid / TASK_FAILURE**. Both structured answers failed recomputation and output preservation. Baseline/optimized Codex input was **411,731 / 272,552**, cached input **373,888 / 229,248**, output **3,349 / 1,961**, reasoning output **1,519 / 584**, and elapsed time **110.945s / 89.702s**. Optimized made two `middleman_context` and two `middleman_expand_context` calls. Its first context requested **9,000** tokens, selected **8,223** estimated source tokens, and covered **7/7** required files and identifiers with no repair. Its second context requested **11,000**. Thus this real pair did **not** execute the intended fixed-6,000 initial-context experiment. The lower optimized input in one pair with both answers wrong, different cached input, and uncontrolled requested budgets is **not a token-saving claim**.

The historical usage log measured **14,334 unique** and **3,322 repeated** estimated source tokens (18.8% overlap) across the two contexts and two expansions. Query-signature reconstruction from the retained redacted second task and explicit arguments proves that the second context used `force_replay=True`; `force_replay=False` does not match its recorded signature. The second call therefore deliberately bypassed session-local replay suppression. The old schema did not record a server session ID, so historical process continuity cannot be proven; it is not necessary to invoke a ledger bug to explain the repetition. A local pinned-corpus same-Gateway replay with the recorded 9,000/11,000 requests repeats source when replay is on; the same sequence with replay off has zero repeated delivered source even though the second pack selects source. Expansions add only unseen lines in that local sequence. Local replay overlap need not equal the real 18.8% because the recorded run ordered expansions before its second context, while the Phase 22.5 fixture places the second context before expansions.

Future optimized benchmark launches pass `--benchmark-context-budget 6000` and `--benchmark-expansion-budget 12000`. The server builds every `middleman_context` at no more than 6,000 without rejecting 9,000/11,000 requests; receipts and usage distinguish requested, effective, and cap, and core results expose compact budget metadata. Explicit expansion can grow the cumulative pack up to its separate 12,000 ceiling. Normal MCP sessions still accept requests up to 12,000. The runner marks optimized infrastructure invalid if successful initial contexts lack verified effective-budget evidence or exceed/mismatch the configured cap. Usage schema v3 records source-free `server_session_id`, call sequence, and ledger before/after counts; future reports display all observed session IDs and native read MCP coverage (`ABSENT_FROM_MCP`, `PARTIAL_IN_MCP`, `COMPLETE_IN_MCP`). The ledger remains session-local and source-free. **No new external Codex call or A/B result occurred in Phase 22.5; old artifacts and the Task A v3 evaluator remain unchanged.**

## Phase 22.6: Local Codex-core Replay Hardening

The historical second context call used `force_replay=True`, explaining its repeated source without proving a ledger defect. The current Codex-core `middleman_context` tool no longer exposes that argument or another replay control; direct Python Gateway calls retain replay only for explicit diagnostics. Future optimized benchmark traffic with successful replay-enabled context usage is infrastructure-invalid under the benchmark policy. The normal same-task path remains context then expansion; a materially new task may call context again. Native reads remain valid.

An official local stdio MCP test confirmed exactly five Codex-core tools and no `force_replay` in the context tool definition. The definition estimate decreased from **851 to 824** heuristic tokens. On the pinned Task A corpus, one server handled first/second requested budgets **9,000/11,000**, each effectively **6,000**, followed by engine/request expansions. The first pack reached **7/7** required files and identifiers at **5,891** selected tokens. The second selected **5,805** tokens with a different fingerprint; the two selections shared **176** path/hash/line identities, yet actual delivered overlap across all four calls was **0 bytes / 0%**. Complete-file reselection (`preemption.py`) sent no old source; partial-file overlap (`engine.py`) sent only new lines. Session ID remained constant, sequences were 1-4, and ledger counts increased only for unseen lines. A separate direct-Gateway replay test deliberately resent source and triggered the benchmark guard. Normal 12,000-token non-benchmark behavior, metadata-only usage, and Phase 22.5 receipts remain intact. **No external Codex call, historical rescore, or token-saving claim was made.**

## Local Preflight Path Fix (Post-22.6)

An attempted real Task A v3 pair stopped in the canonical no-inference preflight **before either external `codex exec` call**. Sandbox PowerShell started in `System32`, so relative `marker.txt` commands checked the wrong location. The preflight now constructs all read, read-only write, and workspace-write commands with a resolved absolute marker path inside the disposable root, represented as a PowerShell single-quoted literal with apostrophes doubled. It retains `-C <root>`, the containment check, and all three permission assertions; it no longer depends on the shell's starting directory.

An absolute-path retry under a nested `%TEMP%` parent still failed because the unelevated sandbox could not access that parent's disposable marker. Using the previously validated Desktop sibling snapshot parent, the real local preflight passed: read allowed, read-only write blocked, workspace write allowed, snapshot-scoped MCP root/log verified, and primary MCP usage log unchanged. This was **preflight only**: no new A/B pair, benchmark result artifact, historical rescore, or external inference call was produced.

## Task A v4: Local Contract Audit

The latest controlled v3 pair (`20260930T082418Z-e6523494`) was infrastructure-valid on both sides but **TASK_FAILURE** on both. Baseline and optimized each failed `recomputation_symbol` and `output_preservation_symbol`. The optimized run made one 6,000-budget `middleman_context` call, delivered **7/7 required files and 7/7 identifiers** at 5,891 estimated selected-source tokens, and made three native fallback reads, none for an absent file. Retrieval failure is therefore not the immediate explanation for these two structured failures. Baseline/optimized Codex input was **83,780 / 186,395**; both answers failed, so there is **no token-saving claim**.

The v3 prompt asked broadly for a recomputation or output-preservation "symbol." The pinned code also contains relevant request methods and scheduler helpers, while v3's evaluator expects the work-kind member and output counter field. Both latest responses placed multiple related symbols in single fields. V4 removes the abstraction ambiguity with a new prompt, `preemption_v4.schema.json`, and `evaluate_preemption_v4`; it does **not** loosen or rescore v3. The v4 schema describes six fields but includes no literal expected answers:

| Field | Requested abstraction |
| --- | --- |
| `victim_selection_policy` | Concrete preemption policy implementation class choosing a victim |
| `memory_control_component` | Controller coordinating KV allocation, release, and preemption |
| `recomputation_work_kind` | WorkKind enum member scheduled after preemption |
| `output_progress_field` | InferenceRequest field counting generated output across preemption |
| `proving_test_file` | Test file proving recomputation and output preservation |
| `explanation` | Brief account of how the pieces interact |

Expected evaluator-only concepts are `LargestPrivateOwnerPolicy`, `MemoryController`, `RECOMPUTE`, `output_generated`, and `tests/test_phase_7_preemption.py`. A single bare or qualified identifier may satisfy a symbol field when its final whole segment matches; related methods, substring matches, composite values, and prose do not. Test paths retain v3 normalization. The explanation cannot rescue a wrong structured field. The production selector never receives this expectation map.

The first local v4 prompt wording selected **7/7 files but 6/7 identifiers**, omitting the scheduler's `WorkKind.RECOMPUTE` line. After documenting that regression, only v4 prompt wording changed. The final prompt reaches **7/7 files and 7/7 identifiers** at **5,983 estimated selected-source tokens** under BALANCED/6000 on the unchanged pinned corpus. Direct ContextBuilder, direct MCPGateway, and local Codex-core stdio return the same fingerprint, excerpts, estimate, and warnings. These are local heuristic measurements, **not** new external Codex inference or an A/B result. Historical v1-v3 artifacts remain unchanged and cannot be aggregated with v4.

## Phase 22.8: Local Efficiency Investigation

The first real Task A v4 pair (`20260930T102955Z-ea96eff7`) was infrastructure-valid and **PASS/PASS**, with harness gate `CORRECT_WITH_LESS_NATIVE_EXPLORATION`. The historical artifact is frozen. Baseline/optimized Codex input was **86,143/156,138**, cached input **58,368/120,320**, output **634/1,383**, reasoning output **116/459**, and elapsed **40.263s/82.496s**. Explicit native reads fell **7 to 3**, but native calls rose **8 to 9**, searches **1 to 3**, and one optimized MCP call made total observed native-plus-MCP interactions **8 to 10**. A file-read reduction is not a reduction in all tool interactions or agent turns. Optimized natively read `engine.py` (partially delivered), `memory.py` (absent), and `request.py` (completely delivered). The complete-file native reread is separate from MCP delivery duplication, which was **0%**.

The optimized agent made one BALANCED/6000 `middleman_context` call, with a 6,000 effective cap, 33,552 candidate, 5,949 selected-source, and 7,184 MCP-result estimated tokens. Actual delivered source was 23,770 unique bytes (about 5,943 tokens) and zero repeated bytes. The pack covered **6/7 required files and 6/7 identifiers**; `middle_man/lab/memory.py` and its `def release_request` evidence were omitted for `context_budget`, although `memory_control.py` contained the verified `self.memory.release_request(...)` path. The answer passed after a native `memory.py` read. The optimized query was a shorter paraphrase of the committed v4 prompt; its receipt signature is `2c1f2980aa8b8d971e68090bb2a8bca837d369c67dcddc2fceccc5466ff1262d`. The local exact-prompt pack and actual-query pack need not match.

The local Codex event parser uses the documented `turn.completed.usage` fields. The retained **sanitized** event artifacts contain one `turn.completed` record per side and no per-model-invocation token records; raw stdout JSONL was not retained by the canonical harness. The parser would take the last `turn.completed` usage if multiple appeared. Exact model-call decomposition is therefore unavailable. Diagnostic arithmetic for this correct pair is baseline `input - cached = 27,775`, optimized `35,818`, delta **+8,043**; total input delta **+69,995**, cached-input delta **+61,952**. These are observed turn-level fields and subtraction, not billing, quota, a cache multiplier, or evidence that the 7,184-token MCP result caused the entire input increase. Persistent conversation context is a plausible hypothesis, not provider-side causal proof.

Phase 22.8 adds per-range selection-phase attribution in local `SelectionDiagnostic` and an optional `depth_token_limit` shadow parameter on `ContextBuilder.build`. The default `None` reproduces current BALANCED fingerprints, selected ranges, and core result sizes. The cap touches DEPTH only; required/coverage source and the bounded repair pass still use the 6,000 hard budget. The parameter is not an MCP tool argument; phase metadata is omitted from Codex-core and full-profile Context Pack payloads. On the **actual real v4 query**, final selected tokens by phase were:

| REQUIRED | COVERAGE | DEPTH | REPAIR | Total |
| ---: | ---: | ---: | ---: | ---: |
| 1,693 | 3,705 | 261 | 290 | 5,949 |

Thus only **261 tokens (4.4%)** were DEPTH-only in the actual final pack; REQUIRED plus COVERAGE accounted for **5,398 (90.7%)**. DEPTH ranges were `engine.py:34` (6), `metrics.py:9` (17) and `20-44` (138), `workloads.py:65-68` (31), `prefix_cache.py:17` (5) and `26-30` (33), and `config.py:4-10` (31). Only `prefix_cache.py` and `config.py` were entirely DEPTH-selected paths; `engine.py`, `metrics.py`, and `workloads.py` also had other-phase context. `trace.py` and `serialization.py` were COVERAGE-selected through query trace terms, and `test_phase_4_engine_runner.py` through test/release/work signals; this labels selection evidence, not objective usefulness. The repair added a 290-token `workloads.py:19-51` range for underrepresented query evidence, evicting `metrics.py:158-177`, and did not add `memory.py`.

The following are **local heuristic** BALANCED/6000 sweeps using the same pinned corpus and exact real query from the receipt. `F/I` is seven-unit file/identifier recall; `R` notes the accepted repair target. The five explicit v4 structured concepts and a verified release call were present at every row. The exact-prompt result is not the historical model query.

| DEPTH cap | Exact source/result | Exact F/I, R | Real-query source/result | Real F/I, R |
| ---: | ---: | --- | ---: | --- |
| None (control) | 5,983 / 6,913 | 7/7, trace | 5,949 / 7,184 | 6/6, workloads |
| 0 | 5,921 / 6,764 | 7/7, engine | 5,404 / 6,263 | 6/6, engine |
| 250 | 5,983 / 6,913 | 7/7, trace | 5,916 / 7,094 | 6/6, workloads |
| 500 | 5,983 / 6,913 | 7/7, trace | 5,888 / 7,076 | 6/6, workloads |
| 750 | 5,983 / 6,913 | 7/7, trace | 5,949 / 7,184 | 6/6, workloads |
| 1,000 | 5,983 / 6,913 | 7/7, trace | 5,949 / 7,184 | 6/6, workloads |
| 1,500 | 5,983 / 6,913 | 7/7, trace | 5,949 / 7,184 | 6/6, workloads |
| 2,000 | 5,983 / 6,913 | 7/7, trace | 5,949 / 7,184 | 6/6, workloads |

The zero-depth shadow therefore reduces the real query by **545 selected-source** and **921 core-result** estimated tokens, but it does **not** recover `memory.py` or prove lower Codex usage. At zero depth, the exact prompt falls by only 62 source and 149 result tokens. Non-source heuristic result overhead for real control/shadow is 1,235/859 tokens (`result - selected source`); for exact prompt it is 930/843. The core result estimates use the existing serializer plus the same benchmark budget metadata, not a second payload implementation.

The broader robustness sweep rejects zero depth as a general LEAN policy. Historical v3-style exact/behavior/reordered/agent queries were 7/7 at current BALANCED; zero depth gave **4/4, 4/2, 6/5, 6/5** respectively. A 2,000-token cap still gave behavior **5/5** and reordered **6/5**. The short query remained intentionally underspecified (control **5/3**, zero **3/1**); generic architecture remained **0/0** at every cap. On unrelated bounded fixtures, auth was **4/4 at 133 tokens** and queue **4/4 at 306** across the sweep; upload was **4/4 at 129** by default and at caps 250-2,000, but zero depth regressed to **3/3 at 109**. No cap from this sweep both materially reduces the explicit v4 packs and preserves all broader checks. **No LEAN mode was promoted**; BALANCED remains the control, and a stronger general stopping rule needs separate evidence. This phase used no external Codex inference and makes no real token-saving claim.

## Phase 22.9: Local Total-Budget Investigation

This is a **shadow/local** sweep of the existing total `max_context_tokens` control, not a change to the selector. The pinned source, BALANCED mode, query wording, ranking, coverage/depth/repair rules, and core serializer remain unchanged. Both v4 queries considered **33,552** estimated candidate-source tokens at every budget. `S/R/O` means selected-source estimate / serialized core-result estimate / their difference (non-source overhead), all heuristic tokens. `F/I` is strict seven-unit file/identifier recall, `C` is the five structured v4 source concepts, `K` is verified KV release evidence, `P/E` is selected path/excerpt count, and `Req/Cov/Dep/Rep` is final phase attribution. The result estimate includes the same compact benchmark budget metadata at each cap. A different cap can change omission metadata and therefore overhead; estimates are not Codex-reported input or billing.

| Cap | Exact S/R/O | Exact F/I,C,K,P/E | Exact Req/Cov/Dep/Rep | Real S/R/O | Real F/I,C,K,P/E | Real Req/Cov/Dep/Rep |
| ---: | ---: | --- | ---: | ---: | --- | ---: |
| 2,000 | 1,966/2,621/655 | 2/2,2,no,7/9 | 1693/107/28/138 | 1,990/2,800/810 | 2/2,2,no,9/12 | 1693/180/117/0 |
| 2,500 | 2,427/3,252/825 | 3/3,3,no,9/12 | 1693/382/90/262 | 2,480/3,395/915 | 3/3,3,no,10/14 | 1693/449/338/0 |
| 3,000 | 2,842/3,567/725 | 4/4,4,no,9/10 | 1693/1121/11/17 | 2,971/3,842/871 | 4/4,4,no,11/13 | 1693/1188/90/0 |
| 3,500 | 3,488/4,465/977 | 4/4,4,no,10/15 | 1693/1121/393/281 | 3,371/4,356/985 | 4/4,4,no,11/15 | 1693/1188/200/290 |
| 4,000 | 3,848/4,591/743 | 5/5,5,yes,9/10 | 1693/2132/6/17 | 3,982/5,034/1052 | 4/4,4,no,12/16 | 1693/1876/123/290 |
| 4,500 | 4,499/5,544/1045 | 5/5,5,yes,11/16 | 1693/2132/393/281 | 4,477/5,478/1001 | 5/5,4,no,13/15 | 1693/2694/90/0 |
| 5,000 | 4,959/5,880/921 | 6/6,5,yes,10/13 | 1693/2950/54/262 | 4,938/6,100/1162 | 5/5,4,no,13/18 | 1693/2694/261/290 |
| 5,500 | 5,340/6,557/1217 | 6/6,5,yes,13/19 | 1693/2950/416/281 | 5,488/6,562/1074 | 6/6,5,yes,14/16 | 1693/3705/90/0 |
| 6,000 | 5,983/6,913/930 | 7/7,5,yes,12/13 | 1693/4222/23/45 | 5,949/7,184/1235 | 6/6,5,yes,14/19 | 1693/3705/261/290 |

The **exact committed prompt** first has 5/5 concepts and release evidence at **4,000**, not 5,000; its strict 7/7 threshold is **6,000**. The **actual optimized query** first has 5/5 plus release at **5,500**; strict 7/7 is **not reached** in this sweep. Release evidence first appears at 4,000 exact and 5,500 actual. The real-query 5,500 task-sufficient row reduces estimated selected source by **461** and core result by **622** versus its 6,000 control; overhead falls by 161. Exact 4,000 reduces selected source by **2,135** and core result by **2,322** versus exact 6,000, but sacrifices strict source recall. These are local pack-size differences, not real Codex input savings.

Path stability is non-monotonic because ranges are atomic and repair may evict depth ranges. For the exact prompt, `preemption.py` enters at 2,500, the Phase 7 test at 3,000, `memory_control.py` at 4,000, `scheduler.py` at 5,000, and `memory.py` only at 6,000. `prefix_cache.py` and `config.py` enter and disappear at intermediate caps; `trace.py` enters at 5,500 and is repaired into the 6,000 pack after two evictions. `memory.py` is omitted for `context_budget` below 6,000. For the actual query, `preemption.py` enters at 2,500, the Phase 7 test at 3,000, `trace.py` at 4,000, `scheduler.py` at 4,500, and `memory_control.py` at 5,500. The 6,000 selected path set is unchanged from 5,500, although excerpts and phase allocation differ. `memory.py` remains omitted for `context_budget` at **every** actual-query cap. At 3,500, 4,000, 5,000, and 6,000, repair targets `workloads.py`; no repair adds `memory.py`. The per-budget test output prints the full selected paths, all omitted paths/reasons, and repair evictions, not just this summary.

Strict seven-unit file/identifier recall across historical variants (columns are budgets 2,000 through 6,000 in 500-token steps):

| Query | 2000 | 2500 | 3000 | 3500 | 4000 | 4500 | 5000 | 5500 | 6000 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Historical exact | 3/2 | 4/4 | 5/5 | 5/5 | 5/5 | 5/5 | 6/6 | 7/7 | 7/7 |
| Behavior | 4/2 | 5/4 | 5/5 | 5/5 | 6/6 | 6/6 | 7/7 | 7/7 | 7/7 |
| Reordered | 3/2 | 4/4 | 5/5 | 5/5 | 5/5 | 6/6 | 5/5 | 5/5 | 7/7 |
| Agent | 4/4 | 5/5 | 5/5 | 6/5 | 6/5 | 6/6 | 7/7 | 7/7 | 7/7 |
| Short | 3/1 | 3/1 | 3/1 | 4/2 | 5/3 | 5/3 | 5/3 | 5/3 | 5/3 |
| Generic | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |

The auth, queue, and upload quality fixtures retain **4/4 required files and symbols at every cap**. Their selected-source/core-result estimates stay at **133/416**, **306/621**, and **129/425** respectively. The unrelated fixtures do not justify a smaller global cap: the reordered concrete Task A query needs 6,000 for its expected 7/7, and the committed exact v4 prompt also needs 6,000. Hence the **smallest globally robust swept cap is 6,000**; no smaller global budget is supported. A `BenchmarkPolicy(initial_context_budget=5500, expansion_ceiling=12000)` is representable with existing plumbing, but 5,500 is only a **real-query task-sufficient diagnostic**, not a promoted `PROGRESSIVE_INITIAL_CONTEXT` policy. The 12,000 expansion ceiling is independent and normal user sessions remain unchanged.

The retained sanitized v4 events show this **observable** sequence, not hidden model invocations. Baseline: one `rg -n` repository search; `Get-Content` of `test_phase_7_preemption.py`, `scheduler.py`, `preemption.py`, `memory_control.py`, `memory.py`, and `request.py`; then `Get-Content engine.py`; then the answer. That is 8 native calls (1 search, 7 explicit reads). Optimized: `middleman_context` first; then three `rg -n -C` searches (Phase 7 test, engine, then seven implementation files); `Get-Location`; partial `Get-Content` reads of `engine.py`, `memory.py`, and `request.py`; two local pytest invocations; then the answer. That is 9 native calls plus 1 MCP call, with **zero searches before** context, **three after**, and **three native reads after**. `request.py` was `COMPLETE_IN_MCP` but still reread natively; source delivery cannot guarantee that Codex will avoid verification. Baseline/optimized observed interactions were **8/10**, so any future smaller-initial-pack experiment must measure both delivered payload and added search/read/expand interactions. The sanitized events expose one `turn.completed` usage record per side and do not support per-model-call attribution.

Phase 22.8 remains locked: the real pack's REQUIRED+COVERAGE share was 5,398/5,949; DEPTH alone was only 261/5,949. Phase 22.9 tested **total** initial budgets, leaving selector logic, v4 evaluator/schema, historical artifacts, normal MCP defaults, and the real v4 result untouched. It ran **zero external Codex calls**, produced **no new A/B result**, and makes **no real token-saving claim**.

## Phase 22.10: Local Progressive Delivery Prototype

Phase 22.9 ruled out lowering the **canonical selection** cap globally: the reordered strong query still needs 6,000 for one-shot strict 7/7. Phase 22.10 instead keeps the same BALANCED/6000 canonical pack and tests a smaller **initial source-delivery** budget. This is an optional benchmark/server policy, not a model-facing `middleman_context` argument or a normal-session default. Codex-core still has exactly five tools. The existing `middleman_expand_context` now accepts `kind="selected_path"` for a path already present in the stored canonical pack; it sends only unseen selected source after current-hash verification. Other expansion kinds, native reads, redaction, and path confinement remain available. The separate expansion ceiling stays at 12,000.

The deterministic seed planner operates only on canonical selected ranges, prioritizing REQUIRED, COVERAGE, REPAIR, then DEPTH, preserving canonical order within each class. REQUIRED ranges remain atomic even if they overrun the seed cap: the 1,500-row seed is 1,693 source tokens, a **193-token** planned overrun. No evaluator identifiers or benchmark required units enter runtime planning. The initial `evidence_map` has one metadata-only entry per canonical selected range: `path`, `start_line`, `end_line`, primary indexed `symbol`, short existing `reason`, `complete_file`, and `delivered`. It contains no source text, scores, phase records, or evaluator metadata. When all selected source fits the seed, no map is sent and the normal one-shot payload shape is used. Map-only lines never enter `DeliveryLedger`.

The table is a **local heuristic**, not Codex input usage. Canonical source/result remain **5,949/7,184** for the actual v4 query and **5,983/6,913** for the committed exact prompt at every row. `Seed` is source actually sent initially, `Map` is the serialized evidence-map estimate, `Result` includes all initial response metadata, `C` is directly seeded v4 concept evidence out of five, `K` is directly seeded verified release evidence, and `Calls` is the minimum ideal targeted selected-path expansions needed for five concepts plus release / strict seven-unit recall. `N/A` means the canonical pack itself lacks a strict unit.

| Seed cap | Actual seed/map/result | Actual C,K,calls | Exact seed/map/result | Exact C,K,calls |
| ---: | ---: | --- | ---: | --- |
| 1,500 | 1,693/919/2,986 | 2,no,3/N/A | 1,693/613/2,682 | 2,no,3/5 |
| 1,750 | 1,740/918/3,264 | 2,no,3/N/A | 1,735/612/2,904 | 2,no,3/5 |
| 2,000 | 1,990/917/3,780 | 2,no,3/N/A | 1,868/612/3,146 | 2,no,3/5 |
| 2,250 | 2,234/917/4,031 | 3,no,2/N/A | 2,143/612/3,476 | 3,no,2/4 |
| 2,500 | 2,479/918/4,067 | 3,no,2/N/A | 2,496/612/3,682 | 3,no,2/4 |
| 3,000 | 2,973/916/4,834 | 4,no,1/N/A | 2,882/611/4,279 | 4,no,1/3 |
| 3,500 | 3,500/917/5,190 | 4,no,1/N/A | 3,485/612/4,788 | 4,yes,1/3 |
| 4,000 | 3,984/916/5,919 | 5,yes,0/N/A | 3,893/611/5,359 | 5,yes,0/2 |
| 4,500 | 4,500/918/6,162 | 5,yes,0/N/A | 3,893/611/5,359 | 5,yes,0/2 |

At the 4,000 setting the actual map has **19 range entries**, 5 mapped-but-undelivered paths, and 11 seed paths; exact has **13 entries**, 2 mapped paths, and 10 seed paths. The actual map is about 916 estimated tokens; exact about 611. Paths, symbols/reasons, and line bounds make omitted selected evidence discoverable without copying source. The actual pack still lacks `middle_man/lab/memory.py` and its `def release_request` unit; **no selected-path expansion can recover it**. The controller's verified release call is seeded at 4,000. A native read or a separately authorized fresh/normal expansion is still needed for the absent strict unit. In the real historical run, `request.py` was complete in MCP but was nevertheless read natively; the local complete-in-seed test returns zero source on selected-path expansion, while a mapped-only `request.py` test delivers once then returns zero. Neither blocks native verification.

The four strong historical variants retain their unchanged canonical 7/7 source quality. At a 4,000 seed, ideal strict-recovery calls are **historical exact 2, behavior 1, reordered 1, agent-style 2**. Their seed/map/result estimates are respectively **3,877/797/5,568**, **3,853/1,048/6,185**, **3,892/751/5,537**, and **3,992/895/5,763**. These are oracle-style benchmark-only minimums, not a prediction that Codex will pick those paths. Short and generic queries remain limited by their canonical selection; progressive delivery does not create missing relevance. Auth, queue, and upload fixtures preserve **4/4 files and symbols directly in the seed**, need **0 expansions**, and are sent without a map because the full canonical source fits. Their selected-source/result estimates remain **133/416**, **306/621**, and **129/425**.

The one possible **future** benchmark policy is `initial_context_budget=6000`, `initial_source_delivery_budget=4000`, `expansion_ceiling=12000`. It is **not promoted**. At this setting, initial heuristic result size falls **7,184 to 5,919** on the actual query (minus 1,265, 17.6%) and **6,913 to 5,359** on the exact prompt (minus 1,554, 22.5%). Both seed responses already contain all five structured concepts plus release evidence, so the task-sufficient ideal expansion count is zero; exact strict 7/7 remains two targeted calls away. A 3,500 seed has larger initial reduction but needs an extra call for v4 task evidence and three calls for exact strict 7/7. This interaction difference favors 4,000 for a future real test.

Optional-expansion local scenarios show why initial size alone is insufficient. Actual query: **1/2/3 interactions** deliver cumulative source **3,984/4,802/4,833** and cumulative result estimates **5,919/6,958/7,194** after expanding `scheduler.py` and then `config.py`. Exact prompt: cumulative source **3,893/5,165/5,983**, results **5,359/6,869/7,909** after expanding `memory.py` and `scheduler.py`. After two optional expansions, both cumulative result estimates exceed their one-shot controls. These are payload sums, **not a model-conversation or Codex input model**. The real historical baseline/optimized pair already had 8/10 observed tool interactions; a future A/B must measure both delivered payload and all native/MCP calls, including verification reads. No external inference, new A/B result, historical rescore, or real token-saving claim exists in Phase 22.10.

## Phase 22.10.1: Local Canonical Harness Plumbing

The locked Phase 22.10 candidate is BALANCED canonical selection at **6,000**, an experimental initial source-delivery budget of **4,000**, and a separate expansion ceiling of **12,000**. The canonical runner now threads one `BenchmarkPolicy` through `run_suite`, `_pair`, `run_one`, invocation construction, optimized MCP registration, and `_mcp_preflight`. The default policy omits the source-delivery flag and remains one-shot; baseline has no Middle_Man MCP registration. An explicit `--benchmark-source-delivery-budget 4000` on `codex benchmark run` adds the server-side flag only to optimized mode. Preflight compares the exact policy-aware MCP command/arguments and aborts before inference if the registered server is wrong.

Local preview only, with the previously validated Desktop sibling snapshot parent:

```powershell
.venv\Scripts\python.exe -m middle_man codex benchmark run preemption-v4 --repo . --dry-run --benchmark-source-delivery-budget 4000 --windows-sandbox unelevated --snapshot-root "C:\Users\Dennis O'Loane\OneDrive\Desktop\Middle Man benchmark copy O'Loane"
```

The optimized preview shows `--benchmark-context-budget 6000 --benchmark-source-delivery-budget 4000 --benchmark-expansion-budget 12000`; baseline shows no MCP policy args. Do not add `--confirm-external-service` without separate authorization. Successful progressive context usage now audits the configured 4,000 delivery cap, actual source-seed estimate, required-range overrun, fixed canonical selection, and replay state. The runner rejects missing/wrong progressive evidence, non-fixed or non-6,000 canonical selection, replay, and impossible seed/overrun accounting. One-shot retains its historical budget semantics and rejects an accidental progressive server. The sanitized `result.json` contains `benchmark_policy`, human reports label one-shot/progressive and the distinct budgets, and snapshot-local receipts carry source-free policy values. The pinned-v4 local stdio proof delivers the unchanged 5,949-token canonical pack fingerprint with a 3,984-token initial seed, then delivers mapped selected-path source once and zero source on repetition in the same session. These are heuristic local measurements only. **No external progressive A/B has run and no real token saving is claimed.**
