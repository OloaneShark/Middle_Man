"""Local-only measurements for the offline AUTO gate; no Codex process."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from middle_man.gateway.codex_benchmark.offline_locator import build_offline_locator
from middle_man.gateway.codex_benchmark.offline_auto import decide_offline_locator
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery
from tests.test_phase_22_11 import ACTUAL_QUERY, STRONG


def measure(name: str, root: Path, query: ContextQuery) -> dict[str, int | float | str]:
    config = GatewayConfig(root)
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    locator = build_offline_locator(config, query)
    decision = decide_offline_locator(pack, locator)
    index = RepositoryIndexer(config).index()
    text_files = [item for item in index.files if item.is_text]
    candidate = pack.metrics.estimated_raw_candidate_tokens
    selected = pack.metrics.estimated_selected_tokens
    return {
        "case": name,
        "candidate_tokens": candidate,
        "selected_tokens": selected,
        "locator_tokens": locator.estimated_tokens,
        "candidate_paths": len({item.path for item in pack.candidates}),
        "selected_paths": len(locator.selected_paths),
        "selected_ranges": len(locator.selected_ranges),
        "indexed_text_tokens": sum((item.size_bytes + 3) // 4 for item in text_files),
        "indexed_text_files": len(text_files),
        "selected_candidate_ratio": round(selected / candidate, 4) if candidate else 0.0,
        "locator_selected_ratio": round(locator.estimated_tokens / selected, 4) if selected else 0.0,
        "decision": "USE LOCATOR" if decision.use_locator else "BYPASS MIDDLE_MAN",
        "reason": decision.reason,
    }


def main() -> None:
    with TemporaryDirectory(prefix="middle-man-auto-measure-") as temporary:
        base = Path(temporary)
        task_a = next(task for task in TASKS if task.id == "preemption-v4")
        _, pinned, _ = prepare_pair(task_a, base / "preemption", None)
        queries = {"task-a-exact": ContextQuery(task_a.prompt),
                   "task-a-recorded": ContextQuery(ACTUAL_QUERY, symbols=("WorkKind", "InferenceRequest")),
                   **{f"task-a-{name}": ContextQuery(value) for name, value in STRONG.items()}}
        for name, query in queries.items():
            print("AUTO_DECISION", json.dumps(measure(name, pinned, query), sort_keys=True))
        for task_id in ("oauth-bug", "upload-feature"):
            task = next(item for item in TASKS if item.id == task_id)
            _, root, _ = prepare_pair(task, base / task_id, None)
            print("AUTO_DECISION", json.dumps(measure(task_id, root, ContextQuery(task.prompt)),
                                                  sort_keys=True))
        for case in coverage_cases():
            root = base / case.name
            root.mkdir()
            for relative, source in case.files:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
            print("AUTO_DECISION", json.dumps(measure(case.name, root, ContextQuery(case.query)),
                                                  sort_keys=True))


if __name__ == "__main__":
    main()
