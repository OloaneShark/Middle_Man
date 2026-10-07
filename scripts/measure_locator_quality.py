"""Compare two locked locator outcomes locally, without invoking Codex."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

from middle_man.gateway.codex_benchmark.offline_locator import build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.codex_runner.infrastructure import capture_repository_state
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.locator_diagnostics import diagnose_locator
from middle_man.gateway.relevance import ContextQuery


ROOT = Path(__file__).resolve().parents[1]
LOSS_HEAD = "bdd471f19bc4ffb9a0548cfcfdf54f4abdce6731"
LOSS_TASK = (
    "Trace the complete read-only production Codex path in Middle_Man from the user's CLI command "
    "through local context selection, offline AUTO routing, isolated Codex execution, event parsing, "
    "audit construction, and final repository-integrity enforcement. Explain what Middle_Man computes "
    "before Codex starts, what Codex reports afterward, when the original task bytes remain unchanged "
    "versus when a source-free locator is appended, and which failures cause the production result to "
    "be rejected."
)
LOSS_TASK_SHA256 = "55b50254c5eaadb5ef239ce14f0b25b3f3beee78eed7c596eb0062603f38a7eb"
LOSS_SELECTED_PATHS = (
    "tests/test_phase_23_claude.py",
    "tests/test_codex_live_runner.py",
    "tests/test_codex_runner.py",
    "tests/test_phase_22_v4.py",
    "tests/test_phase_23_2_runtime.py",
    "middle_man/mcp/gateway.py",
    "middle_man/gateway/source.py",
    "middle_man/gateway/git_diff.py",
    "middle_man/gateway/codex_benchmark/runner.py",
    "middle_man/gateway/codex_benchmark/offline_auto.py",
    "middle_man/gateway/claude_benchmark/runtime_probe.py",
    "middle_man/cli/codex_run.py",
    "middle_man/gateway/codex_benchmark/offline_locator.py",
)
LOSS_LOCATOR_SHA256 = "6be069352e2f897b9eea765fbc15516c6e4029ecd8651dc14191041e5d72d379"
TASK_A_ARTIFACT = ROOT / ".middle_man_cache" / "codex_benchmarks" / "20261001T161512Z-015fde5e" / "result.json"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          timeout=30, check=True).stdout.strip()


def _measure(root: Path, task: str) -> dict[str, object]:
    before = capture_repository_state(root)
    config = GatewayConfig(root, cache_writes_enabled=False)
    query = ContextQuery(task)
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    locator = build_offline_locator(config, query)
    index = RepositoryIndexer(config).index()
    if pack.fingerprint != locator.pack_fingerprint or pack.selected_files != locator.selected_paths:
        raise RuntimeError("pack and locator differ")
    if capture_repository_state(root) != before:
        raise RuntimeError("local diagnostic changed its snapshot")
    return {
        "source_head": before.head,
        "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "locator_sha256": locator.sha256,
        "pack_fingerprint": pack.fingerprint,
        "index_cache_hits": index.stats.cache_hits,
        "index_cache_misses": index.stats.cache_misses,
        "quality": diagnose_locator(pack, index, locator_tokens=locator.estimated_tokens),
    }


def main() -> None:
    if hashlib.sha256(LOSS_TASK.encode("utf-8")).hexdigest() != LOSS_TASK_SHA256:
        raise RuntimeError("production-loss task differs from the frozen prompt")
    if _git(ROOT, "rev-parse", "HEAD") != LOSS_HEAD:
        raise RuntimeError("run this historical comparison from the pinned production commit")
    with TemporaryDirectory(prefix="middle-man-locator-quality-") as temporary:
        base = Path(temporary).resolve()
        if not base.is_relative_to(Path(gettempdir()).resolve()):
            raise RuntimeError("temporary snapshots escaped the system temp directory")
        production = base / "production"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks", "-q",
                        str(ROOT), str(production)],
                       capture_output=True, text=True, timeout=120, check=True)
        if _git(production, "rev-parse", "HEAD") != LOSS_HEAD or _git(production, "status", "--porcelain=v1"):
            raise RuntimeError("production snapshot differs from pinned clean HEAD")
        task_a = next(task for task in TASKS if task.id == "preemption-v4")
        _, task_a_root, fingerprint = prepare_pair(task_a, base / "task_a", None)
        task_a_report = _measure(task_a_root, task_a.prompt)
        loss_report = _measure(production, LOSS_TASK)
        loss_report["historical_selected_paths_match"] = (
            tuple(row["path"] for row in loss_report["quality"]["selected_paths"]) == LOSS_SELECTED_PATHS)
        loss_report["historical_locator_hash_match"] = loss_report["locator_sha256"] == LOSS_LOCATOR_SHA256
        if not loss_report["historical_selected_paths_match"] or not loss_report["historical_locator_hash_match"]:
            raise RuntimeError("production-loss locator did not reproduce from pinned LF snapshot")
        task_a_report["source_tree_fingerprint"] = fingerprint
        if not TASK_A_ARTIFACT.exists():
            raise RuntimeError("frozen Task A result artifact is unavailable")
        artifact = json.loads(TASK_A_ARTIFACT.read_text(encoding="utf-8"))
        pair = artifact["pairs"][0]
        audit = pair["optimized"]["offline_locator_audit"]
        task_a_report["historical_source_fingerprint_match"] = (
            fingerprint == pair["source_tree_fingerprint"])
        task_a_report["historical_selected_paths_match"] = (
            tuple(row["path"] for row in task_a_report["quality"]["selected_paths"])
            == tuple(audit["selected_paths"]))
        task_a_report["historical_locator_hash_match"] = (
            task_a_report["locator_sha256"] == audit["locator_sha256"])
        if not all(task_a_report[key] for key in (
                "historical_source_fingerprint_match", "historical_selected_paths_match",
                "historical_locator_hash_match")):
            raise RuntimeError("Task A locator did not reproduce from frozen source")
        print(json.dumps({"task_a_win": task_a_report, "production_loss": loss_report},
                         sort_keys=True))


if __name__ == "__main__":
    main()
