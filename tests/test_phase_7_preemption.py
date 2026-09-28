import pytest

from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.events import EventType
from middle_man.lab.memory import AllocationError
from middle_man.lab.request import InferenceRequest, RequestState


def pressure_requests() -> list[InferenceRequest]:
    return [
        InferenceRequest("a", 0.0, prompt_tokens=2, max_output_tokens=3),
        InferenceRequest("b", 0.0, prompt_tokens=2, max_output_tokens=1),
    ]


def test_pressure_preempts_rebuilds_and_preserves_output() -> None:
    config = LabConfig(token_budget=2, kv_blocks=4, tokens_per_block=2, preemption_enabled=True)
    engine = SimulationEngine(config)
    requests = pressure_requests()

    result = engine.run(requests)

    preemptions = [event for event in result.events if event.kind == EventType.REQUEST_PREEMPTED]
    assert preemptions
    assert preemptions[0].blocks > 0
    victim = next(request for request in requests if request.request_id == preemptions[0].request_id)
    assert victim.preemption_count >= 1
    assert victim.recomputed_tokens > 0
    assert victim.output_generated == victim.max_output_tokens
    assert len(victim.output_token_times_ms) == victim.max_output_tokens
    assert all(request.state == RequestState.COMPLETED for request in requests)
    assert result.metrics.aggregate.total_recomputed_tokens == sum(
        request.recomputed_tokens for request in requests
    )
    assert engine.memory.free_block_count == engine.memory.total_blocks


def test_disabled_preemption_keeps_clear_allocation_failure() -> None:
    engine = SimulationEngine(LabConfig(token_budget=2, kv_blocks=4, tokens_per_block=2))
    with pytest.raises(AllocationError, match="could not allocate"):
        engine.run(pressure_requests())
    assert engine.memory.free_block_count == engine.memory.total_blocks


def test_request_larger_than_physical_memory_fails_cleanly() -> None:
    engine = SimulationEngine(LabConfig(
        token_budget=2, kv_blocks=2, tokens_per_block=2, preemption_enabled=True,
    ))
    request = InferenceRequest("too-large", 0.0, prompt_tokens=5, max_output_tokens=1)
    with pytest.raises(AllocationError, match="cannot fit"):
        engine.run([request])
    assert request.state == RequestState.FAILED
    assert engine.memory.free_block_count == engine.memory.total_blocks


def test_preemption_decisions_and_timing_are_deterministic() -> None:
    config = LabConfig(token_budget=2, kv_blocks=4, tokens_per_block=2, preemption_enabled=True)
    first = SimulationEngine(config).run(pressure_requests())
    second = SimulationEngine(config).run(pressure_requests())
    assert first.events == second.events
    assert first.metrics.aggregate == second.metrics.aggregate
    assert [(r.state, r.output_generated, r.completion_time_ms) for r in first.requests] == [
        (r.state, r.output_generated, r.completion_time_ms) for r in second.requests
    ]
