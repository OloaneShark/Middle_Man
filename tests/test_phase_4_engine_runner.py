from __future__ import annotations

from middle_man.cli.main import main
from middle_man.lab.clock import VirtualClock
from middle_man.lab.config import LabConfig, RunnerCostConfig, SchedulerKind
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.request import InferenceRequest, RequestState
from middle_man.lab.runner import ExecutionResult, SimulatedModelRunner
from middle_man.lab.scheduler import DecodePriorityScheduler
from middle_man.lab.work import SchedulePlan, WorkItem, WorkKind


class RecordingRunner:
    def __init__(self) -> None:
        self.delegate = SimulatedModelRunner()
        self.plans: list[SchedulePlan] = []
        self.decode_prompt_progress: list[int] = []

    def execute(
        self,
        plan: SchedulePlan,
        requests: dict[str, InferenceRequest],
    ) -> ExecutionResult:
        self.plans.append(plan)
        for item in plan.items:
            if item.kind == WorkKind.DECODE:
                self.decode_prompt_progress.append(requests[item.request_id].prompt_processed)
        return self.delegate.execute(plan, requests)


class RecordingScheduler:
    def __init__(self) -> None:
        self.delegate = DecodePriorityScheduler()
        self.active_counts: list[int] = []

    def plan(self, requests: list[InferenceRequest], token_budget: int) -> SchedulePlan:
        self.active_counts.append(len(requests))
        return self.delegate.plan(requests, token_budget)


def test_simulated_runner_returns_deterministic_costs() -> None:
    request = InferenceRequest("req-1", 0.0, prompt_tokens=8, max_output_tokens=1)
    request.mark_admitted(now_ms=0.0)
    plan = SchedulePlan((WorkItem("req-1", WorkKind.PREFILL, 4),), token_budget=4)
    runner = SimulatedModelRunner(RunnerCostConfig(prefill_base_ms=1, prefill_token_ms=0.5))
    result = runner.execute(plan, {"req-1": request})
    assert result.elapsed_ms == 3.0
    assert result.prompt_tokens == 4
    assert result.output_tokens == 0


def test_engine_completes_requests_and_releases_memory() -> None:
    config = LabConfig(token_budget=4, kv_blocks=16, tokens_per_block=2, scheduler=SchedulerKind.DECODE_PRIORITY)
    clock = VirtualClock()
    engine = SimulationEngine(config, clock=clock)
    requests = [
        InferenceRequest("req-1", 0.0, prompt_tokens=5, max_output_tokens=2),
        InferenceRequest("req-2", 0.0, prompt_tokens=2, max_output_tokens=1),
    ]
    result = engine.run(requests)
    assert all(request.state == RequestState.COMPLETED for request in requests)
    assert result.prompt_tokens_processed == 7
    assert result.output_tokens_generated == 3
    assert result.iterations > 0
    assert result.elapsed_ms == clock.now_ms()
    assert engine.memory.free_block_count == engine.memory.total_blocks
    assert all(engine.memory.request_blocks(request.request_id) == () for request in requests)
    assert all(request.allocated_blocks == [] for request in requests)


def test_engine_respects_later_arrival_without_sleeping() -> None:
    config = LabConfig(token_budget=8, kv_blocks=16, tokens_per_block=4)
    clock = VirtualClock()
    engine = SimulationEngine(config, clock=clock, scheduler=DecodePriorityScheduler())
    requests = [
        InferenceRequest("req-1", 20.0, prompt_tokens=1, max_output_tokens=1),
    ]
    engine.run(requests)
    assert requests[0].state == RequestState.COMPLETED
    assert clock.now_ms() >= 20.0


def test_zero_output_request_completes_after_prefill_and_releases_memory() -> None:
    config = LabConfig(token_budget=4, kv_blocks=8, tokens_per_block=2)
    engine = SimulationEngine(config)
    request = InferenceRequest("zero-output", 0.0, prompt_tokens=7, max_output_tokens=0)

    result = engine.run([request])

    assert request.state == RequestState.COMPLETED
    assert request.prompt_processed == 7
    assert request.output_generated == 0
    assert request.completion_time_ms == engine.clock.now_ms()
    assert result.prompt_tokens_processed == 7
    assert result.output_tokens_generated == 0
    assert engine.memory.free_block_count == engine.memory.total_blocks
    assert engine.memory.request_blocks(request.request_id) == ()


def test_zero_prompt_and_zero_output_request_terminates_without_work() -> None:
    clock = VirtualClock(current_ms=3.0)
    engine = SimulationEngine(clock=clock)
    request = InferenceRequest("empty", 0.0, prompt_tokens=0, max_output_tokens=0)

    result = engine.run([request])

    assert request.state == RequestState.COMPLETED
    assert request.completion_time_ms == 3.0
    assert result.iterations == 0
    assert result.prompt_tokens_processed == 0
    assert result.output_tokens_generated == 0
    assert engine.memory.free_block_count == engine.memory.total_blocks


def test_repeated_engine_runs_report_only_current_run_statistics() -> None:
    engine = SimulationEngine(LabConfig(token_budget=4, kv_blocks=16, tokens_per_block=2))
    first = engine.run([InferenceRequest("first", 0.0, prompt_tokens=4, max_output_tokens=2)])
    second = engine.run(
        [
            InferenceRequest(
                "second",
                engine.clock.now_ms(),
                prompt_tokens=1,
                max_output_tokens=1,
            )
        ]
    )

    assert first.prompt_tokens_processed == 4
    assert first.output_tokens_generated == 2
    assert second.prompt_tokens_processed == 1
    assert second.output_tokens_generated == 1
    assert second.iterations == 2


def test_engine_chunks_prefill_across_iterations_before_decode() -> None:
    runner = RecordingRunner()
    config = LabConfig(token_budget=4, kv_blocks=16, tokens_per_block=4)
    engine = SimulationEngine(config, runner=runner)
    request = InferenceRequest("chunked", 0.0, prompt_tokens=20, max_output_tokens=1)

    result = engine.run([request])

    prefill_plans = [
        plan
        for plan in runner.plans
        if any(item.kind == WorkKind.PREFILL for item in plan.items)
    ]
    assert len(prefill_plans) == 5
    assert all(plan.scheduled_tokens <= config.token_budget for plan in runner.plans)
    assert all(plan.items[0].tokens == 4 for plan in prefill_plans)
    assert runner.decode_prompt_progress == [20]
    assert result.iterations == 6
    assert result.prompt_tokens_processed == 20
    assert result.output_tokens_generated == 1
    assert request.state == RequestState.COMPLETED


def test_engine_respects_max_active_sequences() -> None:
    scheduler = RecordingScheduler()
    config = LabConfig(
        token_budget=2,
        max_active_sequences=2,
        kv_blocks=16,
        tokens_per_block=2,
    )
    engine = SimulationEngine(config, scheduler=scheduler)
    requests = [
        InferenceRequest(f"req-{index}", 0.0, prompt_tokens=2, max_output_tokens=1)
        for index in range(5)
    ]

    engine.run(requests)

    assert max(scheduler.active_counts) == config.max_active_sequences
    assert all(count <= config.max_active_sequences for count in scheduler.active_counts)
    assert all(request.state == RequestState.COMPLETED for request in requests)


def test_cli_without_subcommand_prints_help(capsys: object) -> None:
    main([])
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert output.startswith("usage: middle-man")
    assert "simulate" in output
