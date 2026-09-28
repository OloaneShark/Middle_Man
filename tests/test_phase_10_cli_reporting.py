import json
import sys

import pytest

from middle_man.cli.main import main
from middle_man.lab.reporting import format_benchmark_suite
from middle_man.lab.serialization import safe_name
from middle_man.lab.suites import build_suite
from middle_man.lab.trace import format_trace


def test_benchmark_listing_does_not_execute_suite(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("listing must not run a benchmark")

    monkeypatch.setattr("middle_man.cli.benchmark.build_suite", unexpected)
    main(["benchmark", "--list"])
    output = capsys.readouterr().out
    assert "scheduler-comparison" in output
    assert "prefix-cache" in output


def test_cli_selects_suite_and_labels_simulated_results(capsys: pytest.CaptureFixture[str]) -> None:
    main(["benchmark", "scheduler-comparison", "--seed", "9"])
    output = capsys.readouterr().out
    assert "SIMULATED PERFORMANCE - NOT REAL GPU PERFORMANCE" in output
    assert "Seed: 9" in output
    assert "Difference: balanced - decode-priority" in output
    assert "TTFT P50/P95" in output


def test_cli_debug_and_json_trace_use_structured_events(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "trace.json"
    main([
        "simulate", "--requests", "1", "--prompt-tokens", "5",
        "--output-tokens", "1", "--token-budget", "2",
        "--debug", "--trace-json", str(destination),
    ])
    output = capsys.readouterr().out
    assert "MIDDLE_MAN SIMULATION TRACE" in output
    assert "prompt 2/5" in output
    assert "prompt 5/5" in output
    assert "request completed" in output
    assert "MEMORY" in output
    data = json.loads(destination.read_text(encoding="utf-8"))
    assert data["simulated"] is True
    assert any(event["kind"] == "prefill_executed" for event in data["events"])


def test_reporting_shows_expected_failure_and_zero_baseline() -> None:
    result = build_suite("memory-pressure").run()
    report = format_benchmark_suite(result)
    assert "FAILED: AllocationError" in report
    assert "SIMULATED PERFORMANCE" in report
    assert "Difference: constrained-preemption - comfortable" in report

    prefix_report = format_benchmark_suite(build_suite("prefix-cache").run())
    assert "n/a (zero baseline)" in prefix_report


def test_core_benchmark_command_does_not_need_matplotlib(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    main(["benchmark", "mixed"])
    assert "MIDDLE_MAN BENCHMARK" in capsys.readouterr().out


def test_safe_output_names_and_trace_are_deterministic() -> None:
    assert safe_name("../Scheduler Comparison") == "scheduler-comparison"
    with pytest.raises(ValueError):
        safe_name("...")
    first = build_suite("mixed").cases[0].run()
    second = build_suite("mixed").cases[0].run()
    # Trace formatting consumes the same immutable event sequence on both runs.
    from middle_man.lab.engine import SimulationEngine
    requests = build_suite("mixed").cases[0].workload.create_requests()
    trace = format_trace(SimulationEngine().run(requests))
    assert "SIMULATED TIME" in trace
    assert first.events == second.events
