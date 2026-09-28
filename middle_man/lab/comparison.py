from __future__ import annotations

from dataclasses import dataclass

from middle_man.lab.metrics import AggregateMetrics


COMPARISON_FIELDS = (
    "total_prompt_tokens_processed",
    "prefix_reused_tokens",
    "elapsed_ms",
    "total_throughput_tokens_per_s",
    "p50_ttft_ms",
    "p95_ttft_ms",
    "p50_e2e_ms",
    "p95_e2e_ms",
    "peak_kv_used_blocks",
    "preemption_count",
    "total_recomputed_tokens",
    "scheduler_iterations",
)


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    baseline: float
    variant: float
    absolute_delta: float
    percentage_delta: float | None


@dataclass(frozen=True)
class ComparisonResult:
    baseline_case: str
    variant_case: str
    differences: tuple[MetricDelta, ...]


def compare_aggregates(
    baseline_name: str,
    baseline: AggregateMetrics,
    variant_name: str,
    variant: AggregateMetrics,
    fields: tuple[str, ...] = COMPARISON_FIELDS,
) -> ComparisonResult:
    differences = []
    for field in fields:
        before = getattr(baseline, field)
        after = getattr(variant, field)
        if before is None or after is None:
            continue
        delta = after - before
        differences.append(MetricDelta(
            field,
            float(before),
            float(after),
            float(delta),
            float(delta / before * 100) if before else None,
        ))
    return ComparisonResult(baseline_name, variant_name, tuple(differences))
