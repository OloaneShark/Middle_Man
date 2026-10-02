"""Local-only explicit offline-anchor harness tests; no Codex inference."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark import infrastructure, runner
from middle_man.gateway.codex_benchmark.offline_anchor import (
    ANCHOR_HEADING, append_offline_anchors, render_offline_anchors,
)
from middle_man.gateway.codex_benchmark.offline_locator import LOCATOR_HEADING, build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import BenchmarkPolicy, selector_implementation_fingerprint


TASK = next(item for item in TASKS if item.id == "large-edit-v1")
ANCHOR_TEXT = ("Relevant entry points:\n"
               "- middle_man/lab/engine.py: SimulationEngine.run\n"
               "- middle_man/lab/request.py: InferenceRequest.cancel\n"
               "- tests/test_batch_cancellation.py: ExistingSimulationTests.test_uncancelled_requests_complete\n"
               "- middle_man/lab/events.py: SimulationEvent")


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory):
    baseline, optimized, fingerprint = prepare_pair(
        TASK, tmp_path_factory.mktemp("phase-22-17") / "pair", None)
    config = GatewayConfig(optimized)
    pack = ContextBuilder(config).build(ContextQuery(TASK.prompt), mode="balanced",
                                        max_context_tokens=6000)
    anchors = render_offline_anchors(pack, config)
    return baseline, optimized, fingerprint, pack, anchors


def test_exact_anchor_and_prompts(prepared) -> None:
    baseline_root, optimized_root, fingerprint, pack, anchors = prepared
    assert source_fingerprint(baseline_root) == source_fingerprint(optimized_root) == fingerprint
    assert anchors == render_offline_anchors(pack, GatewayConfig(optimized_root))
    assert anchors.text == ANCHOR_TEXT and anchors.estimated_tokens == 66
    assert tuple(item.phase for item in anchors.anchors) == (
        "REQUIRED", "REQUIRED", "COVERAGE", "COVERAGE")
    baseline = runner.build_invocation("codex", TASK, "baseline", baseline_root,
                                       model="gpt-6-sol", effort="high", optimized_mode="offline-anchor")
    optimized = runner.build_invocation("codex", TASK, "optimized", optimized_root,
                                        model="gpt-6-sol", effort="high", optimized_mode="offline-anchor",
                                        anchors=anchors)
    original = TASK.prompt + " Work only inside this benchmark working copy. Do not commit or push."
    assert baseline[-1] == original
    assert optimized[-1] == append_offline_anchors(original, anchors)
    assert optimized[-1].startswith(original + "\n\n" + ANCHOR_HEADING + "\n")
    assert optimized[-1].count(ANCHOR_HEADING) == 1
    assert LOCATOR_HEADING not in optimized[-1]
    assert "middle_man/lab/benchmarks.py" not in optimized[-1]
    assert "IndependentCancellationAcceptance" not in optimized[-1]
    assert "test_unknown_id_is_rejected_before_mutation" not in optimized[-1]
    assert "class SimulationEngine" not in optimized[-1]
    assert all(argv[argv.index("-s") + 1] == "workspace-write" for argv in (baseline, optimized))
    assert all("--ignore-user-config" in argv and not any(
        "mcp_servers." in part or "AGENTS.md" in part for part in argv) for argv in (baseline, optimized))
    assert not (baseline_root / "AGENTS.md").exists() and not (optimized_root / "AGENTS.md").exists()
    assert HeuristicTokenEstimator().estimate(append_offline_anchors("", anchors)) > 66
    assert pack.fingerprint


def test_anchor_rejects_missing_source_bearing_and_wrong_task(prepared, tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    _, root, _, _, anchors = prepared
    with pytest.raises(ValueError, match="requires generated anchors"):
        runner.build_invocation("codex", TASK, "optimized", root, model="gpt-6-sol",
                                effort="high", optimized_mode="offline-anchor")
    with pytest.raises(ValueError, match="source-free"):
        append_offline_anchors("prompt", replace(anchors, text=anchors.text + "\nclass Secret: pass"))
    with pytest.raises(ValueError, match="two to four"):
        append_offline_anchors("prompt", replace(anchors, anchors=()))
    other = next(item for item in TASKS if item.id == "preemption-v4")
    with pytest.raises(ValueError, match="only for large-edit-v1"):
        runner.build_invocation("codex", other, "optimized", root, model="gpt-6-sol",
                                effort="high", optimized_mode="offline-anchor", anchors=anchors)
    monkeypatch.setattr(runner, "_codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not start")))
    with pytest.raises(ValueError, match="only large-edit-v1"):
        runner.run_suite(("preemption-v4",), repository_root=tmp_path,
                         artifact_base=tmp_path, optimized_mode="offline-anchor")
    with pytest.raises(ValueError, match="canonical benchmark policy"):
        runner.run_suite(("large-edit-v1",), repository_root=tmp_path,
                         artifact_base=tmp_path, optimized_mode="offline-anchor",
                         policy=BenchmarkPolicy(initial_context_budget=5000))


def test_anchor_dry_run_never_starts_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(runner, "_codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not start")))
    main(["codex", "benchmark", "run", "large-edit-v1", "--repo", str(tmp_path),
          "--dry-run", "--optimized-mode", "offline-anchor", "--windows-sandbox", "unelevated"])
    output = capsys.readouterr().out
    assert "Optimized mode: offline-anchor" in output and "Offline anchor: 66 heuristic tokens" in output
    assert ANCHOR_HEADING in output and ANCHOR_TEXT in output
    assert LOCATOR_HEADING not in output and "mcp_servers." not in output
    assert "no AGENTS.md or MCP registration" in output
    assert not (tmp_path / ".middle_man_cache").exists()
    with pytest.raises(SystemExit, match="only large-edit-v1"):
        main(["codex", "benchmark", "run", "oauth-bug", "--repo", str(tmp_path),
              "--dry-run", "--optimized-mode", "offline-anchor"])
    with pytest.raises(SystemExit, match="only large-edit-v1"):
        main(["codex", "benchmark", "run-all", "--repo", str(tmp_path),
              "--dry-run", "--optimized-mode", "offline-anchor"])


def test_anchor_run_audit_and_read_labels(prepared, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    _, root, fingerprint, pack, anchors = prepared
    observed: list[list[str]] = []
    real_run = subprocess.run
    events = "\n".join(json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": f"Get-Content {path}"}}) for path in (
        "middle_man/lab/engine.py", "middle_man/lab/metrics.py"))

    def fake_run(argv: list[str], **kwargs):
        if argv[0] == "codex":
            observed.append(argv)
            return subprocess.CompletedProcess(argv, 0, events, "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no MCP")))
    monkeypatch.setattr(runner, "_evaluate", lambda *args: (True, (), None, None))
    result = runner.run_one(TASK, "optimized", root, fingerprint, order=1,
                            codex_command="codex", codex_version="local", model="gpt-6-sol",
                            effort="high", timeout=10, artifact_root=tmp_path,
                            primary_repository_root=tmp_path, windows_sandbox="unelevated",
                            optimized_mode="offline-anchor")
    assert len(observed) == 1 and result.valid and result.mcp_calls_by_tool == ()
    assert observed[0][-1] == append_offline_anchors(
        runner.build_invocation("codex", TASK, "baseline", root, model="gpt-6-sol",
                                effort="high", optimized_mode="offline-anchor",
                                windows_sandbox="unelevated")[-1], anchors)
    audit = result.offline_anchor_audit
    assert audit["delivery_mode"] == "offline-anchor"
    assert audit["anchor_estimated_tokens"] == 66
    assert audit["prompt_append_estimated_tokens"] == HeuristicTokenEstimator().estimate(
        append_offline_anchors("", anchors))
    assert audit["anchor_paths"] == tuple(item.path for item in anchors.anchors)
    assert audit["anchor_symbols"] == tuple(item.symbol for item in anchors.anchors)
    assert audit["anchor_phases"] == tuple(item.phase for item in anchors.anchors)
    assert audit["pack_fingerprint"] == pack.fingerprint
    assert audit["selector_implementation_fingerprint"] == selector_implementation_fingerprint()
    assert result.native_read_anchor_coverage == (
        ("middle_man/lab/engine.py", "ANCHOR_PATH"),
        ("middle_man/lab/metrics.py", "NON_ANCHOR_PATH"))
    assert result.native_read_locator_coverage == () and result.offline_locator_audit is None
    assert not (root / "AGENTS.md").exists()
    assert not (root / ".middle_man_cache" / "mcp_usage.jsonl").exists()
    serialized = json.loads(json.dumps(asdict(result)))
    assert serialized["offline_anchor_audit"]["anchor_estimated_tokens"] == 66
    report = runner.format_report({"run_id": "local", "codex_version": "local", "model": "gpt-6-sol",
                                   "effort": "high", "optimized_mode": "offline-anchor", "pairs": [{
                                       "title": TASK.title, "task_version": TASK.schema_version,
                                       "quality_gate": "CORRECT", "valid": True,
                                       "baseline": asdict(result), "optimized": asdict(result),
                                   }]})
    assert "Native anchor reads: 1/4 paths accessed; non-anchor paths: 1" in report
    assert "LOCATOR_PATH" not in report and "Native locator reads" not in report


def test_anchor_preflight_skips_mcp_without_inference(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(infrastructure.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runner, "_codex_version", lambda _: "local-cli")
    monkeypatch.setattr(runner, "_mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no MCP")))
    monkeypatch.setattr(infrastructure, "_snapshot_mcp_call",
                        lambda *_: (_ for _ in ()).throw(AssertionError("no MCP")))

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
                                                 repository_root=tmp_path, optimized_mode="offline-anchor")
    assert result.passed and not result.optimized_mcp_root_verified
    assert result.primary_repo_usage_unchanged


def test_anchor_fails_closed_before_process_on_contamination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, root, fingerprint = prepare_pair(TASK, tmp_path / "pair", None)
    real_run = subprocess.run
    monkeypatch.setattr(runner.subprocess, "run", lambda argv, **kwargs: (
        (_ for _ in ()).throw(AssertionError("Codex must not start")) if argv[0] == "codex"
        else real_run(argv, **kwargs)))
    # Status and source checks also reject an untracked AGENTS file before inference.
    (root / "AGENTS.md").write_text("contamination\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        runner.run_one(TASK, "optimized", root, fingerprint, order=1,
                       codex_command="codex", codex_version="local", model="gpt-6-sol",
                       effort="high", timeout=10, artifact_root=tmp_path,
                       primary_repository_root=tmp_path, windows_sandbox="unelevated",
                       optimized_mode="offline-anchor")
    (root / "AGENTS.md").unlink()
    usage = root / ".middle_man_cache" / "mcp_usage.jsonl"
    usage.parent.mkdir(parents=True, exist_ok=True)
    usage.write_text('{"tool":"middleman_context"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="MCP usage records"):
        runner.run_one(TASK, "optimized", root, fingerprint, order=1,
                       codex_command="codex", codex_version="local", model="gpt-6-sol",
                       effort="high", timeout=10, artifact_root=tmp_path,
                       primary_repository_root=tmp_path, windows_sandbox="unelevated",
                       optimized_mode="offline-anchor")
    assert not runner._infrastructure_valid(
        "optimized", ({"tool": "middleman_context"},),
        runner.isolation_warnings("optimized", ({"tool": "middleman_context"},), (),
                                  optimized_mode="offline-anchor"), optimized_mode="offline-anchor")
