from __future__ import annotations

from dataclasses import replace

from middle_man.lab.benchmarks import BenchmarkCase, BenchmarkSuite
from middle_man.lab.config import LabConfig, SchedulerKind
from middle_man.lab.workloads import WorkloadPreset, make_workload


SUITE_DESCRIPTIONS = {
    "mixed": "Run a mixed chat workload.",
    "short-chat": "Run a small interactive workload.",
    "scheduler-comparison": "Compare decode-priority and balanced scheduling.",
    "prefix-cache": "Compare prefix caching disabled and enabled.",
    "memory-pressure": "Compare comfortable and constrained KV memory.",
    "token-budget": "Compare four scheduler token budgets.",
    "active-sequences": "Compare active-sequence admission limits.",
    "chunked-prefill": "Compare long-prompt progress at two token budgets.",
}


def available_benchmarks() -> tuple[tuple[str, str], ...]:
    return tuple(SUITE_DESCRIPTIONS.items())


def build_suite(name: str, seed: int = 7) -> BenchmarkSuite:
    if name not in SUITE_DESCRIPTIONS:
        raise ValueError(f"unknown benchmark {name!r}")

    if name == "scheduler-comparison":
        workload = make_workload(WorkloadPreset.SCHEDULER_MIXED, seed)
        base = LabConfig(
            token_budget=4, max_active_sequences=4,
            kv_blocks=32, tokens_per_block=4, random_seed=seed,
        )
        variants = (
            ("decode-priority", base),
            ("balanced", replace(base, scheduler=SchedulerKind.BALANCED)),
        )
    elif name == "prefix-cache":
        workload = make_workload(WorkloadPreset.PREFIX_HEAVY, seed)
        base = LabConfig(
            token_budget=4, max_active_sequences=4,
            kv_blocks=32, tokens_per_block=2, random_seed=seed,
        )
        variants = (
            ("cache-off", base),
            ("cache-on", replace(base, prefix_cache_enabled=True)),
        )
    elif name == "memory-pressure":
        workload = make_workload(WorkloadPreset.MEMORY_PRESSURE, seed)
        base = LabConfig(
            token_budget=2, max_active_sequences=2,
            kv_blocks=8, tokens_per_block=2, random_seed=seed,
        )
        variants = (
            ("comfortable", base),
            ("constrained-preemption", replace(base, kv_blocks=3, preemption_enabled=True)),
            ("constrained-no-preemption", replace(base, kv_blocks=3)),
        )
    elif name == "token-budget":
        workload = make_workload(WorkloadPreset.LONG_CONTEXT, seed)
        base = LabConfig(
            token_budget=4, max_active_sequences=3,
            kv_blocks=64, tokens_per_block=4, random_seed=seed,
        )
        variants = tuple((f"budget-{budget}", replace(base, token_budget=budget))
                         for budget in (4, 8, 16, 32))
    elif name == "active-sequences":
        workload = make_workload(WorkloadPreset.BURST_TRAFFIC, seed)
        base = LabConfig(
            token_budget=8, max_active_sequences=1,
            kv_blocks=64, tokens_per_block=2, random_seed=seed,
        )
        variants = tuple((f"active-{count}", replace(base, max_active_sequences=count))
                         for count in (1, 2, 4))
    elif name == "chunked-prefill":
        workload = make_workload(WorkloadPreset.LONG_CONTEXT, seed)
        base = LabConfig(
            token_budget=4, max_active_sequences=3,
            kv_blocks=64, tokens_per_block=4, random_seed=seed,
        )
        variants = (
            ("budget-4", base),
            ("budget-16", replace(base, token_budget=16)),
        )
    else:
        preset = WorkloadPreset.MIXED_CHAT if name == "mixed" else WorkloadPreset.SHORT_CHAT
        workload = make_workload(preset, seed)
        variants = (("default", LabConfig(
            token_budget=8, max_active_sequences=4,
            kv_blocks=64, tokens_per_block=4, random_seed=seed,
        )),)

    description = SUITE_DESCRIPTIONS[name]
    cases = tuple(
        BenchmarkCase(
            name=case_name,
            description=f"{description} Configuration: {case_name}.",
            workload=workload,
            config=config,
            labels=(name, case_name),
        )
        for case_name, config in variants
    )
    return BenchmarkSuite(name, description, cases)
