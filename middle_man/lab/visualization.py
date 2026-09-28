from __future__ import annotations

from pathlib import Path

from middle_man.lab.benchmarks import BenchmarkResult, BenchmarkSuiteResult
from middle_man.lab.events import EventType
from middle_man.lab.serialization import safe_name


class VisualizationUnavailable(RuntimeError):
    pass


def _pyplot():
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise VisualizationUnavailable(
            "matplotlib is optional; install Middle_Man with the viz extra"
        ) from exc
    return plt


def _save(figure, path: Path, plt) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def plot_request_timeline(
    case: BenchmarkResult,
    output_dir: str | Path = "benchmark_results",
) -> Path:
    if case.metrics is None:
        raise ValueError("cannot plot a failed case")
    plt = _pyplot()
    figure, ax = plt.subplots(figsize=(10, max(3.5, len(case.metrics.requests) * 0.45)))
    by_id = {request.request_id: index for index, request in enumerate(case.metrics.requests)}
    arrivals = {request.request_id: request.arrival_time_ms for request in case.metrics.requests}
    active_start: dict[str, float] = {}
    waiting_start = dict(arrivals)
    marker_style = {
        EventType.PREFILL_EXECUTED: ("o", "#007f86", "prefill end"),
        EventType.DECODE_EXECUTED: ("s", "#bd541b", "decode end"),
        EventType.RECOMPUTE_EXECUTED: ("^", "#9c3b78", "recompute end"),
        EventType.REQUEST_PREEMPTED: ("x", "#b51e2c", "preempted"),
        EventType.REQUEST_COMPLETED: ("D", "#314b52", "completed"),
    }
    seen_labels: set[str] = set()

    for event in case.events:
        if event.request_id not in by_id:
            continue
        row = by_id[event.request_id]
        if event.kind == EventType.REQUEST_ADMITTED:
            start = waiting_start.pop(event.request_id, event.time_ms)
            label = "waiting" if "waiting" not in seen_labels else None
            ax.plot([start, event.time_ms], [row, row], linestyle=":", color="#8a969a",
                    linewidth=1.5, label=label)
            seen_labels.add("waiting")
            active_start[event.request_id] = event.time_ms
        elif event.kind in {EventType.REQUEST_PREEMPTED, EventType.REQUEST_COMPLETED}:
            start = active_start.pop(event.request_id, None)
            if start is not None:
                label = "active" if "active" not in seen_labels else None
                ax.plot([start, event.time_ms], [row, row], color="#314b52",
                        linewidth=2, label=label)
                seen_labels.add("active")
            if event.kind == EventType.REQUEST_PREEMPTED:
                waiting_start[event.request_id] = event.time_ms
        if event.kind in marker_style:
            marker, color, label = marker_style[event.kind]
            ax.scatter(event.time_ms, row, marker=marker, color=color, s=24,
                       label=label if label not in seen_labels else None, zorder=3)
            seen_labels.add(label)

    ax.set_yticks(range(len(by_id)), list(by_id))
    ax.invert_yaxis()
    ax.set_xlabel("Simulated time (ms)")
    ax.set_title(f"SIMULATED request timeline: {case.case_name}")
    ax.grid(axis="x", alpha=0.25)
    if seen_labels:
        ax.legend(loc="upper right", fontsize="small")
    destination = Path(output_dir) / f"{safe_name(case.workload_name)}-{safe_name(case.case_name)}-timeline.png"
    return _save(figure, destination, plt)


def plot_kv_utilization(
    case: BenchmarkResult,
    output_dir: str | Path = "benchmark_results",
) -> Path:
    if case.metrics is None:
        raise ValueError("cannot plot a failed case")
    plt = _pyplot()
    samples = case.metrics.kv_samples
    figure, ax = plt.subplots(figsize=(9, 4))
    ax.step([sample.time_ms for sample in samples], [sample.used_blocks for sample in samples],
            where="post", label="used blocks", color="#007f86")
    ax.step([sample.time_ms for sample in samples], [sample.cached_blocks for sample in samples],
            where="post", label="cached blocks", color="#bd541b")
    ax.set_ylim(bottom=0, top=case.config.kv_blocks * 1.05)
    ax.set_xlabel("Simulated time (ms)")
    ax.set_ylabel("Physical KV blocks")
    ax.set_title(f"SIMULATED KV utilization: {case.case_name}")
    ax.grid(alpha=0.25)
    ax.legend()
    destination = Path(output_dir) / f"{safe_name(case.workload_name)}-{safe_name(case.case_name)}-kv.png"
    return _save(figure, destination, plt)


def plot_ttft_distribution(
    case: BenchmarkResult,
    output_dir: str | Path = "benchmark_results",
) -> Path:
    if case.metrics is None:
        raise ValueError("cannot plot a failed case")
    plt = _pyplot()
    values = [request.ttft_ms for request in case.metrics.requests if request.ttft_ms is not None]
    figure, ax = plt.subplots(figsize=(8, 4))
    if values:
        ax.hist(values, bins=min(10, max(1, len(values))), color="#007f86", edgecolor="white")
    else:
        ax.text(0.5, 0.5, "No output-token timestamps", ha="center", va="center",
                transform=ax.transAxes)
    ax.set_xlabel("Time to first output token (simulated ms)")
    ax.set_ylabel("Requests")
    ax.set_title(f"SIMULATED TTFT distribution: {case.case_name}")
    destination = Path(output_dir) / f"{safe_name(case.workload_name)}-{safe_name(case.case_name)}-ttft.png"
    return _save(figure, destination, plt)


def plot_throughput_comparison(
    suite: BenchmarkSuiteResult,
    output_dir: str | Path = "benchmark_results",
) -> Path:
    successful = [case for case in suite.cases if case.metrics is not None]
    if not successful:
        raise ValueError("no successful cases to compare")
    plt = _pyplot()
    figure, ax = plt.subplots(figsize=(max(7, len(successful) * 2.2), 4))
    ax.bar(
        [case.case_name for case in successful],
        [case.metrics.aggregate.total_throughput_tokens_per_s for case in successful],
        color="#007f86",
    )
    ax.set_ylabel("Simulated total tokens/s")
    ax.set_title(f"SIMULATED throughput: {suite.name}")
    ax.tick_params(axis="x", rotation=20)
    destination = Path(output_dir) / f"{safe_name(suite.name)}-throughput.png"
    return _save(figure, destination, plt)


def render_suite_plots(
    suite: BenchmarkSuiteResult,
    output_dir: str | Path = "benchmark_results",
) -> tuple[Path, ...]:
    first = next((case for case in suite.cases if case.metrics is not None), None)
    if first is None:
        return ()
    paths = [
        plot_request_timeline(first, output_dir),
        plot_kv_utilization(first, output_dir),
        plot_ttft_distribution(first, output_dir),
    ]
    if sum(case.metrics is not None for case in suite.cases) > 1:
        paths.append(plot_throughput_comparison(suite, output_dir))
    return tuple(paths)
