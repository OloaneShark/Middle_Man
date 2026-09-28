from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

from middle_man import __version__
from middle_man.lab.benchmarks import BenchmarkSuiteResult
from middle_man.lab.engine import EngineResult
from middle_man.lab.metrics import AggregateMetrics


def safe_name(name: str) -> str:
    result = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if not result:
        raise ValueError("name has no filename-safe characters")
    return result


def _metadata(result: BenchmarkSuiteResult, timestamp: datetime | None) -> dict[str, object]:
    now = timestamp if timestamp is not None else datetime.now(timezone.utc)
    return {
        "middle_man_version": __version__,
        "timestamp_utc": now.astimezone(timezone.utc).isoformat(),
        "simulated": True,
        "measurement_source": "Middle_Man deterministic simulation cost model",
        "benchmark": result.name,
    }


def save_json(
    result: BenchmarkSuiteResult,
    output_dir: str | Path = "benchmark_results",
    *,
    timestamp: datetime | None = None,
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{safe_name(result.name)}.json"
    payload = {"metadata": _metadata(result, timestamp), "suite": asdict(result)}
    destination.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return destination


def save_csv(
    result: BenchmarkSuiteResult,
    output_dir: str | Path = "benchmark_results",
    *,
    timestamp: datetime | None = None,
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{safe_name(result.name)}.csv"
    metadata = _metadata(result, timestamp)
    metric_names = [field.name for field in fields(AggregateMetrics)]
    columns = [
        "middle_man_version", "timestamp_utc", "simulated", "measurement_source",
        "benchmark", "case_name", "workload", "seed", "request_count",
        "labels", "scheduler", "token_budget", "max_active_sequences",
        "kv_blocks", "tokens_per_block", "preemption_enabled", "prefix_cache_enabled",
        "random_seed", "debug", "runner_costs", "failure_type", "failure_message", "final_kv_used_blocks",
        *metric_names,
    ]
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for case in result.cases:
            row = {
                **metadata,
                "case_name": case.case_name,
                "workload": case.workload_name,
                "seed": case.seed,
                "request_count": case.request_count,
                "labels": ";".join(case.labels),
                "scheduler": case.config.scheduler.value,
                "token_budget": case.config.token_budget,
                "max_active_sequences": case.config.max_active_sequences,
                "kv_blocks": case.config.kv_blocks,
                "tokens_per_block": case.config.tokens_per_block,
                "preemption_enabled": case.config.preemption_enabled,
                "prefix_cache_enabled": case.config.prefix_cache_enabled,
                "random_seed": case.config.random_seed,
                "debug": case.config.debug,
                "runner_costs": json.dumps(asdict(case.config.runner_costs)),
                "failure_type": case.failure.exception_type if case.failure else "",
                "failure_message": case.failure.message if case.failure else "",
                "final_kv_used_blocks": case.final_kv_used_blocks,
            }
            if case.metrics:
                row.update(asdict(case.metrics.aggregate))
            writer.writerow(row)
    return destination


def save_trace_json(result: EngineResult, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "middle_man_version": __version__,
        "simulated": True,
        "measurement_source": "Middle_Man deterministic simulation cost model",
        "iterations": result.iterations,
        "elapsed_ms": result.elapsed_ms,
        "events": [asdict(event) for event in result.events],
    }
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path