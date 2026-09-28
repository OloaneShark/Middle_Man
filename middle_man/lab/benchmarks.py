from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from middle_man.lab.clock import VirtualClock
from middle_man.lab.comparison import ComparisonResult, compare_aggregates
from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine, SimulationError
from middle_man.lab.events import SimulationEvent
from middle_man.lab.memory import AllocationError, KVBlockManager
from middle_man.lab.metrics import MetricsResult
from middle_man.lab.workloads import WorkloadSpec


@dataclass(frozen=True)
class BenchmarkFailure:
    exception_type: str
    message: str


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    description: str
    workload: WorkloadSpec
    config: LabConfig
    labels: tuple[str, ...] = ()

    def run(self) -> BenchmarkResult:
        requests = self.workload.create_requests()
        memory = KVBlockManager(self.config.kv_blocks, self.config.tokens_per_block)
        engine = SimulationEngine(self.config, clock=VirtualClock(), memory=memory)
        try:
            result = engine.run(requests)
        except (AllocationError, SimulationError) as exc:
            return BenchmarkResult(
                case_name=self.name,
                description=self.description,
                workload_name=self.workload.name,
                seed=self.workload.seed,
                config=self.config,
                labels=self.labels,
                request_count=len(requests),
                metrics=None,
                events=(),
                event_counts=(),
                failure=BenchmarkFailure(type(exc).__name__, str(exc)),
                final_kv_used_blocks=memory.used_block_count,
            )

        counts = Counter(event.kind.value for event in result.events)
        return BenchmarkResult(
            case_name=self.name,
            description=self.description,
            workload_name=self.workload.name,
            seed=self.workload.seed,
            config=self.config,
            labels=self.labels,
            request_count=len(requests),
            metrics=result.metrics,
            events=result.events,
            event_counts=tuple(sorted(counts.items())),
            failure=None,
            final_kv_used_blocks=memory.used_block_count,
        )


@dataclass(frozen=True)
class BenchmarkResult:
    case_name: str
    description: str
    workload_name: str
    seed: int
    config: LabConfig
    labels: tuple[str, ...]
    request_count: int
    metrics: MetricsResult | None
    events: tuple[SimulationEvent, ...]
    event_counts: tuple[tuple[str, int], ...]
    failure: BenchmarkFailure | None
    final_kv_used_blocks: int


@dataclass(frozen=True)
class BenchmarkSuiteResult:
    name: str
    description: str
    cases: tuple[BenchmarkResult, ...]
    comparisons: tuple[ComparisonResult, ...]


@dataclass(frozen=True)
class BenchmarkSuite:
    name: str
    description: str
    cases: tuple[BenchmarkCase, ...]

    def run(self) -> BenchmarkSuiteResult:
        results = tuple(case.run() for case in self.cases)
        comparisons = []
        if results and results[0].metrics is not None:
            baseline = results[0]
            for variant in results[1:]:
                if variant.metrics is not None:
                    comparisons.append(compare_aggregates(
                        baseline.case_name,
                        baseline.metrics.aggregate,
                        variant.case_name,
                        variant.metrics.aggregate,
                    ))
        return BenchmarkSuiteResult(self.name, self.description, results, tuple(comparisons))
