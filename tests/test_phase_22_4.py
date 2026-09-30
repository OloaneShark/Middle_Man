from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from middle_man.gateway.codex_benchmark.preemption_v3 import measure_required_source
from middle_man.gateway.codex_benchmark.runner import _new_run_id, _pair
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import MatchSignal, RelevanceCandidate
from middle_man.gateway.selection import SelectionEntry, allocate
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity
from middle_man.mcp.gateway import MCPGateway


TASK = next(task for task in TASKS if task.id == "preemption-v3")
RECEIPT_DERIVED_QUERY_FIXTURE = (
    "Need exact source references for KV preemption in Middle_Man: identify victim selection, "
    "memory control and release, recomputation, output preservation, and test symbols proving "
    "these behaviors and components"
)
QUERIES = {
    "exact": TASK.prompt,
    "short": "Find the KV preemption implementation and tests",
    "behavior": "Need context for victim selection, KV release, recomputation, and output preservation",
    "receipt_derived": RECEIPT_DERIVED_QUERY_FIXTURE,
    "reordered": "For KV preemption, identify the proving preemption test and output preservation; "
                 "then explain recomputation scheduling, memory release and control, and victim selection",
    "agent": "Locate source and tests for KV preemption victim choice, memory release, the RECOMPUTE "
             "work kind and scheduling path, and output_generated preservation",
    "generic": "inspect the Middle_Man architecture",
}


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-4") / "pair", "guidance\n")
    return optimized


def test_pinned_query_robustness_and_receipt_derived_repair(pinned: Path) -> None:
    builder = ContextBuilder(GatewayConfig(pinned))
    results = {}
    for name, query in QUERIES.items():
        pack = builder.build(query, mode="balanced", max_context_tokens=6000)
        recall = measure_required_source(pack)
        results[name] = {
            "files": round(recall.required_file_recall * 7),
            "identifiers": round(recall.required_symbol_recall * 7),
            "tokens": pack.metrics.estimated_selected_tokens,
            "paths": pack.selected_files,
            "warnings": pack.warnings,
            "swaps": [(item.candidate_path, item.evicted_ranges) for item in pack.selection_diagnostics
                      if item.repair_candidate],
        }
        assert pack.metrics.estimated_selected_tokens <= 6000
        assert pack.fingerprint == builder.build(query, mode="balanced", max_context_tokens=6000).fingerprint
    assert results["exact"]["files"] == results["exact"]["identifiers"] == 7
    assert results["receipt_derived"]["files"] == results["receipt_derived"]["identifiers"] == 7
    assert any(path == "middle_man/lab/scheduler.py" for path, _ in results["receipt_derived"]["swaps"])
    assert results["generic"]["files"] < 7
    print("PHASE22_4_LOCAL_MATRIX", json.dumps(results, sort_keys=True))


def _candidate(path: str, score: float, *signals: MatchSignal) -> RelevanceCandidate:
    return RelevanceCandidate(path, score, "PRIMARY", (), (), (), signals)


@pytest.mark.parametrize("domain,concept", [
    ("auth", "expiry"), ("queue", "cancellation"), ("upload", "validation"),
])
def test_unrelated_bounded_repair(domain: str, concept: str) -> None:
    root = f"app/{domain}.py"
    coverage = f"app/{domain}_controller.py"
    depth = f"app/{domain}_report.py"
    omitted = f"app/{domain}_policy.py"
    entries = (
        SelectionEntry(root, 1, 10, "full_file", 120, True,
                       _candidate(root, 150, MatchSignal("explicit_path", f"path:{root}", 120, "explicit")),
                       anchor=True),
        SelectionEntry(coverage, 1, 20, "full_file", 90, False,
                       _candidate(coverage, 100,
                                  MatchSignal("filename_term", f"term:{domain}", 28, "filename", domain),
                                  MatchSignal("family_term", f"term:{concept}", 10, "family", concept))),
        SelectionEntry(depth, 1, 15, "full_file", 50, False,
                       _candidate(depth, 100,
                                  MatchSignal("family_term", f"term:{concept}", 10, "family", concept),
                                  MatchSignal("import_neighbor", "graph:import", 13, "graph"))),
        SelectionEntry(omitted, 1, 12, "full_file", 45, False,
                       _candidate(omitted, 50,
                                  MatchSignal("family_term", f"term:{concept}", 10, "family", concept),
                                  MatchSignal("import_neighbor", "graph:import", 13, "graph"))),
    )
    selected, diagnostics = allocate(entries, 260)
    assert selected == allocate(entries, 260)[0]
    assert {entries[index].path for index in selected} == {root, coverage, omitted}
    assert sum(entries[index].cost for index in selected) == 255
    repair = next(item for item in diagnostics if item.repair_candidate)
    assert repair.candidate_path == omitted
    assert repair.evicted_ranges == ((depth, 1, 15),)


def test_repair_does_not_displace_required_test_or_choose_irrelevant() -> None:
    path = "app/auth.py"
    test = "tests/test_auth.py"
    entries = (
        SelectionEntry(path, 1, 10, "full_file", 120, True,
                       _candidate(path, 150, MatchSignal("explicit_path", f"path:{path}", 120, "explicit")),
                       anchor=True),
        SelectionEntry(test, 1, 10, "full_file", 100, True,
                       _candidate(test, 100, MatchSignal("related_test", "graph:test", 12, "test")),
                       is_test=True),
        SelectionEntry("app/auth_policy.py", 1, 10, "full_file", 80, False,
                       _candidate("app/auth_policy.py", 50,
                                  MatchSignal("family_term", "term:expiry", 10, "family", "expiry"),
                                  MatchSignal("import_neighbor", "graph:import", 13, "graph"))),
        SelectionEntry("app/irrelevant.py", 1, 1, "full_file", 1, False,
                       _candidate("app/irrelevant.py", 1,
                                  MatchSignal("import_neighbor", "graph:import", 13, "graph"))),
    )
    selected, diagnostics = allocate(entries, 220, tests_requested=True)
    assert {entries[index].path for index in selected} == {path, test}
    assert not any(item.repair_candidate for item in diagnostics)


def test_core_completeness_and_delta_without_source_in_ledger(tmp_path: Path) -> None:
    (tmp_path / "engine.py").write_text(
        "def preemption():\n    return 1\n\n" +
        "".join(f"def helper_{index}():\n    return {index}\n\n" for index in range(90)),
        encoding="utf-8")
    gateway = MCPGateway(GatewayConfig(tmp_path))
    first = gateway.context("preemption", mode="aggressive", max_context_tokens=300)
    assert first["excerpts"] and all(item["complete_file"] is False for item in first["excerpts"])
    old = {(item["path"], line) for item in first["excerpts"]
           for line in range(item["start_line"], item["end_line"] + 1)}
    repeated = gateway.context("preemption", mode="aggressive", max_context_tokens=300)
    assert repeated["unchanged"] and not repeated["excerpts"]
    expanded = gateway.expand_context(first["fingerprint"], "full_file", target="engine.py",
                                      max_context_tokens=3000, core=True)
    new = {(item["path"], line) for item in expanded["excerpts"]
           for line in range(item["start_line"], item["end_line"] + 1)}
    assert new and not old & new
    assert all(item["complete_file"] is False for item in expanded["excerpts"])
    assert "def preemption" not in repr(gateway.delivery_ledger.__dict__)
    estimator = HeuristicTokenEstimator()
    actual = estimator.estimate(json.dumps(first, separators=(",", ":")))
    without = estimator.estimate(json.dumps({
        **first, "excerpts": [{key: value for key, value in item.items() if key != "complete_file"}
                             for item in first["excerpts"]]}, separators=(",", ":")))
    print("PHASE22_4_CORE_OVERHEAD", actual - without, actual, without)
    assert actual - without <= 15


def test_benchmark_receipt_redaction_and_run_id(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(): return True\n", encoding="utf-8")
    secret = "not-a-real-bearer-token-123456789"
    query = "Investigate auth.py Bearer " + secret
    identity = BenchmarkIdentity(_new_run_id(), "preemption-v3", "optimized", "fixture")
    gateway = MCPGateway(GatewayConfig(tmp_path), benchmark_identity=identity)
    gateway.context(query)
    record = json.loads((tmp_path / ".middle_man_cache/benchmark_receipts.jsonl")
                        .read_text(encoding="utf-8").splitlines()[0])
    usage = (tmp_path / ".middle_man_cache/mcp_usage.jsonl").read_text(encoding="utf-8")
    assert record["run_id"] == identity.run_id
    assert record["query"]["redacted_task"].startswith("Investigate auth.py Bearer ")
    assert secret not in json.dumps(record) and secret not in usage
    assert "redacted_task" not in usage and "Investigate auth.py" not in usage
    assert _new_run_id() != identity.run_id
    assert identity.run_id != "artifacts"
    normal = tmp_path / "normal"
    normal.mkdir()
    (normal / "auth.py").write_text("def authenticate(): return True\n", encoding="utf-8")
    MCPGateway(GatewayConfig(normal)).context(query)
    assert not (normal / ".middle_man_cache/benchmark_receipts.jsonl").exists()


def test_pair_threads_explicit_unique_run_id_without_codex(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run_one(task: object, mode: str, root: Path, fingerprint: str, **kwargs: object
                     ) -> SimpleNamespace:
        calls.append((mode, kwargs["run_id"], kwargs["artifact_root"].name))
        return SimpleNamespace(valid=True, starting_fingerprint=fingerprint, correctness=False,
                               native=SimpleNamespace(file_reads=0, search_calls=0, listing_calls=0))

    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner.run_one", fake_run_one)
    run_id = _new_run_id()
    _pair(TASK, tmp_path / "pair", "guidance\n", first="baseline", order=1, command="unused",
          version="local", model="local", effort="high", timeout=1,
          artifacts=tmp_path / "artifacts", primary_repository_root=tmp_path,
          windows_sandbox="unelevated", run_id=run_id)
    assert calls == [("baseline", run_id, "artifacts"), ("optimized", run_id, "artifacts")]
