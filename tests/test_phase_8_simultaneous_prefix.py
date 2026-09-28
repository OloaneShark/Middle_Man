from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.events import EventType
from middle_man.lab.request import InferenceRequest, RequestState


def test_simultaneous_compatible_requests_share_one_computed_prefix() -> None:
    config = LabConfig(
        token_budget=4, kv_blocks=8, tokens_per_block=2, prefix_cache_enabled=True,
    )
    engine = SimulationEngine(config)
    requests = [
        InferenceRequest("first", 0.0, 4, 1, shared_prefix_tokens=4, prefix_key="same"),
        InferenceRequest("second", 0.0, 4, 1, shared_prefix_tokens=4, prefix_key="same"),
    ]

    result = engine.run(requests)

    assert result.prompt_tokens_processed == 4
    assert result.metrics.aggregate.prefix_cache_hits == 1
    assert result.metrics.aggregate.peak_prefix_cached_blocks == 2
    assert result.metrics.aggregate.peak_prefix_cache_utilization == 2 / 8
    assert requests[1].shared_blocks == []
    assert any(event.kind == EventType.PREFIX_CACHE_HIT and event.request_id == "second"
               for event in result.events)
    assert all(request.state == RequestState.COMPLETED for request in requests)
    assert engine.memory.free_block_count == engine.memory.total_blocks
