from __future__ import annotations

from dataclasses import asdict

from middle_man.lab.benchmarks import BenchmarkSuiteResult
from middle_man.lab.comparison import ComparisonResult
from middle_man.lab.events import EventType


DISPLAY_FIELDS = {
    "scheduler-comparison": ("p50_ttft_ms", "p95_ttft_ms", "p50_e2e_ms",
                             "total_throughput_tokens_per_s", "scheduler_iterations"),
    "prefix-cache": ("total_prompt_tokens_processed", "prefix_reused_tokens",
                     "elapsed_ms", "peak_kv_used_blocks", "total_throughput_tokens_per_s"),
    "memory-pressure": ("preemption_count", "total_recomputed_tokens", "elapsed_ms",
                        "p50_ttft_ms", "p50_e2e_ms", "total_throughput_tokens_per_s",
                        "peak_kv_used_blocks"),
    "token-budget": ("scheduler_iterations", "p50_ttft_ms", "p50_e2e_ms",
                     "total_throughput_tokens_per_s"),
    "active-sequences": ("p50_ttft_ms", "p50_e2e_ms",
                         "total_throughput_tokens_per_s", "scheduler_iterations",
                         "peak_kv_used_blocks"),
    "chunked-prefill": ("scheduler_iterations", "p50_ttft_ms", "elapsed_ms"),
}


def _number(value: float | None, unit: str = "") -> str:
    return f"{value:.2f}{unit}" if value is not None else "n/a"


def _format_comparison(comparison: ComparisonResult, fields: tuple[str, ...]) -> list[str]:
    lines = [f"Difference: {comparison.variant_case} - {comparison.baseline_case}"]
    by_name = {item.metric: item for item in comparison.differences}
    for field in fields:
        if field not in by_name:
            continue
        difference = by_name[field]
        change = (
            f"{difference.percentage_delta:+.1f}%"
            if difference.percentage_delta is not None else "n/a (zero baseline)"
        )
        lines.append(f"  {field}: {difference.absolute_delta:+.2f} ({change})")
    return lines


def format_benchmark_suite(result: BenchmarkSuiteResult, verbose: bool = False) -> str:
    lines = [
        "MIDDLE_MAN BENCHMARK",
        "SIMULATED PERFORMANCE - NOT REAL GPU PERFORMANCE",
        f"Benchmark: {result.name}",
        f"Workload: {result.cases[0].workload_name if result.cases else 'n/a'}",
        f"Seed: {result.cases[0].seed if result.cases else 'n/a'}",
    ]
    for case in result.cases:
        lines.extend(("", case.case_name.upper(), f"Requests: {case.request_count}"))
        if case.failure:
            lines.append(f"FAILED: {case.failure.exception_type}: {case.failure.message}")
            continue
        assert case.metrics is not None
        summary = case.metrics.aggregate
        lines.extend((
            f"Completed: {summary.completed_requests}",
            f"Iterations: {summary.scheduler_iterations}",
            f"Prompt work: {summary.total_prompt_tokens_processed} tokens",
            f"Output: {summary.total_output_tokens_generated} tokens",
            f"Elapsed: {summary.elapsed_ms:.2f} ms",
            f"Total throughput: {summary.total_throughput_tokens_per_s:.2f} tokens/s",
            f"TTFT P50/P95: {_number(summary.p50_ttft_ms, ' ms')} / {_number(summary.p95_ttft_ms, ' ms')}",
            f"E2E P50/P95: {_number(summary.p50_e2e_ms, ' ms')} / {_number(summary.p95_e2e_ms, ' ms')}",
            f"Peak KV: {summary.peak_kv_used_blocks}/{case.config.kv_blocks} blocks",
            f"Preemptions: {summary.preemption_count}  Recomputed: {summary.total_recomputed_tokens} tokens",
            f"Prefix hits: {summary.prefix_cache_hits}  Reused: {summary.prefix_reused_tokens} tokens",
        ))
        if result.name == "chunked-prefill" and case.metrics.requests:
            longest = max(case.metrics.requests, key=lambda request: request.prompt_tokens)
            chunks = [
                event for event in case.events
                if event.kind == EventType.PREFILL_EXECUTED
                and event.request_id == longest.request_id
            ]
            lines.append(
                f"Long prompt {longest.request_id}: {len(chunks)} prefill chunks, "
                f"{sum(event.tokens for event in chunks)} executed tokens"
            )
        if verbose:
            lines.extend(f"  {name}: {value}" for name, value in asdict(summary).items())
    fields = DISPLAY_FIELDS.get(result.name, ())
    for comparison in result.comparisons:
        lines.extend(("", *_format_comparison(comparison, fields)))
    return "\n".join(lines)
