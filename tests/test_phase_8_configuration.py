from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.request import InferenceRequest


def test_same_key_with_different_declared_lengths_does_not_share() -> None:
    engine = SimulationEngine(LabConfig(
        token_budget=16, kv_blocks=8, tokens_per_block=16, prefix_cache_enabled=True,
    ))
    requests = [
        InferenceRequest("first", 0.0, 24, 0, shared_prefix_tokens=20, prefix_key="key"),
        InferenceRequest("second", 10.0, 24, 0, shared_prefix_tokens=16, prefix_key="key"),
    ]

    result = engine.run(requests)

    assert result.metrics.aggregate.prefix_cache_hits == 0
    assert result.metrics.aggregate.prefix_cache_misses == 2
    assert result.prompt_tokens_processed == 48
    assert requests[1].prefix_reused_tokens == 0
    assert engine.memory.free_block_count == engine.memory.total_blocks
