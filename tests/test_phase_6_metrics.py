from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.metrics import percentile
from middle_man.lab.request import InferenceRequest


def test_percentiles_cover_empty_single_and_interpolation() -> None:
    assert percentile([], 95) is None
    assert percentile([7.0], 99) == 7.0
    assert percentile([0.0, 10.0], 50) == 5.0
    assert percentile([0.0, 10.0], 95) == 9.5


def test_metrics_come_from_request_timestamps_and_executed_work() -> None:
    engine = SimulationEngine(LabConfig(token_budget=2, tokens_per_block=2, kv_blocks=8))
    request = InferenceRequest("one", 0.0, prompt_tokens=2, max_output_tokens=2)
    result = engine.run([request])
    one = result.metrics.requests[0]
    total = result.metrics.aggregate

    assert one.first_token_time_ms == request.output_token_times_ms[0]
    assert one.ttft_ms == request.first_token_time_ms - request.arrival_time_ms
    assert one.e2e_ms == result.elapsed_ms
    assert one.inter_token_latency_ms == (
        request.output_token_times_ms[1] - request.output_token_times_ms[0]
    )
    assert total.total_prompt_tokens_processed == 2
    assert total.total_output_tokens_generated == 2
    assert total.total_tokens_processed == 4
    assert total.p50_ttft_ms == one.ttft_ms
    assert total.p99_e2e_ms == one.e2e_ms
    assert total.total_throughput_tokens_per_s == 4000 / result.elapsed_ms
    assert total.peak_kv_used_blocks == 2
    assert total.kv_used_blocks == 0
    assert result.metrics.kv_samples[-1].used_blocks == 0


def test_metrics_handle_empty_and_zero_output_runs() -> None:
    engine = SimulationEngine()
    empty = engine.run([]).metrics.aggregate
    assert empty.total_requests == 0
    assert empty.total_throughput_tokens_per_s == 0
    assert empty.p95_ttft_ms is None
    assert empty.p99_e2e_ms is None
    assert empty.prefix_cache_hit_rate == 0

    request = InferenceRequest("no-output", 0.0, prompt_tokens=2, max_output_tokens=0)
    zero_output = engine.run([request]).metrics
    assert zero_output.requests[0].ttft_ms is None
    assert zero_output.requests[0].e2e_ms is not None
    assert zero_output.aggregate.output_throughput_tokens_per_s == 0
