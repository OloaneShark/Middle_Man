"""Measure the frozen large-edit fixture and coherent smaller Lab subsets locally."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from middle_man.gateway.codex_benchmark.large_edit_v1 import VISIBLE_TEST_PATH
from middle_man.gateway.codex_benchmark.offline_auto import decide_offline_locator
from middle_man.gateway.codex_benchmark.offline_locator import build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery


CORE = {
    "middle_man/__init__.py", "middle_man/lab/__init__.py",
    *(f"middle_man/lab/{name}.py" for name in ("clock", "config", "request", "work")),
    "tests/test_phase_1_core.py",
}
MEMORY = CORE | {
    "middle_man/lab/memory.py", "tests/test_phase_2_memory.py",
}
SCHEDULING = MEMORY | {
    "middle_man/lab/scheduler.py", "tests/test_phase_3_scheduler.py",
}
ADAPTERS = SCHEDULING | {
    *(f"middle_man/lab/{name}.py" for name in (
        "events", "preemption", "prefix_cache", "runner",
    )),
}
MEMORY_CONTROL = ADAPTERS | {
    "middle_man/lab/memory_control.py", "middle_man/lab/metrics.py",
}
EXECUTION = MEMORY_CONTROL | {
    "middle_man/lab/engine.py",
    "tests/test_phase_5_continuous_batching.py", "tests/test_phase_6_metrics.py",
    VISIBLE_TEST_PATH,
}
WORKFLOWS = EXECUTION | {
    *(f"middle_man/lab/{name}.py" for name in (
        "benchmarks", "comparison", "workloads", "trace", "serialization",
    )),
}
SAMPLE_TIERS = (
    ("core", CORE),
    ("memory", MEMORY),
    ("scheduling", SCHEDULING),
    ("adapters", ADAPTERS),
    ("memory-control", MEMORY_CONTROL),
    ("execution", EXECUTION),
    ("workflows", WORKFLOWS),
)


def measure(root: Path, prompt: str) -> dict[str, object]:
    config = GatewayConfig(root)
    query = ContextQuery(prompt)
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    locator = build_offline_locator(config, query)
    decision = decide_offline_locator(pack, locator)
    indexed = [item for item in RepositoryIndexer(config).index().files if item.is_text]
    candidate = pack.metrics.estimated_raw_candidate_tokens
    selected = pack.metrics.estimated_selected_tokens
    return {
        "indexed_files": len(indexed),
        "indexed_source_tokens": sum((item.size_bytes + 3) // 4 for item in indexed),
        "candidate_paths": len({item.path for item in pack.candidates}),
        "candidate_tokens": candidate,
        "selected_paths": len(locator.selected_paths),
        "selected_tokens": selected,
        "selected_ranges": len(locator.selected_ranges),
        "locator_tokens": locator.estimated_tokens,
        "selected_candidate_ratio": round(selected / candidate, 4) if candidate else 0.0,
        "locator_selected_ratio": round(locator.estimated_tokens / selected, 4) if selected else 0.0,
        "auto_decision": "LOCATOR USED" if decision.use_locator else "BYPASSED",
        "auto_reason": decision.reason,
    }


def main() -> None:
    task = next(item for item in TASKS if item.id == "large-edit-v1")
    with TemporaryDirectory(prefix="middle-man-large-edit-measure-") as temporary:
        base = Path(temporary)
        _, frozen, _ = prepare_pair(task, base / "pair", None)
        for name, paths in SAMPLE_TIERS:
            root = base / name
            for relative in sorted(paths):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(frozen / relative, target)
            print("AUTO_SAMPLE", json.dumps({"sample": name, **measure(root, task.prompt)}, sort_keys=True))
        print("AUTO_SAMPLE", json.dumps({"sample": "full", **measure(frozen, task.prompt)}, sort_keys=True))


if __name__ == "__main__":
    main()
