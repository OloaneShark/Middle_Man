"""Local-only total-budget diagnostics on the unchanged selector."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark.preemption_v3 import TASK_A_V3_UNITS, measure_required_source
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import BenchmarkPolicy
from middle_man.mcp.gateway import MCPGateway


TASK = next(task for task in TASKS if task.id == "preemption-v4")
REAL_QUERY = (
    "Explain KV preemption in this repository: identify victim selection policy implementation class, "
    "controller coordinating KV allocation and release, scheduler WorkKind for preempted requests, "
    "InferenceRequest generated-output field preserved, and proving test file; trace interactions and "
    "KV block release. Read only, no changes."
)
BUDGETS = (2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000)
QUERIES = {
    "exact_v4": TASK.prompt,
    "real_v4": REAL_QUERY,
    "historical_exact": next(task.prompt for task in TASKS if task.id == "preemption-v3"),
    "behavior": "Need context for victim selection, KV release, recomputation, and output preservation",
    "reordered": "For KV preemption, identify the proving preemption test and output preservation; "
                 "then explain recomputation scheduling, memory release and control, and victim selection",
    "agent": "Locate source and tests for KV preemption victim choice, memory release, the RECOMPUTE "
             "work kind and scheduling path, and output_generated preservation",
    "short": "Find the KV preemption implementation and tests",
    "generic": "inspect the Middle_Man architecture",
}


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-9") / "pair", "guidance\n")
    return optimized


def _concepts(pack: object) -> tuple[bool, ...]:
    by_path: dict[str, str] = {}
    for excerpt in pack.excerpts:
        by_path[excerpt.path] = by_path.get(excerpt.path, "") + excerpt.text
    return (
        "LargestPrivateOwnerPolicy" in by_path.get("middle_man/lab/preemption.py", ""),
        "class MemoryController" in by_path.get("middle_man/lab/memory_control.py", ""),
        "RECOMPUTE =" in by_path.get("middle_man/lab/work.py", ""),
        "output_generated:" in by_path.get("middle_man/lab/request.py", ""),
        "def test_pressure_preempts_rebuilds_and_preserves_output" in by_path.get(
            "tests/test_phase_7_preemption.py", ""),
    )


def _release(pack: object) -> bool:
    return any((item.path == "middle_man/lab/memory.py" and "def release_request" in item.text) or
               (item.path == "middle_man/lab/memory_control.py" and
                "self.memory.release_request(victim.request_id)" in item.text)
               for item in pack.excerpts)


def _row(pack: object, gateway: MCPGateway, *, fixture: object | None = None,
         index: RepositoryIndexer | None = None) -> dict:
    phases = Counter({phase: sum(item.estimated_source_tokens
                                 for diagnostic in pack.selection_diagnostics
                                 for item in diagnostic.selected_range_phases if item.phase == phase)
                      for phase in ("REQUIRED", "COVERAGE", "DEPTH", "REPAIR")})
    budget = pack.max_context_tokens
    payload = {**gateway._core_payload(pack).data, "budget": {
        "requested_context_tokens": budget, "effective_context_tokens": budget,
        "benchmark_context_cap": budget, "budget_capped": False, "force_replay": False,
    }}
    result = HeuristicTokenEstimator().estimate(json.dumps(payload, ensure_ascii=False))
    row = {
        "budget": budget,
        "fingerprint": pack.fingerprint,
        "candidate": pack.metrics.estimated_raw_candidate_tokens,
        "source": pack.metrics.estimated_selected_tokens,
        "result": result,
        "overhead": result - pack.metrics.estimated_selected_tokens,
        "paths": list(pack.selected_files),
        "excerpt_count": len(pack.excerpts),
        "phases": dict(phases),
        "repairs": [{"target": item.candidate_path, "evicted": item.evicted_ranges}
                    for item in pack.selection_diagnostics if item.repair_candidate],
        "omitted": [{"path": item.candidate_path, "reason": item.omission_reason}
                    for item in pack.selection_diagnostics if item.omission_reason],
    }
    assert sum(phases.values()) == row["source"]
    if fixture is None:
        recall = measure_required_source(pack, TASK_A_V3_UNITS)
        row.update(files=7 - len(recall.missing_files), identifiers=7 - len(recall.missing_symbols),
                   concepts=sum(_concepts(pack)), release=_release(pack),
                   missing_files=recall.missing_files, missing_identifiers=recall.missing_symbols,
                   memory_selected="middle_man/lab/memory.py" in pack.selected_files)
    else:
        paths = set(pack.selected_files)
        assert index is not None
        row.update(files=sum(path in paths for path in fixture.required_files),
                   identifiers=sum(any(excerpt.path == symbol.path and
                                       excerpt.start_line <= symbol.start_line and
                                       excerpt.end_line >= (symbol.end_line or symbol.start_line)
                                       for symbol in index.index().find_symbol(name)
                                       for excerpt in pack.excerpts)
                                   for name in fixture.required_symbols))
    return row


def _summary(row: dict) -> dict:
    keys = ("budget", "candidate", "source", "result", "overhead", "excerpt_count",
            "files", "identifiers", "concepts", "release", "phases", "memory_selected")
    return {key: row[key] for key in keys if key in row}


def test_pinned_total_budget_matrix(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    builder = ContextBuilder(config)
    gateway = MCPGateway(config)
    matrix = {name: [_row(builder.build(query, mode="balanced", max_context_tokens=budget), gateway)
                     for budget in BUDGETS] for name, query in QUERIES.items()}
    for rows in matrix.values():
        assert [row["budget"] for row in rows] == list(BUDGETS)
        assert all(row["source"] <= row["budget"] for row in rows)
        for row in rows:
            assert row["overhead"] == row["result"] - row["source"]
    assert (matrix["exact_v4"][-1]["source"], matrix["exact_v4"][-1]["result"]) == (5983, 6913)
    assert (matrix["real_v4"][-1]["source"], matrix["real_v4"][-1]["result"]) == (5949, 7184)
    assert matrix["real_v4"][-1]["fingerprint"] == builder.build(
        REAL_QUERY, mode="balanced", max_context_tokens=6000).fingerprint
    assert matrix["exact_v4"][-1]["fingerprint"] == builder.build(
        TASK.prompt, mode="balanced", max_context_tokens=6000).fingerprint
    assert (matrix["exact_v4"][-1]["files"], matrix["exact_v4"][-1]["identifiers"]) == (7, 7)
    assert (matrix["real_v4"][-1]["files"], matrix["real_v4"][-1]["identifiers"]) == (6, 6)
    assert [row["concepts"] for row in matrix["exact_v4"]] == [2, 3, 4, 4, 5, 5, 5, 5, 5]
    assert [row["release"] for row in matrix["exact_v4"]] == [False] * 4 + [True] * 5
    assert [row["concepts"] for row in matrix["real_v4"]] == [2, 3, 4, 4, 4, 4, 4, 5, 5]
    assert [row["release"] for row in matrix["real_v4"]] == [False] * 7 + [True] * 2
    assert all(not row["memory_selected"] for row in matrix["real_v4"])
    for name in ("historical_exact", "behavior", "reordered", "agent"):
        assert (matrix[name][-1]["files"], matrix[name][-1]["identifiers"]) == (7, 7)
    assert matrix["reordered"][-2]["files"] < 7
    assert all(row["files"] == 0 for row in matrix["generic"])
    assert all(row["files"] < 7 for row in matrix["short"])
    assert BenchmarkPolicy(3500).expansion_ceiling == 12000
    assert BenchmarkPolicy().initial_context_budget == 6000
    for name, rows in matrix.items():
        print("PHASE22_9_MATRIX", name, json.dumps([_summary(row) for row in rows], sort_keys=True))
    for name in ("exact_v4", "real_v4"):
        for row in matrix[name]:
            print("PHASE22_9_PATHS", name, row["budget"], json.dumps({
                "selected": row["paths"], "omitted": row["omitted"], "repairs": row["repairs"]},
                sort_keys=True))


@pytest.mark.parametrize("case", coverage_cases(), ids=lambda case: case.name)
def test_unrelated_total_budget_matrix(tmp_path: Path, case: object) -> None:
    for path, source in case.files:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    config = GatewayConfig(tmp_path)
    builder = ContextBuilder(config)
    gateway = MCPGateway(config)
    index = RepositoryIndexer(config)
    rows = [_row(builder.build(case.query, mode="balanced", max_context_tokens=budget,
                               top_k=10), gateway, fixture=case, index=index) for budget in BUDGETS]
    assert all(row["files"] == row["identifiers"] == 4 for row in rows)
    assert all(row["source"] <= row["budget"] for row in rows)
    print("PHASE22_9_FIXTURE_MATRIX", case.name,
          json.dumps([_summary(row) for row in rows], sort_keys=True))
