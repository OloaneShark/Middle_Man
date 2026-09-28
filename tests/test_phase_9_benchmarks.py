import csv
import json
from datetime import datetime, timezone

import pytest

from middle_man.lab.benchmarks import BenchmarkCase
from middle_man.lab.comparison import compare_aggregates
from middle_man.lab.events import EventType
from middle_man.lab.request import RequestState
from middle_man.lab.serialization import save_csv, save_json
from middle_man.lab.suites import available_benchmarks, build_suite
from middle_man.lab.workloads import WorkloadSpec


@pytest.mark.parametrize("name", [name for name, _ in available_benchmarks()])
def test_every_benchmark_suite_executes_with_isolated_kv(name: str) -> None:
    suite = build_suite(name, seed=13)
    result = suite.run()

    assert result.cases
    assert all(case.workload is suite.cases[0].workload for case in suite.cases)
    assert all(case.final_kv_used_blocks == 0 for case in result.cases)
    assert all(case.request_count == len(suite.cases[0].workload.requests) for case in result.cases)
    assert any(case.metrics is not None for case in result.cases)


def test_comparison_cases_construct_distinct_request_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = []
    original = WorkloadSpec.create_requests

    def record(self: WorkloadSpec):
        requests = original(self)
        observed.append(requests)
        return requests

    monkeypatch.setattr(WorkloadSpec, "create_requests", record)
    suite = build_suite("prefix-cache", seed=5)
    result = suite.run()

    assert len(observed) == len(suite.cases) == 2
    assert all(a is not b for a, b in zip(*observed))
    assert all(request.state == RequestState.COMPLETED for case in observed for request in case)
    assert result.cases[0].config.prefix_cache_enabled is False
    assert result.cases[1].config.prefix_cache_enabled is True


def test_scheduler_and_prefix_comparisons_measure_actual_differences() -> None:
    scheduler = build_suite("scheduler-comparison").run()
    assert scheduler.cases[0].metrics.aggregate != scheduler.cases[1].metrics.aggregate
    assert scheduler.comparisons[0].differences

    prefix = build_suite("prefix-cache").run()
    off, on = (case.metrics.aggregate for case in prefix.cases)
    assert on.total_prompt_tokens_processed < off.total_prompt_tokens_processed
    assert on.prefix_cache_hits > 0
    assert on.prefix_reused_tokens > 0
    assert on.peak_prefix_cached_blocks > 0


def test_memory_pressure_records_preemption_and_expected_failure() -> None:
    comfortable, constrained, failed = build_suite("memory-pressure").run().cases
    assert comfortable.metrics.aggregate.preemption_count == 0
    assert constrained.metrics.aggregate.preemption_count > 0
    assert constrained.metrics.aggregate.total_recomputed_tokens > 0
    assert constrained.metrics.aggregate.elapsed_ms > comfortable.metrics.aggregate.elapsed_ms
    assert failed.failure.exception_type == "AllocationError"
    assert failed.metrics is None
    assert failed.final_kv_used_blocks == 0


def test_budgets_active_limits_and_chunked_prefill_are_measured() -> None:
    budgets = build_suite("token-budget").run().cases
    assert budgets[0].metrics.aggregate.scheduler_iterations > budgets[-1].metrics.aggregate.scheduler_iterations

    active = build_suite("active-sequences").run().cases
    assert active[0].metrics.aggregate.scheduler_iterations > active[-1].metrics.aggregate.scheduler_iterations

    chunks = build_suite("chunked-prefill").run().cases
    low_budget_prefills = [
        event for event in chunks[0].events
        if event.kind == EventType.PREFILL_EXECUTED and event.request_id == "long-00"
    ]
    assert len(low_budget_prefills) > 1
    assert all(event.tokens <= chunks[0].config.token_budget for event in low_budget_prefills)


def test_comparison_zero_baseline_has_no_percentage() -> None:
    off, on = build_suite("prefix-cache").run().cases
    comparison = compare_aggregates("off", off.metrics.aggregate, "on", on.metrics.aggregate)
    reused = next(item for item in comparison.differences if item.metric == "prefix_reused_tokens")
    assert reused.baseline == 0
    assert reused.variant > 0
    assert reused.percentage_delta is None


def test_repeated_identical_suites_produce_identical_simulated_results() -> None:
    first = build_suite("memory-pressure", seed=19).run()
    second = build_suite("memory-pressure", seed=19).run()
    assert first == second


def test_only_expected_resource_failures_become_benchmark_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from middle_man.lab.engine import SimulationEngine

    def broken_run(self, requests):
        raise TypeError("programming error")

    monkeypatch.setattr(SimulationEngine, "run", broken_run)
    case: BenchmarkCase = build_suite("mixed").cases[0]
    with pytest.raises(TypeError, match="programming error"):
        case.run()


def test_json_and_csv_include_simulation_metadata_and_failure(tmp_path) -> None:
    result = build_suite("memory-pressure", seed=3).run()
    timestamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
    json_path = save_json(result, tmp_path, timestamp=timestamp)
    csv_path = save_csv(result, tmp_path, timestamp=timestamp)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["metadata"]["simulated"] is True
    assert data["metadata"]["middle_man_version"]
    assert data["metadata"]["timestamp_utc"] == "2026-01-02T00:00:00+00:00"
    assert data["suite"]["cases"][0]["workload_name"] == "memory-pressure"
    assert data["suite"]["cases"][0]["config"]["token_budget"] == 2
    assert data["suite"]["cases"][0]["metrics"]["aggregate"]["elapsed_ms"] > 0
    assert data["suite"]["cases"][2]["failure"]["exception_type"] == "AllocationError"

    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3
    assert all(row["simulated"] == "True" and row["seed"] == "3" for row in rows)
    assert rows[2]["failure_type"] == "AllocationError"
    assert rows[1]["preemption_count"] != "0"
