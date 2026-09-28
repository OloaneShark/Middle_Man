from __future__ import annotations

import argparse

from middle_man.lab.reporting import format_benchmark_suite
from middle_man.lab.serialization import save_csv, save_json
from middle_man.lab.suites import available_benchmarks, build_suite


def run_benchmark(args: argparse.Namespace) -> None:
    if args.list or args.name is None:
        print("AVAILABLE MIDDLE_MAN BENCHMARKS")
        for name, description in available_benchmarks():
            print(f"{name:22} {description}")
        return

    result = build_suite(args.name, seed=args.seed).run()
    print(format_benchmark_suite(result, verbose=args.verbose))
    if args.json:
        print(f"JSON: {save_json(result, args.output_dir)}")
    if args.csv:
        print(f"CSV: {save_csv(result, args.output_dir)}")
    if args.plot:
        from middle_man.lab.visualization import VisualizationUnavailable, render_suite_plots
        try:
            paths = render_suite_plots(result, args.output_dir)
        except VisualizationUnavailable as exc:
            raise SystemExit(str(exc)) from exc
        for path in paths:
            print(f"Plot: {path}")
