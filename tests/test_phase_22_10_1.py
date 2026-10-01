"""Local-only canonical benchmark policy plumbing and stdio proof."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import Client, StdioServerParameters

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark.runner import (
    CodexBenchmarkSuite, _infrastructure_valid, _mcp_preflight, _server_args,
    build_invocation, format_report, validate_initial_context_budgets,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity, BenchmarkPolicy
from middle_man.mcp.gateway import MCPGateway


TASK = next(task for task in TASKS if task.id == "preemption-v4")
POLICY = BenchmarkPolicy(6000, 12000, 4000)
QUERY = (
    "Explain KV preemption in this repository: identify victim selection policy implementation class, "
    "controller coordinating KV allocation and release, scheduler WorkKind for preempted requests, "
    "InferenceRequest generated-output field preserved, and proving test file; trace interactions and "
    "KV block release. Read only, no changes."
)


def test_runner_policy_and_baseline_isolation(tmp_path: Path) -> None:
    default = _server_args(tmp_path, run_id="local", task_id=TASK.id, mode="optimized")
    assert default == [
        "-I", "-c", "import sys;sys.path.insert(0,sys.argv.pop(1));"
        "from middle_man.cli.main import main;main()", str(Path(__file__).resolve().parents[1]),
        "mcp", "serve", "--repo", str(tmp_path.resolve()),
        "--benchmark-run-id", "local", "--benchmark-task-id", "preemption-v4",
        "--benchmark-mode", "optimized", "--benchmark-source-commit", TASK.source_ref,
        "--benchmark-context-budget", "6000", "--benchmark-expansion-budget", "12000",
        "--tool-profile", "codex-core",
    ]
    assert default == _server_args(tmp_path, run_id="local", task_id=TASK.id,
                                   mode="optimized", policy=BenchmarkPolicy())
    assert "--benchmark-source-delivery-budget" not in default
    progressive = _server_args(tmp_path, run_id="local", task_id=TASK.id,
                               mode="optimized", policy=POLICY)
    assert progressive[progressive.index("--benchmark-context-budget") + 1] == "6000"
    assert progressive[progressive.index("--benchmark-source-delivery-budget") + 1] == "4000"
    assert progressive[progressive.index("--benchmark-expansion-budget") + 1] == "12000"
    assert progressive[-2:] == ["--tool-profile", "codex-core"]
    baseline = build_invocation("codex", TASK, "baseline", tmp_path, model="gpt-6-sol",
                                effort="high", run_id="local", policy=POLICY)
    optimized = build_invocation("codex", TASK, "optimized", tmp_path, model="gpt-6-sol",
                                 effort="high", run_id="local", policy=POLICY)
    assert "mcp_servers.middle-man" not in " ".join(baseline)
    assert "--benchmark-source-delivery-budget" not in " ".join(baseline)
    assert "--benchmark-source-delivery-budget" in " ".join(optimized)


def test_cli_dry_run_and_invalid_policy(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner._codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    args = ["codex", "benchmark", "run", "preemption-v4", "--repo", str(tmp_path),
            "--dry-run", "--benchmark-source-delivery-budget", "4000"]
    main(args)
    output = capsys.readouterr().out
    baseline = output.split("baseline snapshot:")[1].split("optimized snapshot:")[0]
    optimized = output.split("optimized snapshot:")[1]
    assert "--benchmark-source-delivery-budget" not in baseline
    assert "--benchmark-context-budget 6000" in optimized
    assert "--benchmark-source-delivery-budget 4000" in optimized
    assert "--benchmark-expansion-budget 12000" in optimized
    with pytest.raises(SystemExit, match="source delivery budget"):
        main(args[:-1] + ["6001"])


@pytest.mark.parametrize("configured", [BenchmarkPolicy(), POLICY])
def test_mcp_preflight_rejects_policy_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                               configured: BenchmarkPolicy) -> None:
    wrong = POLICY if configured.initial_source_delivery_budget is None else BenchmarkPolicy()
    args = _server_args(tmp_path, run_id="local", task_id=TASK.id,
                        mode="optimized", policy=wrong)
    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(stdout=json.dumps({"enabled": True, "transport": {
            "args": args, "command": sys.executable}}))
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="MCP arguments"):
        _mcp_preflight("codex", "optimized", tmp_path, run_id="local", task_id=TASK.id,
                       policy=configured)


def test_progressive_audit_fails_closed() -> None:
    audit = {"effective_context_tokens": 6000, "benchmark_context_cap": 6000,
             "initial_source_delivery_budget": 4000, "initial_source_delivery_tokens": 3984,
             "initial_source_delivery_overrun": 0, "canonical_selection_fixed": True,
             "force_replay": False}
    entry = {"tool": "middleman_context", "success": True, "budget": audit}
    assert not validate_initial_context_budgets((entry,), POLICY)
    for key, value in (("initial_source_delivery_budget", None),
                       ("initial_source_delivery_budget", 3999),
                       ("canonical_selection_fixed", False),
                       ("effective_context_tokens", 5999),
                       ("force_replay", True),
                       ("initial_source_delivery_tokens", 4001),
                       ("initial_source_delivery_overrun", -1)):
        bad = {**entry, "budget": {**audit, key: value}}
        warnings = validate_initial_context_budgets((bad,), POLICY)
        assert warnings and not _infrastructure_valid("optimized", (bad,), warnings)
    soft_cap = {**entry, "budget": {**audit, "initial_source_delivery_tokens": 4050,
                                    "initial_source_delivery_overrun": 50}}
    assert not validate_initial_context_budgets((soft_cap,), POLICY)
    assert not validate_initial_context_budgets(({"tool": "middleman_context", "success": True,
                                                   "budget": {"effective_context_tokens": 6000,
                                                              "benchmark_context_cap": 6000}},),
                                                 BenchmarkPolicy())
    assert validate_initial_context_budgets((entry,), BenchmarkPolicy())


def test_result_and_report_policy() -> None:
    suite = CodexBenchmarkSuite("local", "now", "test", "test", "high", (), "artifact", (),
                                benchmark_policy=POLICY)
    data = asdict(suite)
    assert data["benchmark_policy"] == asdict(POLICY)
    assert "Delivery policy: progressive; canonical selection: 6000; initial source delivery: 4000; " \
           "expansion ceiling: 12000" in format_report(data)
    data["benchmark_policy"] = asdict(BenchmarkPolicy())
    assert "Delivery policy: one-shot" in format_report(data)


def test_full_required_seed_records_soft_cap_overrun(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    estimator = HeuristicTokenEstimator()
    monkeypatch.setattr("middle_man.mcp.gateway.plan_seed", lambda pack, budget: (
        pack.excerpts, max(0, sum(estimator.estimate(item.text) for item in pack.excerpts) - budget)))
    policy = BenchmarkPolicy(6000, 12000, 1)
    gateway = MCPGateway(GatewayConfig(tmp_path), BenchmarkIdentity(
        "localoverrun", TASK.id, "optimized", "fixture", policy))
    result = gateway.context("Inspect module.py alpha", paths=["module.py"])
    assert "progressive_delivery" not in result
    entry = json.loads((gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8"))
    assert entry["budget"]["initial_source_delivery_tokens"] > 1
    assert entry["budget"]["initial_source_delivery_overrun"] == (
        entry["budget"]["initial_source_delivery_tokens"] - 1)
    assert not validate_initial_context_budgets((entry,), policy)


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-10-1") / "pair", "guidance\n")
    return optimized


def test_official_progressive_stdio_and_selected_path(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    expected = ContextBuilder(config).build(QUERY, mode="balanced", max_context_tokens=6000)
    assert expected.metrics.estimated_selected_tokens == 5949

    async def exercise() -> tuple[dict, dict, dict]:
        params = StdioServerParameters(command=sys.executable,
                                       args=_server_args(pinned, run_id="local-22101", task_id=TASK.id,
                                                         mode="optimized", policy=POLICY), cwd=pinned)
        async with Client(params, raise_exceptions=True, read_timeout_seconds=30) as client:
            first = await client.call_tool("middleman_context", {"task": QUERY, "mode": "balanced",
                                                                 "max_context_tokens": 6000})
            assert not first.is_error
            data = first.structured_content
            mapped = next(item["path"] for item in data["evidence_map"] if not item["delivered"])
            args = {"fingerprint": data["fingerprint"], "kind": "selected_path", "target": mapped,
                    "max_context_tokens": 12000}
            second = await client.call_tool("middleman_expand_context", args)
            third = await client.call_tool("middleman_expand_context", args)
            assert not second.is_error and not third.is_error
            return data, second.structured_content, third.structured_content

    first, second, third = asyncio.run(exercise())
    assert first["fingerprint"] == expected.fingerprint
    assert first["budget"]["effective_context_tokens"] == 6000
    assert "initial_source_delivery_tokens" not in first["budget"]
    assert "initial_source_delivery_overrun" not in first["budget"]
    assert first["progressive_delivery"]["seed_source_tokens"] == 3984
    assert first["evidence_map"]
    assert second["fingerprint"] == first["fingerprint"] == third["fingerprint"]
    assert second["excerpts"] and second["delta_only"]
    assert third["excerpts"] == [] and third["delta_only"]
    entries = tuple(json.loads(line) for line in (config.cache_dir / "mcp_usage.jsonl")
                    .read_text(encoding="utf-8").splitlines())
    assert [entry["call_sequence"] for entry in entries] == [1, 2, 3]
    assert len({entry["server_session_id"] for entry in entries}) == 1
    assert not validate_initial_context_budgets(entries, POLICY)
    assert entries[0]["budget"]["initial_source_delivery_tokens"] == 3984
    assert entries[0]["budget"]["initial_source_delivery_overrun"] == 0
    assert entries[1]["budget"]["benchmark_expansion_ceiling"] == 12000
    assert entries[0]["ledger_lines_after"] < entries[1]["ledger_lines_after"]
    assert entries[1]["ledger_lines_after"] == entries[2]["ledger_lines_after"]
    assert entries[2]["new_lines_delivered"] == 0
    receipts = [json.loads(line) for line in (config.cache_dir / "benchmark_receipts.jsonl")
                .read_text(encoding="utf-8").splitlines()]
    assert receipts[0]["policy"] == asdict(POLICY)
    assert "LargestPrivateOwnerPolicy" not in json.dumps(receipts[0]["policy"])
