from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from random import Random

from middle_man.lab.request import InferenceRequest


class WorkloadPreset(StrEnum):
    SHORT_CHAT = "short-chat"
    MIXED_CHAT = "mixed-chat"
    LONG_CONTEXT = "long-context"
    BURST_TRAFFIC = "burst-traffic"
    MEMORY_PRESSURE = "memory-pressure"
    PREFIX_HEAVY = "prefix-heavy"
    SCHEDULER_MIXED = "scheduler-mixed"


@dataclass(frozen=True)
class RequestSpec:
    request_id: str
    arrival_time_ms: float
    prompt_tokens: int
    max_output_tokens: int
    prefix_key: str | None = None
    shared_prefix_tokens: int = 0

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must not be empty")
        if self.arrival_time_ms < 0:
            raise ValueError("arrival_time_ms must be non-negative")
        if self.prompt_tokens < 0 or self.max_output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if not 0 <= self.shared_prefix_tokens <= self.prompt_tokens:
            raise ValueError("shared_prefix_tokens must fit within prompt_tokens")

    def create_request(self) -> InferenceRequest:
        return InferenceRequest(
            request_id=self.request_id,
            arrival_time_ms=self.arrival_time_ms,
            prompt_tokens=self.prompt_tokens,
            max_output_tokens=self.max_output_tokens,
            prefix_key=self.prefix_key,
            shared_prefix_tokens=self.shared_prefix_tokens,
        )


@dataclass(frozen=True)
class WorkloadSpec:
    name: str
    description: str
    seed: int
    requests: tuple[RequestSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.requests, tuple) or any(
            not isinstance(request, RequestSpec) for request in self.requests
        ):
            raise TypeError("workload requests must be a tuple of RequestSpec values")
        ids = [request.request_id for request in self.requests]
        if len(ids) != len(set(ids)):
            raise ValueError("workload request IDs must be unique")

    def create_requests(self) -> list[InferenceRequest]:
        return [spec.create_request() for spec in self.requests]


PRESET_DESCRIPTIONS = {
    WorkloadPreset.SHORT_CHAT: "Small interactive requests with frequent arrivals.",
    WorkloadPreset.MIXED_CHAT: "Short and medium prompts with staggered arrivals.",
    WorkloadPreset.LONG_CONTEXT: "Long prompts that require chunked prefill.",
    WorkloadPreset.BURST_TRAFFIC: "Simultaneous arrivals that pressure admission capacity.",
    WorkloadPreset.MEMORY_PRESSURE: "Two requests that exceed constrained combined KV capacity.",
    WorkloadPreset.PREFIX_HEAVY: "Requests sharing a configured prefix.",
    WorkloadPreset.SCHEDULER_MIXED: "Decode and prefill work competing in the same iterations.",
}


def make_workload(preset: WorkloadPreset | str, seed: int = 7) -> WorkloadSpec:
    preset = WorkloadPreset(preset)
    rng = Random(seed)
    specs: list[RequestSpec] = []

    if preset == WorkloadPreset.SHORT_CHAT:
        for index in range(10):
            specs.append(RequestSpec(
                f"short-{index:02d}", index * 1.5, rng.randint(2, 6), rng.randint(1, 3),
            ))
    elif preset == WorkloadPreset.MIXED_CHAT:
        for index in range(8):
            specs.append(RequestSpec(
                f"mixed-{index:02d}", (index // 2) * 2.0,
                rng.choice((3, 8, 12, 20)), rng.randint(1, 5),
            ))
    elif preset == WorkloadPreset.LONG_CONTEXT:
        for index, prompt in enumerate((24, 32, 40)):
            specs.append(RequestSpec(f"long-{index:02d}", float(index), prompt, rng.randint(1, 3)))
    elif preset == WorkloadPreset.BURST_TRAFFIC:
        for index in range(8):
            specs.append(RequestSpec(
                f"burst-{index:02d}", 0.0, rng.randint(2, 6), rng.randint(2, 4),
            ))
    elif preset == WorkloadPreset.MEMORY_PRESSURE:
        specs = [
            RequestSpec("pressure-a", 0.0, 2, 3),
            RequestSpec("pressure-b", 0.0, 2, 3),
        ]
    elif preset == WorkloadPreset.PREFIX_HEAVY:
        for index in range(6):
            specs.append(RequestSpec(
                f"prefix-{index:02d}", 0.0, 4 + 2 * rng.randint(0, 2),
                rng.randint(1, 2), "shared-system", 4,
            ))
    elif preset == WorkloadPreset.SCHEDULER_MIXED:
        specs = [
            RequestSpec("decode-a", 0.0, 2, 8),
            RequestSpec("prefill-a", 0.0, 20, 1),
            RequestSpec("decode-b", 1.0, 2, 5),
            RequestSpec("prefill-b", 2.0, 16, 1),
        ]

    return WorkloadSpec(preset.value, PRESET_DESCRIPTIONS[preset], seed, tuple(specs))
