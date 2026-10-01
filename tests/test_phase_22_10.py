"""Local-only progressive delivery checks over canonical selected source."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark.preemption_v3 import TASK_A_V3_UNITS
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.source import StaleSourceError
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity, BenchmarkPolicy
from middle_man.mcp.gateway import MCPGateway
from middle_man.mcp.server import create_server
from middle_man.mcp.surface import measure_tool_surface


TASK = next(task for task in TASKS if task.id == "preemption-v4")
REAL_QUERY = (
    "Explain KV preemption in this repository: identify victim selection policy implementation class, "
    "controller coordinating KV allocation and release, scheduler WorkKind for preempted requests, "
    "InferenceRequest generated-output field preserved, and proving test file; trace interactions and "
    "KV block release. Read only, no changes."
)
BUDGETS = (1500, 1750, 2000, 2250, 2500, 3000, 3500, 4000, 4500)
CONCEPTS = (
    ("middle_man/lab/preemption.py", "LargestPrivateOwnerPolicy"),
    ("middle_man/lab/memory_control.py", "class MemoryController"),
    ("middle_man/lab/work.py", "RECOMPUTE ="),
    ("middle_man/lab/request.py", "output_generated:"),
    ("tests/test_phase_7_preemption.py", "def test_pressure_preempts_rebuilds_and_preserves_output"),
)
RELEASE = (
    ("middle_man/lab/memory.py", "def release_request"),
    ("middle_man/lab/memory_control.py", "self.memory.release_request(victim.request_id)"),
)
STRONG = {
    "historical_exact": next(task.prompt for task in TASKS if task.id == "preemption-v3"),
    "behavior": "Need context for victim selection, KV release, recomputation, and output preservation",
    "reordered": "For KV preemption, identify the proving preemption test and output preservation; "
                 "then explain recomputation scheduling, memory release and control, and victim selection",
    "agent": "Locate source and tests for KV preemption victim choice, memory release, the RECOMPUTE "
             "work kind and scheduling path, and output_generated preservation",
}


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-10") / "pair", "guidance\n")
    return optimized


def _present(excerpts: tuple, path: str, needle: str) -> bool:
    return any(item.path == path and needle in item.text for item in excerpts)


def _meets(excerpts: tuple, required: tuple[tuple[str, str], ...], *, release: bool = False) -> bool:
    return all(_present(excerpts, path, needle) for path, needle in required) and (
        not release or any(_present(excerpts, path, needle) for path, needle in RELEASE))


def _recovery_paths(pack: object, seed: tuple, required: tuple[tuple[str, str], ...],
                    *, release: bool = False) -> tuple[str, ...] | None:
    if not _meets(pack.excerpts, required, release=release):
        return None
    paths = sorted({item.path for item in pack.excerpts if item not in seed})
    for count in range(len(paths) + 1):
        for chosen in combinations(paths, count):
            recovered = seed + tuple(item for item in pack.excerpts if item.path in chosen)
            if _meets(recovered, required, release=release):
                return chosen
    raise AssertionError("canonical evidence should be recoverable")


def _fixture_coverage(excerpts: tuple, case: object, index: object) -> tuple[int, int]:
    files = sum(any(item.path == path for item in excerpts) for path in case.required_files)
    symbols = sum(any(item.path == symbol.path and item.start_line <= symbol.start_line and
                      item.end_line >= (symbol.end_line or symbol.start_line)
                      for symbol in index.find_symbol(name) for item in excerpts)
                  for name in case.required_symbols)
    return files, symbols


def _fixture_recovery(pack: object, seed: tuple, case: object, index: object) -> tuple[str, ...] | None:
    if _fixture_coverage(pack.excerpts, case, index) != (4, 4):
        return None
    paths = sorted({item.path for item in pack.excerpts if item not in seed})
    for count in range(len(paths) + 1):
        for chosen in combinations(paths, count):
            recovered = seed + tuple(item for item in pack.excerpts if item.path in chosen)
            if _fixture_coverage(recovered, case, index) == (4, 4):
                return chosen
    raise AssertionError("fixture evidence should be recoverable")


def _summary(pack: object, gateway: MCPGateway, source_budget: int,
             required: tuple[tuple[str, str], ...]) -> dict:
    payload = gateway._progressive_payload(pack, source_budget)
    data = payload.data
    seed = tuple(item for item in pack.excerpts if any(
        item.path == entry.path and item.start_line == entry.start_line and item.end_line == entry.end_line
        for entry in payload.delivery_excerpts or ()))
    estimator = HeuristicTokenEstimator()
    seed_tokens = sum(estimator.estimate(item.text) for item in payload.delivery_excerpts or ())
    budget = {"requested_context_tokens": 6000, "effective_context_tokens": 6000,
              "benchmark_context_cap": 6000, "budget_capped": False, "force_replay": False,
              "initial_source_delivery_budget": source_budget, "canonical_selection_fixed": True}
    if "progressive_delivery" not in data:
        budget = {key: value for key, value in budget.items()
                  if key not in {"initial_source_delivery_budget", "canonical_selection_fixed"}}
    result = estimator.estimate(json.dumps({**data, "budget": budget}, ensure_ascii=False))
    evidence_map = data.get("evidence_map", [])
    map_text = json.dumps(evidence_map, ensure_ascii=False)
    if "progressive_delivery" in data:
        assert estimator.estimate(map_text) == data["progressive_delivery"]["map_tokens"]
        assert len(evidence_map) == len(pack.excerpts)
        assert all(entry["path"] in pack.selected_files for entry in evidence_map)
        assert all(set(entry) == {"path", "start_line", "end_line", "symbol", "reason",
                                  "complete_file", "delivered"} for entry in evidence_map)
    else:
        assert len(seed) == len(pack.excerpts) and not evidence_map
    assert "selected_range_phases" not in map_text and "required_file_recall" not in map_text
    assert "self.memory.release_request(victim.request_id)" not in map_text
    five = _recovery_paths(pack, seed, CONCEPTS)
    release_paths = _recovery_paths(pack, seed, (), release=True)
    combined = _recovery_paths(pack, seed, CONCEPTS, release=True)
    strict = _recovery_paths(pack, seed, required)
    recoverable = tuple(dict.fromkeys((*combined, *(strict or ()))) if combined is not None else (strict or ()))
    map_discoverable = all(any(entry["path"] == path and not entry["delivered"] and
                               (entry["symbol"] or entry["reason"])
                               for entry in evidence_map) for path in recoverable)
    return {
        "budget": source_budget, "canonical": pack.metrics.estimated_selected_tokens,
        "fingerprint": pack.fingerprint, "seed": seed_tokens,
        "overrun": data.get("progressive_delivery", {}).get("seed_overrun", max(0, seed_tokens - source_budget)),
        "map": data.get("progressive_delivery", {}).get("map_tokens", 0), "result": result,
        "overhead": result - seed_tokens,
        "seed_paths": len({item.path for item in seed}),
        "mapped_paths": len({entry["path"] for entry in evidence_map if not entry["delivered"]}),
        "seed_concepts": sum(_present(seed, path, needle) for path, needle in CONCEPTS),
        "seed_release": any(_present(seed, path, needle) for path, needle in RELEASE),
        "five_calls": len(five) if five is not None else None,
        "release_calls": len(release_paths) if release_paths is not None else None,
        "five_plus_release_calls": len(combined) if combined is not None else None,
        "five_plus_release_paths": combined,
        "required_calls": len(strict) if strict is not None else None,
        "required_paths": strict,
        "mapped_symbols": sum(bool(entry["symbol"]) for entry in evidence_map if not entry["delivered"]),
        "mapped_recovery_discoverable": map_discoverable,
    }


def test_normal_one_shot_and_policy_contract(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    gateway = MCPGateway(config)
    pack = gateway.builder.build(REAL_QUERY, mode="balanced", max_context_tokens=6000)
    expected = gateway._core_payload(pack).data
    normal = gateway.context(REAL_QUERY)
    assert normal == expected
    assert pack.fingerprint == normal["fingerprint"]
    assert pack.metrics.estimated_selected_tokens == 5949
    assert "evidence_map" not in normal and "progressive_delivery" not in normal
    assert gateway.delivery_ledger.line_count == sum(item.end_line - item.start_line + 1 for item in pack.excerpts)
    assert BenchmarkPolicy().initial_source_delivery_budget is None
    assert BenchmarkPolicy(6000, 12000, 1500).expansion_ceiling == 12000
    with pytest.raises(ValueError, match="source delivery budget"):
        BenchmarkPolicy(6000, 12000, 6500)
    surface = asyncio.run(measure_tool_surface(config, "codex-core"))
    assert {item.name for item in surface.tools} == {
        "middleman_project_state", "middleman_session_handoff", "middleman_context",
        "middleman_expand_context", "middleman_compact_output"}
    context_schema = asyncio.run(create_server(config, tool_profile="codex-core").list_tools())
    context_tool = next(item for item in context_schema if item.name == "middleman_context")
    assert "initial_source_delivery_budget" not in json.dumps(context_tool.input_schema)
    assert "seed_budget" not in json.dumps(context_tool.input_schema)


def test_map_reason_is_redacted_before_shortening(pinned: Path) -> None:
    gateway = MCPGateway(GatewayConfig(pinned))
    pack = gateway.builder.build(REAL_QUERY, mode="balanced", max_context_tokens=6000)
    secret = "fake-token-123456789012"
    annotated = replace(pack, excerpts=tuple(replace(item, reasons=("Bearer " + secret,))
                                               for item in pack.excerpts))
    payload = gateway._progressive_payload(annotated, 4000)
    map_text = json.dumps(payload.data["evidence_map"])
    assert secret not in map_text
    assert "[MIDDLE_MAN_REDACTED_SECRET]" in map_text


def test_progressive_ledger_delta_and_freshness(pinned: Path, tmp_path: Path) -> None:
    config = GatewayConfig(pinned)
    identity = BenchmarkIdentity("local2210", "preemption-v4", "optimized", "fixture",
                                 BenchmarkPolicy(6000, 12000, 2000))
    gateway = MCPGateway(config, identity)
    initial = gateway.context(REAL_QUERY)
    pack = gateway._packs[initial["fingerprint"]]
    assert pack.metrics.estimated_selected_tokens == 5949
    assert initial["fingerprint"] == ContextBuilder(config).build(REAL_QUERY, mode="balanced",
                                                                   max_context_tokens=6000).fingerprint
    assert initial["budget"]["canonical_selection_fixed"] is True
    assert initial["progressive_delivery"]["partial_initial_delivery"]
    assert gateway.delivery_ledger.line_count == sum(item["end_line"] - item["start_line"] + 1
                                                      for item in initial["excerpts"])
    assert gateway.delivery_ledger.line_count < sum(item.end_line - item.start_line + 1
                                                     for item in pack.excerpts)
    requested_small = MCPGateway(config, BenchmarkIdentity("localfixed", "preemption-v4", "optimized",
                                                          "fixture", BenchmarkPolicy(6000, 12000, 2000)))
    fixed = requested_small.context(REAL_QUERY, mode="safe", max_context_tokens=3000)
    assert fixed["fingerprint"] == initial["fingerprint"]
    assert fixed["budget"]["requested_context_tokens"] == 3000
    assert fixed["budget"]["effective_context_tokens"] == 6000
    with pytest.raises(ValueError, match="force_replay"):
        requested_small.context(REAL_QUERY, force_replay=True)
    mapped = next(item for item in initial["evidence_map"] if not item["delivered"])
    partial = next((item["path"] for item in initial["evidence_map"] if not item["delivered"] and
                    any(other["path"] == item["path"] and other["delivered"]
                        for other in initial["evidence_map"]) and item["path"] != "middle_man/lab/request.py"),
                   mapped["path"])
    first = gateway.expand_context(initial["fingerprint"], "selected_path", target=partial, core=True)
    assert first["excerpts"] and first["fingerprint"] == initial["fingerprint"]
    initial_lines = {(item["path"], number) for item in initial["excerpts"]
                     for number in range(item["start_line"], item["end_line"] + 1)}
    expanded_lines = {(item["path"], number) for item in first["excerpts"]
                      for number in range(item["start_line"], item["end_line"] + 1)}
    assert not initial_lines & expanded_lines
    assert gateway.server_session_id
    assert gateway._call_sequence == 2
    second = gateway.expand_context(initial["fingerprint"], "selected_path", target=partial, core=True)
    assert second["excerpts"] == []
    assert gateway._call_sequence == 3
    other = next(item["path"] for item in initial["evidence_map"]
                 if not item["delivered"] and item["path"] != partial)
    lines_before = gateway.delivery_ledger.line_count
    with pytest.raises(ValueError, match="expansion budget"):
        gateway.expand_context(initial["fingerprint"], "selected_path", target=other,
                               max_context_tokens=1, core=True)
    assert gateway.delivery_ledger.line_count == lines_before
    with pytest.raises(ValueError, match="max_context_tokens"):
        gateway.expand_context(initial["fingerprint"], "selected_path", target=other,
                               max_context_tokens=12001, core=True)
    with pytest.raises(ValueError):
        gateway.expand_context(initial["fingerprint"], "selected_path", target="../outside", core=True)
    request_path = "middle_man/lab/request.py"
    request_map = [item for item in initial["evidence_map"] if item["path"] == request_path]
    assert request_map
    assert any(item["complete_file"] for item in request_map)
    if request_map and all(item["delivered"] for item in request_map):
        assert gateway.expand_context(initial["fingerprint"], "selected_path",
                                      target=request_path, core=True)["excerpts"] == []
    elif request_map:
        once = gateway.expand_context(initial["fingerprint"], "selected_path", target=request_path, core=True)
        assert once["excerpts"]
        assert gateway.expand_context(initial["fingerprint"], "selected_path",
                                      target=request_path, core=True)["excerpts"] == []

    assert not any(item.path == "middle_man/lab/memory.py" for item in pack.excerpts)
    with pytest.raises(ValueError, match="not in the canonical"):
        gateway.expand_context(initial["fingerprint"], "selected_path",
                               target="middle_man/lab/memory.py", core=True)

    file = tmp_path / "module.py"
    file.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    fresh = MCPGateway(GatewayConfig(tmp_path))
    response = fresh.context("Inspect module.py alpha", paths=["module.py"])
    file.write_text("def alpha():\n    return 2\n", encoding="utf-8")
    with pytest.raises(StaleSourceError):
        fresh.expand_context(response["fingerprint"], "selected_path", target="module.py", core=True)


def test_pinned_seed_sweep(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    gateway = MCPGateway(config)
    builder = ContextBuilder(config)
    queries = {"real_v4": REAL_QUERY, "exact_v4": TASK.prompt, **STRONG}
    required = tuple((unit.path, unit.identifier) for unit in TASK_A_V3_UNITS)
    for name, query in queries.items():
        pack = builder.build(query, mode="balanced", max_context_tokens=6000)
        rows = [_summary(pack, gateway, budget, required) for budget in BUDGETS]
        assert all(row["fingerprint"] == pack.fingerprint for row in rows)
        assert all(row["canonical"] == pack.metrics.estimated_selected_tokens for row in rows)
        assert all(row["map"] < row["result"] for row in rows)
        assert all(row["mapped_recovery_discoverable"] for row in rows)
        for row in rows:
            for path in row["required_paths"] or ():
                assert path in pack.selected_files
        by_budget = {row["budget"]: row for row in rows}
        if name == "real_v4":
            assert by_budget[1500]["seed"] == 1693 and by_budget[1500]["overrun"] == 193
            assert (by_budget[3500]["five_plus_release_calls"], by_budget[3500]["required_calls"]) == (1, None)
            assert (by_budget[4000]["seed_concepts"], by_budget[4000]["seed_release"],
                    by_budget[4000]["five_plus_release_calls"]) == (5, True, 0)
            assert (by_budget[4000]["map"], by_budget[4000]["result"]) == (916, 5919)
        elif name == "exact_v4":
            assert by_budget[1500]["seed"] == 1693 and by_budget[1500]["overrun"] == 193
            assert (by_budget[3500]["five_plus_release_calls"], by_budget[3500]["required_calls"]) == (1, 3)
            assert (by_budget[4000]["seed_concepts"], by_budget[4000]["seed_release"],
                    by_budget[4000]["required_calls"]) == (5, True, 2)
            assert (by_budget[4000]["map"], by_budget[4000]["result"]) == (611, 5359)
        else:
            assert by_budget[4000]["required_calls"] is not None
            assert by_budget[4000]["required_calls"] <= 2
        print("PHASE22_10_MATRIX", name, json.dumps(rows, sort_keys=True))


@pytest.mark.parametrize(("query", "expected_path"), [
    (REAL_QUERY, "middle_man/lab/scheduler.py"),
    (TASK.prompt, "middle_man/lab/memory.py"),
])
def test_candidate_cumulative_delivery(pinned: Path, query: str, expected_path: str) -> None:
    config = GatewayConfig(pinned)
    identity = BenchmarkIdentity("localcandidate", "preemption-v4", "optimized", "fixture",
                                 BenchmarkPolicy(6000, 12000, 4000))
    gateway = MCPGateway(config, identity)
    initial = gateway.context(query)
    pack = gateway._packs[initial["fingerprint"]]
    estimator = HeuristicTokenEstimator()
    source = lambda result: sum(estimator.estimate(item["text"]) for item in result["excerpts"])
    result = lambda value: estimator.estimate(json.dumps(value, ensure_ascii=False))
    mapped = {item["path"] for item in initial["evidence_map"] if not item["delivered"]}
    assert expected_path in mapped
    one = gateway.expand_context(pack.fingerprint, "selected_path", target=expected_path, core=True)
    remaining = sorted(path for path in mapped if path != expected_path and
                       path in {unit.path for unit in TASK_A_V3_UNITS})
    if not remaining:
        remaining = sorted(path for path in mapped if path != expected_path)
    assert remaining
    two = gateway.expand_context(pack.fingerprint, "selected_path", target=remaining[0], core=True)
    rows = [
        {"interactions": 1, "source": source(initial), "result": result(initial)},
        {"interactions": 2, "source": source(initial) + source(one),
         "result": result(initial) + result(one)},
        {"interactions": 3, "source": source(initial) + source(one) + source(two),
         "result": result(initial) + result(one) + result(two)},
    ]
    assert rows[0]["result"] < result(MCPGateway(config)._core_payload(pack).data)
    assert rows[0]["source"] < rows[1]["source"] <= rows[2]["source"]
    assert [row["interactions"] for row in rows] == [1, 2, 3]
    assert gateway.server_session_id and gateway._call_sequence == 3
    print("PHASE22_10_CUMULATIVE", "real_v4" if query == REAL_QUERY else "exact_v4",
          json.dumps({"paths": [expected_path, remaining[0]], "rows": rows}, sort_keys=True))


def test_mapped_request_file_is_delivered_once(pinned: Path) -> None:
    gateway = MCPGateway(GatewayConfig(pinned), BenchmarkIdentity(
        "localrequest", "preemption-v4", "optimized", "fixture", BenchmarkPolicy(6000, 12000, 3500)))
    initial = gateway.context(STRONG["agent"])
    request_path = "middle_man/lab/request.py"
    mapped = [item for item in initial["evidence_map"] if item["path"] == request_path]
    assert mapped and any(not item["delivered"] for item in mapped)
    first = gateway.expand_context(initial["fingerprint"], "selected_path", target=request_path, core=True)
    assert first["excerpts"] and all(item["path"] == request_path for item in first["excerpts"])
    assert gateway.expand_context(initial["fingerprint"], "selected_path",
                                  target=request_path, core=True)["excerpts"] == []


@pytest.mark.parametrize("case", coverage_cases(), ids=lambda case: case.name)
def test_unrelated_seed_sweep(tmp_path: Path, case: object) -> None:
    for path, source in case.files:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    config = GatewayConfig(tmp_path)
    gateway = MCPGateway(config)
    pack = gateway.builder.build(case.query, mode="balanced", max_context_tokens=6000, top_k=10)
    index = RepositoryIndexer(config).index()
    required = tuple((path, "") for path in case.required_files)
    rows = [_summary(pack, gateway, budget, required) for budget in BUDGETS]
    for row, budget in zip(rows, BUDGETS, strict=True):
        payload = gateway._progressive_payload(pack, budget)
        seed = tuple(item for item in pack.excerpts if any(
            item.path == delivered.path and item.start_line == delivered.start_line and
            item.end_line == delivered.end_line for delivered in payload.delivery_excerpts or ()))
        paths = _fixture_recovery(pack, seed, case, index)
        row["fixture_seed_files"], row["fixture_seed_symbols"] = _fixture_coverage(seed, case, index)
        row["fixture_recovery_paths"] = paths
        row["fixture_calls"] = len(paths) if paths is not None else None
    assert all(row["canonical"] == pack.metrics.estimated_selected_tokens for row in rows)
    assert all(row["fixture_seed_files"] == row["fixture_seed_symbols"] == 4 for row in rows)
    assert all(row["fixture_calls"] == 0 for row in rows)
    assert all(row["map"] == 0 for row in rows)
    assert all(row["result"] == {"auth-callback": 416, "queue-cancellation": 621,
                                 "upload-validation": 425}[case.name] for row in rows)
    print("PHASE22_10_FIXTURE", case.name, json.dumps(rows, sort_keys=True))
