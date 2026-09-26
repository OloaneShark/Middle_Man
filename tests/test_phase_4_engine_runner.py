from middle_man.lab.clock import VirtualClock
from middle_man.lab.config import LabConfig, RunnerCostConfig, SchedulerKind
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.request import InferenceRequest, RequestState
from middle_man.lab.runner import SimulatedModelRunner
from middle_man.lab.scheduler import DecodePriorityScheduler
from middle_man.lab.work import SchedulePlan, WorkItem, WorkKind


def test_simulated_runner_returns_deterministic_costs() -> None:
    request = InferenceRequest("req-1", 0.0, prompt_tokens=8, max_output_tokens=1)
    request.mark_admitted()
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
