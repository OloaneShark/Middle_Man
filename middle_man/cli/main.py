from __future__ import annotations

import argparse

from middle_man.cli.benchmark import run_benchmark
from middle_man.cli.gateway import add_gateway_commands, run_gateway
from middle_man.lab.config import LabConfig, SchedulerKind
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.request import InferenceRequest
from middle_man.lab.serialization import save_trace_json
from middle_man.lab.suites import SUITE_DESCRIPTIONS
from middle_man.lab.trace import format_trace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="middle-man", description="Middle_Man simulation tools")
    subparsers = parser.add_subparsers(dest="command")

    simulate = subparsers.add_parser("simulate", help="run a deterministic serving simulation")
    simulate.add_argument("--requests", type=int, default=8)
    simulate.add_argument("--prompt-tokens", type=int, default=32)
    simulate.add_argument("--output-tokens", type=int, default=8)
    simulate.add_argument("--token-budget", type=int, default=64)
    simulate.add_argument("--kv-blocks", type=int, default=128)
    simulate.add_argument("--tokens-per-block", type=int, default=16)
    simulate.add_argument("--max-active-sequences", type=int, default=16)
    simulate.add_argument("--arrival-gap-ms", type=float, default=0.0)
    simulate.add_argument("--preemption", action="store_true")
    simulate.add_argument("--prefix-cache", action="store_true")
    simulate.add_argument("--prefix-key", default="shared-prefix")
    simulate.add_argument("--shared-prefix-tokens", type=int, default=0)
    simulate.add_argument("--scheduler", choices=[item.value for item in SchedulerKind], default=SchedulerKind.DECODE_PRIORITY.value)
    simulate.add_argument("--debug", action="store_true", help="print a readable event trace")
    simulate.add_argument("--trace-json", help="save structured simulation events to JSON")

    benchmark = subparsers.add_parser("benchmark", help="run deterministic Lab benchmarks")
    benchmark.add_argument("name", nargs="?", choices=list(SUITE_DESCRIPTIONS))
    benchmark.add_argument("--list", action="store_true", help="list benchmark suites")
    benchmark.add_argument("--seed", type=int, default=7)
    benchmark.add_argument("--json", action="store_true", help="save structured JSON")
    benchmark.add_argument("--csv", action="store_true", help="save flat CSV")
    benchmark.add_argument("--plot", action="store_true", help="save optional matplotlib plots")
    benchmark.add_argument("--output-dir", default="benchmark_results")
    benchmark.add_argument("--verbose", action="store_true")

    add_gateway_commands(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    if args.command == "simulate":
        run_simulate(args)
        return
    if args.command == "benchmark":
        run_benchmark(args)
        return
    if args.command in {"index", "inspect", "context", "cache"}:
        run_gateway(args)
        return
    parser.error(f"unknown command: {args.command}")


def run_simulate(args: argparse.Namespace) -> None:
    config = LabConfig(
        token_budget=args.token_budget,
        kv_blocks=args.kv_blocks,
        tokens_per_block=args.tokens_per_block,
        max_active_sequences=args.max_active_sequences,
        scheduler=SchedulerKind(args.scheduler),
        preemption_enabled=args.preemption,
        prefix_cache_enabled=args.prefix_cache,
    )
    requests = [
        InferenceRequest(
            request_id=f"req-{index + 1:03d}",
            arrival_time_ms=index * args.arrival_gap_ms,
            prompt_tokens=args.prompt_tokens,
            max_output_tokens=args.output_tokens,
            shared_prefix_tokens=args.shared_prefix_tokens,
            prefix_key=args.prefix_key if args.shared_prefix_tokens else None,
        )
        for index in range(args.requests)
    ]
    result = SimulationEngine(config).run(requests)
    metrics = result.metrics.aggregate

    def duration(value: float | None) -> str:
        return f"{value:.2f} ms" if value is not None else "n/a"

    print("MIDDLE_MAN SIMULATION")
    print(f"Requests: {metrics.total_requests}  Completed: {metrics.completed_requests}")
    print(f"Iterations: {metrics.scheduler_iterations}")
    print(f"Elapsed simulated time: {metrics.elapsed_ms:.2f} ms")
    print(f"Prompt tokens: {metrics.total_prompt_tokens_processed}")
    print(f"Output tokens: {metrics.total_output_tokens_generated}")
    print(f"Total throughput: {metrics.total_throughput_tokens_per_s:.2f} tokens/s")
    print(f"TTFT P50/P95: {duration(metrics.p50_ttft_ms)} / {duration(metrics.p95_ttft_ms)}")
    print(f"E2E P50/P95: {duration(metrics.p50_e2e_ms)} / {duration(metrics.p95_e2e_ms)}")
    print(f"KV peak: {metrics.peak_kv_used_blocks}/{config.kv_blocks} blocks ({metrics.peak_kv_utilization:.1%})")
    print(f"Preemptions: {metrics.preemption_count}  Recomputed tokens: {metrics.total_recomputed_tokens}")
    print(
        f"Prefix cache hits: {metrics.prefix_cache_hits}  "
        f"Misses: {metrics.prefix_cache_misses}  "
        f"Reused tokens: {metrics.prefix_reused_tokens}"
    )
    if args.debug:
        print()
        print(format_trace(result))
    if args.trace_json:
        print(f"Trace JSON: {save_trace_json(result, args.trace_json)}")


if __name__ == "__main__":
    main()