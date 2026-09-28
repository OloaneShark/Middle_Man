from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

from middle_man.lab.events import EventType, SimulationEvent
from middle_man.lab.memory import KVBlockManager
from middle_man.lab.prefix_cache import PrefixCache
from middle_man.lab.request import InferenceRequest, RequestState


def percentile(values: list[float], rank: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * rank / 100
    low, high = floor(position), ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class KVSample:
    time_ms: float
    used_blocks: int
    total_blocks: int
    cached_blocks: int = 0


@dataclass(frozen=True)
class RequestMetrics:
    request_id: str
    arrival_time_ms: float
    first_token_time_ms: float | None
    completion_time_ms: float | None
    prompt_tokens: int
    output_tokens: int
    ttft_ms: float | None
    e2e_ms: float | None
    inter_token_latency_ms: float | None
    preemption_count: int
    recomputed_tokens: int
    prefix_cache_hit: bool
    prefix_reused_tokens: int


@dataclass(frozen=True)
class AggregateMetrics:
    total_requests: int
    completed_requests: int
    failed_requests: int
    total_prompt_tokens_processed: int
    total_output_tokens_generated: int
    total_recomputed_tokens: int
    total_tokens_processed: int
    elapsed_ms: float
    prompt_throughput_tokens_per_s: float
    output_throughput_tokens_per_s: float
    total_throughput_tokens_per_s: float
    average_ttft_ms: float | None
    p50_ttft_ms: float | None
    p95_ttft_ms: float | None
    p99_ttft_ms: float | None
    average_e2e_ms: float | None
    p50_e2e_ms: float | None
    p95_e2e_ms: float | None
    p99_e2e_ms: float | None
    average_inter_token_latency_ms: float | None
    scheduler_iterations: int
    preemption_count: int
    kv_used_blocks: int
    kv_utilization: float
    peak_kv_used_blocks: int
    peak_kv_utilization: float
    peak_prefix_cached_blocks: int
    peak_prefix_cache_utilization: float
    prefix_cache_hits: int
    prefix_cache_misses: int
    prefix_reused_tokens: int
    prefix_cache_hit_rate: float


@dataclass(frozen=True)
class MetricsResult:
    requests: tuple[RequestMetrics, ...]
    aggregate: AggregateMetrics
    kv_samples: tuple[KVSample, ...]


class MetricsCollector:
    def __init__(self, memory: KVBlockManager, cache: PrefixCache | None = None) -> None:
        self.memory = memory
        self.cache = cache
        self.samples: list[KVSample] = []

    def sample(self, time_ms: float) -> None:
        snapshot = self.memory.snapshot()
        cached = self.cache.cached_block_count if self.cache else 0
        self.samples.append(KVSample(time_ms, snapshot.used_blocks, snapshot.total_blocks, cached))

    def build(
        self,
        requests: list[InferenceRequest],
        events: tuple[SimulationEvent, ...],
        elapsed_ms: float,
        iterations: int,
        prompt_tokens: int,
        output_tokens: int,
    ) -> MetricsResult:
        per_request = tuple(self._request_metrics(request) for request in requests)
        ttft = [item.ttft_ms for item in per_request if item.ttft_ms is not None]
        e2e = [item.e2e_ms for item in per_request if item.e2e_ms is not None]
        itl = [item.inter_token_latency_ms for item in per_request if item.inter_token_latency_ms is not None]
        recomputed = sum(request.recomputed_tokens for request in requests)
        hits = sum(event.kind == EventType.PREFIX_CACHE_HIT for event in events)
        misses = sum(event.kind == EventType.PREFIX_CACHE_MISS for event in events)
        peak = max((sample.used_blocks for sample in self.samples), default=0)
        peak_cached = max((sample.cached_blocks for sample in self.samples), default=0)
        current = self.memory.snapshot()

        def throughput(tokens: int) -> float:
            return tokens * 1000 / elapsed_ms if elapsed_ms > 0 else 0.0

        aggregate = AggregateMetrics(
            total_requests=len(requests),
            completed_requests=sum(request.state == RequestState.COMPLETED for request in requests),
            failed_requests=sum(request.state == RequestState.FAILED for request in requests),
            total_prompt_tokens_processed=prompt_tokens,
            total_output_tokens_generated=output_tokens,
            total_recomputed_tokens=recomputed,
            total_tokens_processed=prompt_tokens + output_tokens + recomputed,
            elapsed_ms=elapsed_ms,
            prompt_throughput_tokens_per_s=throughput(prompt_tokens),
            output_throughput_tokens_per_s=throughput(output_tokens),
            total_throughput_tokens_per_s=throughput(prompt_tokens + output_tokens + recomputed),
            average_ttft_ms=sum(ttft) / len(ttft) if ttft else None,
            p50_ttft_ms=percentile(ttft, 50),
            p95_ttft_ms=percentile(ttft, 95),
            p99_ttft_ms=percentile(ttft, 99),
            average_e2e_ms=sum(e2e) / len(e2e) if e2e else None,
            p50_e2e_ms=percentile(e2e, 50),
            p95_e2e_ms=percentile(e2e, 95),
            p99_e2e_ms=percentile(e2e, 99),
            average_inter_token_latency_ms=sum(itl) / len(itl) if itl else None,
            scheduler_iterations=iterations,
            preemption_count=sum(request.preemption_count for request in requests),
            kv_used_blocks=current.used_blocks,
            kv_utilization=current.utilization,
            peak_kv_used_blocks=peak,
            peak_kv_utilization=peak / current.total_blocks,
            peak_prefix_cached_blocks=peak_cached,
            peak_prefix_cache_utilization=peak_cached / current.total_blocks,
            prefix_cache_hits=hits,
            prefix_cache_misses=misses,
            prefix_reused_tokens=sum(request.prefix_reused_tokens for request in requests),
            prefix_cache_hit_rate=hits / (hits + misses) if hits + misses else 0.0,
        )
        return MetricsResult(per_request, aggregate, tuple(self.samples))

    @staticmethod
    def _request_metrics(request: InferenceRequest) -> RequestMetrics:
        times = request.output_token_times_ms
        gaps = [end - start for start, end in zip(times, times[1:])]
        return RequestMetrics(
            request_id=request.request_id,
            arrival_time_ms=request.arrival_time_ms,
            first_token_time_ms=request.first_token_time_ms,
            completion_time_ms=request.completion_time_ms,
            prompt_tokens=request.prompt_tokens,
            output_tokens=request.output_generated,
            ttft_ms=request.first_token_time_ms - request.arrival_time_ms if request.first_token_time_ms is not None else None,
            e2e_ms=request.completion_time_ms - request.arrival_time_ms if request.completion_time_ms is not None else None,
            inter_token_latency_ms=sum(gaps) / len(gaps) if gaps else None,
            preemption_count=request.preemption_count,
            recomputed_tokens=request.recomputed_tokens,
            prefix_cache_hit=request.prefix_cache_hit,
            prefix_reused_tokens=request.prefix_reused_tokens,
        )
