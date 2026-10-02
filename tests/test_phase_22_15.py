"""Local-only large-edit benchmark proof; external Codex is never invoked."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark import runner
from middle_man.gateway.codex_benchmark.large_edit_v1 import (
    ACCEPTANCE_TEST, FIXTURE_PATHS, PROMPT, VISIBLE_TEST_PATH,
)
from middle_man.gateway.codex_benchmark.large_edit_v1_reference import apply_reference_solution
from middle_man.gateway.codex_benchmark.offline_auto import (
    MIN_CANDIDATE_SOURCE_TOKENS, decide_offline_locator,
)
from middle_man.gateway.codex_benchmark.offline_locator import (
    LOCATOR_HEADING, append_offline_locator, build_offline_locator,
)
from middle_man.gateway.codex_benchmark.tasks import (
    TASK_A_SOURCE_COMMIT, TASKS, add_acceptance_tests, prepare_pair, source_fingerprint,
)
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery
from scripts.measure_large_edit_v1 import SAMPLE_TIERS, measure


TASK = next(task for task in TASKS if task.id == "large-edit-v1")
REQUIRED_PRODUCTION = {
    "middle_man/lab/engine.py", "middle_man/lab/events.py", "middle_man/lab/metrics.py",
}
REQUIRED_SYMBOLS = (
    "SimulationEngine.run", "EventType", "MetricsCollector.build",
    "AggregateMetrics", "InferenceRequest.cancel", "ExistingSimulationTests",
)


def _test_process(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", *args], cwd=root, capture_output=True, text=True)


@pytest.fixture(scope="module")
def frozen(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    return prepare_pair(TASK, tmp_path_factory.mktemp("large-edit-v1") / "pair", None)


def test_frozen_fixture_is_clean_deterministic_and_initially_green(
    frozen: tuple[Path, Path, str], tmp_path: Path,
) -> None:
    baseline, optimized, fingerprint = frozen
    other_baseline, other_optimized, other_fingerprint = prepare_pair(TASK, tmp_path / "pair", None)
    assert TASK.source_ref == TASK_A_SOURCE_COMMIT
    assert fingerprint == other_fingerprint
    assert all(source_fingerprint(root) == fingerprint for root in (
        baseline, optimized, other_baseline, other_optimized))
    for root in (baseline, optimized):
        files = {path.relative_to(root).as_posix() for path in root.rglob("*.py")}
        assert files == set(FIXTURE_PATHS) | {VISIBLE_TEST_PATH}
        assert len(files) == 30
        assert not (root / "AGENTS.md").exists()
        assert not (root / "tests/test_middleman_benchmark_acceptance.py").exists()
        assert not subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"]).strip()
    assert _test_process(baseline, "pytest", "-q", "tests").returncode == 0
    assert _test_process(optimized, "unittest", "discover", "-s", "tests").returncode == 0
    assert "test_middleman_benchmark_acceptance" not in PROMPT
    assert "middle_man/lab/" not in PROMPT and "tests/" not in PROMPT
    assert "cancel_request_ids" in PROMPT and "unknown" in PROMPT
    assert "unique" not in PROMPT or "duplicates count once" in PROMPT
    assert "cancelled_requests" not in PROMPT
    assert "test_unknown_id_is_rejected_before_mutation" in ACCEPTANCE_TEST


def test_reference_solution_satisfies_hidden_contract_and_harness(tmp_path: Path) -> None:
    baseline, solved, _ = prepare_pair(TASK, tmp_path / "pair", None)
    add_acceptance_tests(TASK, baseline)
    initial = _test_process(baseline, "unittest", "discover", "-s", "tests", "-v")
    assert initial.returncode != 0
    assert "unexpected keyword argument" in initial.stderr
    apply_reference_solution(solved)
    before = ()
    after = tuple(subprocess.check_output(
        ["git", "-C", str(solved), "status", "--porcelain=v1", "--untracked-files=all"],
        text=True).splitlines())
    changed = runner._changed_paths(after)
    assert REQUIRED_PRODUCTION <= set(changed)
    assert VISIBLE_TEST_PATH in changed
    passed, notes, test_exit, _ = runner._evaluate(
        TASK, solved, "", changed, before, after, 0, 1)
    assert passed and not notes and test_exit == 0
    full = _test_process(solved, "pytest", "-q", "tests")
    assert full.returncode == 0, full.stdout + full.stderr


def test_plausible_wrong_solution_fails_hidden_acceptance(tmp_path: Path) -> None:
    _, wrong, _ = prepare_pair(TASK, tmp_path / "pair", None)
    path = wrong / "middle_man/lab/engine.py"
    source = path.read_text(encoding="utf-8")
    old = "    def run(self, requests: list[InferenceRequest]) -> EngineResult:\n"
    assert source.count(old) == 1
    source = source.replace(
        old,
        "    def run(self, requests: list[InferenceRequest], cancel_request_ids=()) -> EngineResult:\n"
        "        cancel_ids = set(cancel_request_ids)\n"
        "        for request in requests:\n"
        "            if request.request_id in cancel_ids:\n"
        "                request.cancel()\n",
    )
    old_pending = "        pending = sorted(requests, key=lambda request: request.arrival_time_ms)\n"
    assert source.count(old_pending) == 1
    source = source.replace(
        old_pending,
        "        pending = sorted((request for request in requests if request.request_id not in cancel_ids),\n"
        "                         key=lambda request: request.arrival_time_ms)\n",
    )
    path.write_text(source, encoding="utf-8")
    assert _test_process(wrong, "pytest", "-q", "tests").returncode == 0
    add_acceptance_tests(TASK, wrong)
    rejected = _test_process(wrong, "unittest", "discover", "-s", "tests", "-v")
    assert rejected.returncode != 0
    assert "FAIL" in rejected.stderr or "ERROR" in rejected.stderr


def test_large_edit_auto_selection_locator_and_prompt(
    frozen: tuple[Path, Path, str],
) -> None:
    baseline_root, optimized_root, _ = frozen
    config = GatewayConfig(optimized_root)
    query = ContextQuery(TASK.prompt)
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    repeat = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    locator = build_offline_locator(config, query)
    assert pack.fingerprint == repeat.fingerprint == locator.pack_fingerprint
    assert locator == build_offline_locator(config, query)
    assert MIN_CANDIDATE_SOURCE_TOKENS == 10_000
    decision = decide_offline_locator(pack, locator, read_only=TASK.read_only)
    assert decision == decide_offline_locator(pack, locator, read_only=TASK.read_only)
    assert not decision.use_locator and decision.candidate_tokens == 23982
    assert decision.reason == "workspace_write_not_validated_for_full_locator"
    assert decision.selected_tokens == 5993 and decision.locator_tokens == 214
    assert len(pack.candidates) >= 29 and len(locator.selected_paths) == 14
    assert len(locator.selected_ranges) == 19
    assert locator.sha256 == "5217171cd64bca42a207a2cbf070c4b9a9964dfe96bf5375e944a5045e70ad50"
    selected = set(locator.selected_paths)
    assert len(selected & REQUIRED_PRODUCTION) == 2
    assert VISIBLE_TEST_PATH in selected
    index = RepositoryIndexer(config).index()
    covered_symbols = tuple(name for name in REQUIRED_SYMBOLS if any(
        symbol.path == excerpt.path and excerpt.start_line <= symbol.start_line and
        excerpt.end_line >= (symbol.end_line or symbol.start_line)
        for symbol in index.find_symbol(name) for excerpt in pack.excerpts))
    assert covered_symbols == (
        "SimulationEngine.run", "EventType", "InferenceRequest.cancel",
        "ExistingSimulationTests",
    )
    unrelated = selected - {
        *REQUIRED_PRODUCTION, "middle_man/lab/request.py",
        "middle_man/lab/runner.py", "middle_man/lab/trace.py",
        "middle_man/lab/serialization.py", "middle_man/lab/prefix_cache.py",
        VISIBLE_TEST_PATH,
    }
    assert unrelated == {
        "middle_man/lab/benchmarks.py", "middle_man/lab/reporting.py",
        "middle_man/lab/visualization.py", "middle_man/lab/comparison.py",
        "middle_man/lab/workloads.py", "middle_man/lab/suites.py",
    }
    assert "test_unknown_id_is_rejected_before_mutation" not in locator.text
    assert "IndependentCancellationAcceptance" not in locator.text
    assert "cancelled_requests=sum(" not in locator.text
    assert "class SimulationEngine:" not in locator.text
    baseline = runner.build_invocation(
        "codex", TASK, "baseline", baseline_root, model="gpt-6-sol",
        effort="high", optimized_mode="offline-auto")
    optimized = runner.build_invocation(
        "codex", TASK, "optimized", optimized_root, model="gpt-6-sol",
        effort="high", optimized_mode="offline-auto")
    original = TASK.prompt + " Work only inside this benchmark working copy. Do not commit or push."
    assert baseline[-1] == original
    assert optimized[-1].encode("utf-8") == baseline[-1].encode("utf-8")
    assert LOCATOR_HEADING not in optimized[-1]
    forced = runner.build_invocation(
        "codex", TASK, "optimized", optimized_root, model="gpt-6-sol",
        effort="high", optimized_mode="offline-locator", locator_text=locator.text)
    assert forced[-1] == append_offline_locator(original, locator.text)
    for argv in (baseline, optimized):
        assert argv[argv.index("-s") + 1] == "workspace-write"
        assert "--ignore-user-config" in argv
        assert not any("mcp_servers." in part or "AGENTS.md" in part for part in argv)
        assert "IndependentCancellationAcceptance" not in argv[-1]
    with pytest.raises(ValueError, match="requires offline-auto"):
        runner.build_invocation("codex", TASK, "optimized", optimized_root,
                                model="gpt-6-sol", effort="high", optimized_mode="mcp")


def test_medium_size_tiers_cross_unchanged_gate(
    frozen: tuple[Path, Path, str], tmp_path: Path,
) -> None:
    _, source, _ = frozen
    expected = {
        "core": (3016, False), "memory": (4901, False),
        "scheduling": (6603, False), "adapters": (8335, False),
        "memory-control": (11157, False), "execution": (15004, False),
        "workflows": (19322, False),
    }
    for name, paths in SAMPLE_TIERS:
        root = tmp_path / name
        for relative in paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        observed = measure(root, TASK.prompt)
        assert observed["candidate_tokens"] == expected[name][0]
        assert (observed["auto_decision"] == "LOCATOR USED") is expected[name][1]
        assert observed["candidate_tokens"] > observed["selected_tokens"]
        assert observed["locator_tokens"] > 0
    full = measure(source, TASK.prompt)
    assert full["indexed_files"] == 31 and full["indexed_source_tokens"] == 24008
    assert full["candidate_paths"] == 29 and full["selected_paths"] == 14
    assert full["selected_ranges"] == 19
    assert full["selected_candidate_ratio"] == 0.2499
    assert full["locator_selected_ratio"] == 0.0357


def test_large_edit_auto_dry_run_does_not_start_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "_codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    main(["codex", "benchmark", "run", "large-edit-v1", "--repo", str(tmp_path),
          "--dry-run", "--optimized-mode", "offline-auto", "--windows-sandbox", "unelevated"])
    output = capsys.readouterr().out
    assert "Offline AUTO: BYPASSED" in output and LOCATOR_HEADING not in output
    assert "mcp_servers." not in output and "no AGENTS.md or MCP registration" in output
    assert "IndependentCancellationAcceptance" not in output
    assert not (tmp_path / ".middle_man_cache").exists()
    with pytest.raises(SystemExit, match="requires --optimized-mode offline-auto"):
        main(["codex", "benchmark", "run", "large-edit-v1", "--repo", str(tmp_path),
              "--dry-run"])
