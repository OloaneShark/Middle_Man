"""Local-only Task A payload and SDK tool-surface measurement."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from middle_man.gateway.codex_benchmark.overlap import measure_delivery
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.gateway import MCPGateway
from middle_man.mcp.surface import measure_tool_surface


def main() -> None:
    task = next(item for item in TASKS if item.id == "preemption")
    estimator = HeuristicTokenEstimator()
    with tempfile.TemporaryDirectory(prefix="middle-man-task-a-local-") as folder:
        _, target, fingerprint = prepare_pair(
            task, Path(folder) / "pair", "For scoped tasks, call middleman_context directly.\n"
        )
        config = GatewayConfig(target)
        full_surface = asyncio.run(measure_tool_surface(config, "full"))
        core_surface = asyncio.run(measure_tool_surface(config, "codex-core"))
        old = MCPGateway(config)
        old_results = {}
        handoff_error = None
        try:
            old_results["session_handoff"] = old.session_handoff()
        except Exception as exc:
            handoff_error = type(exc).__name__
        old_results["project_state"] = old.project_state()
        old_results["find_context"] = old.find_context(task.prompt)
        full = old.context_pack(task.prompt, mode="balanced", max_context_tokens=6000)
        old_results["context_pack"] = full
        core_gateway = MCPGateway(config)
        core = core_gateway.context(task.prompt, mode="balanced", max_context_tokens=6000)
        replay = core_gateway.context(task.prompt, mode="balanced", max_context_tokens=6000)

        def size(value: object) -> int:
            return estimator.estimate(json.dumps(value, ensure_ascii=False))

        old_sizes = {name: size(value) for name, value in old_results.items()}
        source_tokens = sum(estimator.estimate(item["text"]) for item in full["excerpts"])
        core_size = size(core)
        full_size = old_sizes["context_pack"]
        entries = [json.loads(line) for line in
                   (config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8").splitlines()]
        source_identity = lambda response: [
            (item["path"], item["start_line"], item["end_line"], item["text"])
            for item in response["excerpts"]
        ]
        print(json.dumps({
            "snapshot_fingerprint": fingerprint,
            "tool_surfaces": {"full": asdict(full_surface), "codex-core": asdict(core_surface)},
            "pack_fingerprint_equal": full["fingerprint"] == core["fingerprint"],
            "source_equal": source_identity(full) == source_identity(core),
            "warnings_equal": full["warnings"] == core["warnings"],
            "selected_tokens_equal": full["metrics"]["estimated_selected_tokens"] == core["metrics"]["selected_tokens"],
            "selected_source_tokens": source_tokens,
            "candidate_tokens": full["metrics"]["estimated_raw_candidate_tokens"],
            "full_result_tokens": full_size, "core_result_tokens": core_size,
            "full_metadata_overhead_tokens": full_size - source_tokens,
            "core_metadata_overhead_tokens": core_size - source_tokens,
            "old_route_successful_result_tokens": sum(old_sizes.values()),
            "old_route_individual_result_tokens": old_sizes,
            "old_route_handoff_error": handoff_error,
            "new_route_result_tokens": core_size,
            "replay_excerpts": len(replay["excerpts"]),
            "replay_result_tokens": size(replay),
            "overlap_available": measure_delivery(entries).overlap_available,
            "usage_calls": [entry["tool"] for entry in entries],
        }, indent=2))


if __name__ == "__main__":
    main()
