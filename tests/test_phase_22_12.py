"""Local-only offline locator benchmark integration; no Codex inference."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark import infrastructure, runner
from middle_man.gateway.codex_benchmark.offline_locator import (
    LOCATOR_HEADING, append_offline_locator, build_offline_locator,
)
from middle_man.gateway.codex_benchmark.preemption_v3 import measure_required_source
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.tokens import HeuristicTokenEstimator
from tests.test_phase_22_11 import ACTUAL_QUERY, STRONG


TASK = next(task for task in TASKS if task.id == "preemption-v4")
ESTIMATOR = HeuristicTokenEstimator()


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    baseline, optimized, fingerprint = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-12") / "pair", None)
    assert not (baseline / "AGENTS.md").exists() and not (optimized / "AGENTS.md").exists()
    assert fingerprint == source_fingerprint(baseline) == source_fingerprint(optimized)
    assert fingerprint == "a548097a4294fd67b2d42a5ab616c19b8ab226d702a406fa36f588873d0a0c1b"
    assert not subprocess.check_output(["git", "-C", str(optimized), "status", "--porcelain=v1"]).strip()
    return optimized


def test_actual_exact_and_strong_offline_locators(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    for name, task in {"actual": ACTUAL_QUERY, "exact": TASK.prompt, **STRONG}.items():
        query = ContextQuery(task, symbols=("WorkKind", "InferenceRequest") if name == "actual" else ())
        pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
        locator = build_offline_locator(config, query)
        assert locator == build_offline_locator(config, query)
        assert locator.pack_fingerprint == pack.fingerprint
        assert locator.selected_source_tokens == pack.metrics.estimated_selected_tokens
        assert locator.selected_paths == pack.selected_files
        assert locator.selected_ranges == tuple((item.path, item.start_line, item.end_line)
                                                for item in pack.excerpts)
        assert locator.sha256 == hashlib.sha256(locator.text.encode("utf-8")).hexdigest()
        assert locator.estimated_tokens == ESTIMATOR.estimate(locator.text)
        assert locator.estimated_tokens <= 800
        assert all(locator.text.count(f"- {path}:") == 1 for path in locator.selected_paths)
        assert "None" not in locator.text and "candidate_score" not in locator.text
        assert "selected_range_phases" not in locator.text and "victim_selection_policy" not in locator.text
        assert "def release_request" not in locator.text
        recall = measure_required_source(pack)
        print("OFFLINE_LOCATOR", json.dumps({"query": name, "tokens": locator.estimated_tokens,
              "text": locator.text, "source_tokens": locator.selected_source_tokens,
              "paths": list(locator.selected_paths), "ranges": list(locator.selected_ranges),
              "required_paths": 7 - len(recall.missing_files),
              "required_identifiers": 7 - len(recall.missing_symbols)}, sort_keys=True))
        if name == "actual":
            assert locator.selected_source_tokens == 5845
            assert len(locator.selected_paths) == 13 and len(locator.selected_ranges) == 16
            assert "middle_man/lab/memory.py" not in locator.selected_paths
        if name == "exact":
            assert locator.selected_source_tokens == 5983
            assert len(locator.selected_paths) == 12 and len(locator.selected_ranges) == 13


@pytest.mark.parametrize("case", coverage_cases(), ids=lambda case: case.name)
def test_unrelated_offline_locator(case: object, tmp_path: Path) -> None:
    for path, source in case.files:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    config = GatewayConfig(tmp_path)
    pack = ContextBuilder(config).build(ContextQuery(case.query), mode="balanced", max_context_tokens=6000)
    locator = build_offline_locator(config, ContextQuery(case.query))
    index = RepositoryIndexer(config).index()
    selected = set(locator.selected_paths)
    symbols = sum(any(item.path == symbol.path and item.start_line <= symbol.start_line and
                      item.end_line >= (symbol.end_line or symbol.start_line)
                      for symbol in index.find_symbol(name) for item in pack.excerpts)
                  for name in case.required_symbols)
    print("OFFLINE_FIXTURE", json.dumps({"case": case.name, "tokens": locator.estimated_tokens,
          "required_paths": len(selected & set(case.required_files)), "required_symbols_by_range": symbols}))
    assert set(case.required_files) <= selected and symbols == len(case.required_symbols)


def test_offline_locator_contains_no_source_or_secret(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text(
        "def alpha():\n    return 'SECRET_SOURCE_SENTINEL Bearer fake-token-123456789012'\n", encoding="utf-8")
    locator = build_offline_locator(GatewayConfig(tmp_path), ContextQuery("Inspect module.py alpha"))
    assert "SECRET_SOURCE_SENTINEL" not in locator.text
    assert "fake-token-123456789012" not in locator.text
    assert "return '" not in locator.text
    assert "module.py:" in locator.text
    assert "pack_fingerprint" not in append_offline_locator("Task", locator.text)


def test_offline_locator_rejects_outside_path(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    config = GatewayConfig(tmp_path)
    original = ContextBuilder.build

    def unsafe(builder: ContextBuilder, *args: object, **kwargs: object) -> object:
        pack = original(builder, *args, **kwargs)
        return replace(pack, excerpts=(replace(pack.excerpts[0], path="../outside.py"),))

    monkeypatch.setattr(ContextBuilder, "build", unsafe)
    with pytest.raises(ValueError, match="escapes repository root"):
        build_offline_locator(config, ContextQuery("Inspect module.py alpha"))


def test_offline_preflight_skips_mcp_without_codex(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(infrastructure.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runner, "_codex_version", lambda _: "local-cli")
    monkeypatch.setattr(runner, "_mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("MCP must not start")))
    monkeypatch.setattr(infrastructure, "_snapshot_mcp_call",
                        lambda *_: (_ for _ in ()).throw(AssertionError("MCP must not start")))

    def fake_probe(command: str, root: Path, permission: str, script: str,
                   windows_sandbox: str) -> subprocess.CompletedProcess[str]:
        if permission == ":read-only" and "Get-Content" in script:
            return subprocess.CompletedProcess([], 0, "original\n", "")
        if permission == ":read-only":
            return subprocess.CompletedProcess([], 1, "", "blocked")
        (root / "marker.txt").write_text("written\n", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(infrastructure, "_probe", fake_probe)
    result = infrastructure.run_local_preflight("codex", model="gpt-6-sol", effort="high",
                                                 windows_sandbox="unelevated", snapshot_root=tmp_path,
                                                 repository_root=tmp_path, optimized_mode="offline-locator")
    assert result.passed and not result.optimized_mcp_root_verified
    assert result.primary_repo_usage_unchanged


def test_invocation_and_dry_run_are_mcp_free(pinned: Path, tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    locator = build_offline_locator(GatewayConfig(pinned), ContextQuery(TASK.prompt))
    baseline = runner.build_invocation("codex", TASK, "baseline", pinned, model="gpt-6-sol", effort="high",
                                       windows_sandbox="unelevated", optimized_mode="offline-locator")
    default_baseline = runner.build_invocation("codex", TASK, "baseline", pinned, model="gpt-6-sol",
                                               effort="high", windows_sandbox="unelevated")
    optimized = runner.build_invocation("codex", TASK, "optimized", pinned, model="gpt-6-sol", effort="high",
                                        windows_sandbox="unelevated", optimized_mode="offline-locator",
                                        locator_text=locator.text)
    assert baseline == default_baseline
    assert optimized[-1].startswith(baseline[-1] + "\n\n" + LOCATOR_HEADING)
    assert optimized[-1].count(TASK.prompt) == 1
    assert all(not any("mcp_servers." in arg for arg in command) for command in (baseline, optimized))
    assert all("--ignore-user-config" in command and "read-only" in command and
               "gpt-6-sol" in command and 'model_reasoning_effort="high"' in command and
               'windows.sandbox="unelevated"' in command and "--output-schema" in command
               for command in (baseline, optimized))
    assert baseline[baseline.index("--output-schema") + 1] == optimized[optimized.index("--output-schema") + 1]
    with pytest.raises(ValueError, match="requires only its precomputed locator"):
        runner.build_invocation("codex", TASK, "optimized", pinned, model="gpt-6-sol", effort="high",
                                optimized_mode="offline-locator")
    monkeypatch.setattr(runner, "_codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    main(["codex", "benchmark", "run", "preemption-v4", "--repo", str(tmp_path), "--dry-run",
          "--optimized-mode", "offline-locator", "--windows-sandbox", "unelevated"])
    output = capsys.readouterr().out
    assert "Optimized mode: offline-locator" in output and LOCATOR_HEADING in output
    assert "mcp_servers." not in output and "optimized MCP policy args" not in output
    assert "no AGENTS.md or MCP registration" in output
    assert not (tmp_path / ".middle_man_cache").exists()
    with pytest.raises(SystemExit, match="requires only preemption-v4"):
        main(["codex", "benchmark", "run", "oauth-bug", "--repo", str(tmp_path), "--dry-run",
              "--optimized-mode", "offline-locator"])


def test_offline_run_isolation_and_audit_without_codex(pinned: Path, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    actual_run = subprocess.run

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[0] == "codex":
            assert not any("mcp_servers." in item for item in argv)
            assert LOCATOR_HEADING in argv[-1]
            return subprocess.CompletedProcess(argv, 0, "", "")
        return actual_run(argv, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("MCP preflight must not run")))
    result = runner.run_one(TASK, "optimized", pinned, source_fingerprint(pinned), order=1,
                            codex_command="codex", codex_version="local", model="gpt-6-sol", effort="high",
                            timeout=10, artifact_root=artifacts, primary_repository_root=tmp_path,
                            windows_sandbox="unelevated", optimized_mode="offline-locator")
    assert result.valid and result.tool_profile == "none" and result.mcp_calls_in_events == 0
    assert result.mcp_calls_by_tool == () and result.offline_locator_audit is not None
    assert result.offline_locator_audit["locator_estimated_tokens"] > 0
    assert result.offline_locator_audit["canonical_selected_source_tokens"] == 5983
    assert not (pinned / ".middle_man_cache" / "mcp_usage.jsonl").exists()
    assert not subprocess.check_output(["git", "-C", str(pinned), "status", "--porcelain=v1"]).strip()
    assert runner.isolation_warnings("optimized", (), (), optimized_mode="offline-locator") == ()
    contaminated = runner.isolation_warnings("optimized", ({"tool": "middleman_context"},), (),
                                              optimized_mode="offline-locator")
    assert contaminated and not runner._infrastructure_valid("optimized", ({"tool": "middleman_context"},),
                                                              contaminated, optimized_mode="offline-locator")
