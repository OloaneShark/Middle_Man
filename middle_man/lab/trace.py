from __future__ import annotations

from itertools import groupby

from middle_man.lab.engine import EngineResult
from middle_man.lab.events import EventType, SimulationEvent


WORK_EVENTS = {
    EventType.PREFILL_EXECUTED,
    EventType.DECODE_EXECUTED,
    EventType.RECOMPUTE_EXECUTED,
}


def _describe(event: SimulationEvent, prompt_progress: str | None = None) -> str:
    name = event.kind.value.replace("_", " ")
    detail = f": {event.tokens} {'token' if event.tokens == 1 else 'tokens'}" if event.tokens else ""
    if prompt_progress:
        detail += f", prompt {prompt_progress}"
    if event.kind in {EventType.KV_ALLOCATED, EventType.KV_RELEASED, EventType.REQUEST_PREEMPTED}:
        detail += f", {event.blocks} physical {'block' if event.blocks == 1 else 'blocks'}"
    if event.related_request_id:
        detail += f", triggered by {event.related_request_id}"
    return f"  {event.request_id}: {name}{detail}"


def format_trace(result: EngineResult) -> str:
    lines = ["MIDDLE_MAN SIMULATION TRACE", "SIMULATED TIME"]
    samples_by_time = {}
    for sample in result.metrics.kv_samples:
        samples_by_time[sample.time_ms] = sample
    prompt_limit = {request.request_id: request.prompt_tokens for request in result.requests}
    prompt_progress = {request.request_id: 0 for request in result.requests}

    for time_ms, group in groupby(result.events, key=lambda event: event.time_ms):
        events = tuple(group)
        lines.extend(("", f"TIME {time_ms:.3f} ms"))
        work: list[str] = []
        changes: list[str] = []
        for event in events:
            if event.kind == EventType.PREFIX_CACHE_HIT:
                prompt_progress[event.request_id] = max(
                    prompt_progress[event.request_id], event.tokens
                )
            if event.kind == EventType.PREFILL_EXECUTED:
                prompt_progress[event.request_id] += event.tokens
                progress = f"{prompt_progress[event.request_id]}/{prompt_limit[event.request_id]}"
            else:
                progress = None
            rendered = _describe(event, progress)
            if event.kind in WORK_EVENTS:
                work.append(rendered)
            else:
                changes.append(rendered)
        if work:
            lines.append("WORK")
            lines.extend(work)
        if changes:
            lines.append("EVENTS")
            lines.extend(changes)
        sample = samples_by_time.get(time_ms)
        if sample:
            lines.append(
                f"MEMORY {sample.used_blocks}/{sample.total_blocks} blocks, "
                f"{sample.cached_blocks} cached"
            )
    lines.extend(("", f"Scheduler iterations: {result.iterations}"))
    return "\n".join(lines)