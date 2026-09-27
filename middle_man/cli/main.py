from __future__ import annotations

import argparse

from middle_man.lab.config import LabConfig, SchedulerKind
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.request import InferenceRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="middle-man", description="Middle_Man simulation tools")
    subparsers = parser.add_subparsers(dest="command")

    simulate = subparsers.add_parser("simulate", help="run a deterministic Phase 1-4 serving simulation")
    simulate.add_argument("--requests", type=int, default=8)
    simulate.add_argument("--prompt-tokens", type=int, default=32)
    simulate.add_argument("--output-tokens", type=int, default=8)
    simulate.add_argument("--token-budget", type=int, default=64)
    simulate.add_argument("--kv-blocks", type=int, default=128)
    simulate.add_argument("--tokens-per-block", type=int, default=16)
    simulate.add_argument("--scheduler", choices=[item.value for item in SchedulerKind], default=SchedulerKind.DECODE_PRIORITY.value)

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
    parser.error(f"unknown command: {args.command}")


def run_simulate(args: argparse.Namespace) -> None:
    config = LabConfig(
        token_budget=args.token_budget,
        kv_blocks=args.kv_blocks,
        tokens_per_block=args.tokens_per_block,
        scheduler=SchedulerKind(args.scheduler),
    )
    requests = [
        InferenceRequest(
            request_id=f"req-{index + 1:03d}",
            arrival_time_ms=0.0,
            prompt_tokens=args.prompt_tokens,
            max_output_tokens=args.output_tokens,
        )
        for index in range(args.requests)
    ]
    result = SimulationEngine(config).run(requests)
    print("MIDDLE_MAN SIMULATION")
    print(f"Requests: {len(result.requests)}")
    print(f"Iterations: {result.iterations}")
    print(f"Elapsed: {result.elapsed_ms:.2f} ms")
    print(f"Prompt tokens processed: {result.prompt_tokens_processed}")
    print(f"Output tokens generated: {result.output_tokens_generated}")


if __name__ == "__main__":
    main()
