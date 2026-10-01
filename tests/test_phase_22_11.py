"""Local-only locator delivery and fixed-overhead measurements."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from middle_man.cli.main import main
from middle_man.gateway.codex_benchmark.preemption_v3 import TASK_A_V3_UNITS, measure_required_source
from middle_man.gateway.codex_benchmark.runner import (
    _infrastructure_valid, _server_args, validate_initial_context_budgets,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.coverage_quality import coverage_cases
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.secrets import MARKER
from middle_man.gateway.source import StaleSourceError
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity, BenchmarkPolicy
from middle_man.mcp.gateway import MCPGateway
from middle_man.mcp.server import CORE_INSTRUCTIONS, create_server
from middle_man.mcp.surface import measure_tool_surface
from tests.test_phase_22_10 import STRONG


TASK = next(task for task in TASKS if task.id == "preemption-v4")
ACTUAL_QUERY = (
    "Explain KV preemption in this Middle_Man repository: identify concrete victim selection policy "
    "implementation class, controller coordinating KV allocation/release/preemption, scheduler WorkKind "
    "for preempted request recomputation, InferenceRequest generated output field preserved, and proving "
    "test file. Trace interactions and KV block release; read only."
)
LOCATOR = BenchmarkPolicy(delivery_policy="locator_only")
ESTIMATOR = HeuristicTokenEstimator()


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _, optimized, _ = prepare_pair(TASK, tmp_path_factory.mktemp("phase-22-11") / "pair", "guidance\n")
    assert source_fingerprint(optimized) == "a548097a4294fd67b2d42a5ab616c19b8ab226d702a406fa36f588873d0a0c1b"
    return optimized


def _identity(policy: BenchmarkPolicy) -> BenchmarkIdentity:
    return BenchmarkIdentity("local2211", TASK.id, "optimized", "fixture", policy)


def _result_tokens(value: dict) -> int:
    return ESTIMATOR.estimate(json.dumps(value, ensure_ascii=False))


def _mapped_ranges(data: dict) -> tuple[tuple[str, int, int], ...]:
    return tuple((group["path"], item["start"], item["end"])
                 for group in data["evidence_locator"] for item in group["ranges"])


def test_policy_cli_and_core_surface(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    assert LOCATOR.delivery_mode == "locator_only"
    assert BenchmarkPolicy().delivery_mode == "one_shot"
    assert BenchmarkPolicy(6000, 12000, 4000).delivery_mode == "progressive"
    with pytest.raises(ValueError, match="conflict"):
        BenchmarkPolicy(6000, 12000, 4000, "locator_only")
    with pytest.raises(ValueError, match="unsupported"):
        BenchmarkPolicy(delivery_policy="unknown")
    args = _server_args(tmp_path, run_id="local", task_id=TASK.id, mode="optimized", policy=LOCATOR)
    assert args[args.index("--benchmark-delivery-policy") + 1] == "locator-only"
    assert "--benchmark-source-delivery-budget" not in args
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner._codex_executable",
                        lambda: (_ for _ in ()).throw(AssertionError("external Codex must not run")))
    main(["codex", "benchmark", "run", TASK.id, "--repo", str(tmp_path), "--dry-run",
          "--benchmark-delivery-policy", "locator-only"])
    output = capsys.readouterr().out
    assert "Delivery policy: locator-only" in output
    assert "--benchmark-delivery-policy locator-only" in output.split("optimized snapshot:")[1]
    assert "--benchmark-delivery-policy" not in output.split("baseline snapshot:")[1].split("optimized snapshot:")[0]
    with pytest.raises(SystemExit, match="conflict"):
        main(["codex", "benchmark", "run", TASK.id, "--repo", str(tmp_path), "--dry-run",
              "--benchmark-delivery-policy", "locator-only", "--benchmark-source-delivery-budget", "4000"])
    tools = asyncio.run(create_server(GatewayConfig(tmp_path), tool_profile="codex-core").list_tools())
    assert len(tools) == 5
    context = next(item for item in tools if item.name == "middleman_context")
    assert "delivery_policy" not in json.dumps(context.input_schema)


def test_actual_and_exact_v4_locator(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    for name, query in {"actual": ACTUAL_QUERY, "exact": TASK.prompt, **STRONG}.items():
        symbols = ["WorkKind", "InferenceRequest"] if name == "actual" else None
        requested = 5500 if name == "actual" else 3000
        canonical = ContextBuilder(config).build(
            ContextQuery(query, symbols=tuple(symbols or ())), mode="balanced", max_context_tokens=6000)
        locator = MCPGateway(config, _identity(LOCATOR))
        data = locator.context(query, mode="safe", max_context_tokens=requested, symbols=symbols)
        assert data["fingerprint"] == canonical.fingerprint
        assert locator._packs[data["fingerprint"]].excerpts == canonical.excerpts
        assert data["metrics"]["selected_tokens"] == canonical.metrics.estimated_selected_tokens
        assert data["excerpts"] == [] and data["source_delivered"] is False
        assert locator.delivery_ledger.line_count == 0
        assert _mapped_ranges(data) == tuple((item.path, item.start_line, item.end_line)
                                              for item in canonical.excerpts)
        assert set(group["path"] for group in data["evidence_locator"]) == set(canonical.selected_files)
        assert not any(key in json.dumps(data["evidence_locator"]) for key in (
            "selected_range_phases", "required_file_recall", "candidate_score", "expected_answer"))
        usage = json.loads((config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        assert not validate_initial_context_budgets((usage,), LOCATOR)
        assert usage["delivery"] == [] and usage["new_lines_delivered"] == 0
        assert usage["budget"]["locator_result_tokens_estimate"] == _result_tokens(data)
        assert usage["budget"]["initial_source_delivery_tokens"] == 0
        mapped = {group["path"] for group in data["evidence_locator"]}
        unit_paths = {unit.path for unit in TASK_A_V3_UNITS}
        label_hits = sum(any(item.get("symbol") == unit.identifier or
                             item.get("symbol", "").endswith("." + unit.identifier)
                             for group in data["evidence_locator"] if group["path"] == unit.path
                             for item in group["ranges"]) for unit in TASK_A_V3_UNITS)
        recall = measure_required_source(canonical)
        controls = {}
        if name in {"actual", "exact"}:
            options = {"max_context_tokens": 6000, "symbols": symbols}
            one = MCPGateway(config, _identity(BenchmarkPolicy())).context(query, **options)
            progressive = MCPGateway(config, _identity(BenchmarkPolicy(6000, 12000, 4000))).context(query, **options)
            assert one["fingerprint"] == progressive["fingerprint"] == data["fingerprint"]
            controls = {"one_shot_tokens": _result_tokens(one), "progressive_tokens": _result_tokens(progressive)}
        print("LOCATOR_V4", json.dumps({"query": name, "fingerprint": canonical.fingerprint,
              "selected_tokens": canonical.metrics.estimated_selected_tokens,
              "paths": list(canonical.selected_files), "ranges": len(canonical.excerpts),
              "locator_paths": len(data["evidence_locator"]), "locator_entries": len(_mapped_ranges(data)),
              "locator_tokens": _result_tokens(data), "required_paths": len(mapped & unit_paths),
              "required_symbols_labeled": label_hits, "required_identifiers_in_selected_source":
              len(TASK_A_V3_UNITS) - len(recall.missing_symbols), **controls}, sort_keys=True))
        if name == "actual":
            assert canonical.metrics.estimated_selected_tokens == 5845
            assert len(canonical.excerpts) == 16 and len(canonical.selected_files) == 13
            assert "middle_man/lab/memory.py" not in mapped


def test_one_shot_progressive_and_overhead(pinned: Path) -> None:
    config = GatewayConfig(pinned)
    options = {"max_context_tokens": 6000, "symbols": ["WorkKind", "InferenceRequest"]}
    one = MCPGateway(config, _identity(BenchmarkPolicy())).context(ACTUAL_QUERY, **options)
    progressive = MCPGateway(config, _identity(BenchmarkPolicy(6000, 12000, 4000))).context(ACTUAL_QUERY, **options)
    locator = MCPGateway(config, _identity(LOCATOR)).context(ACTUAL_QUERY, **options)
    assert one["fingerprint"] == progressive["fingerprint"] == locator["fingerprint"]
    assert one["excerpts"] and progressive["excerpts"] and not locator["excerpts"]
    assert "evidence_map" not in one and "evidence_map" in progressive
    surface = asyncio.run(measure_tool_surface(config, "codex-core"))
    agents = ESTIMATOR.estimate((Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8"))
    instructions = ESTIMATOR.estimate(CORE_INSTRUCTIONS)
    fixed = agents + instructions + surface.total_definition_tokens
    values = {"agents": agents, "instructions": instructions, "five_tools": surface.total_definition_tokens,
              "fixed_total": fixed, "locator": _result_tokens(locator),
              "progressive": _result_tokens(progressive), "one_shot": _result_tokens(one)}
    values.update({f"{key}_plus_fixed": values[key] + fixed for key in ("locator", "progressive", "one_shot")})
    print("LOCATOR_OVERHEAD", json.dumps(values, sort_keys=True))
    assert surface.tool_count == 5 and values["locator"] < values["progressive"] < values["one_shot"]


@pytest.mark.parametrize("case", coverage_cases(), ids=lambda case: case.name)
def test_unrelated_locator_coverage(case: object, tmp_path: Path) -> None:
    for path, source in case.files:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    config = GatewayConfig(tmp_path)
    canonical = ContextBuilder(config).build(case.query, mode="balanced", max_context_tokens=6000)
    data = MCPGateway(config, _identity(LOCATOR)).context(case.query)
    assert data["fingerprint"] == canonical.fingerprint and not data["excerpts"]
    mapped = set(group["path"] for group in data["evidence_locator"])
    index = RepositoryIndexer(config).index()
    represented = sum(any(item.path == symbol.path and item.start_line <= symbol.start_line and
                          item.end_line >= (symbol.end_line or symbol.start_line)
                          for symbol in index.find_symbol(name) for item in canonical.excerpts)
                      for name in case.required_symbols)
    print("LOCATOR_FIXTURE", json.dumps({"case": case.name, "tokens": _result_tokens(data),
          "paths": len(mapped & set(case.required_files)), "symbols_by_range": represented}, sort_keys=True))
    assert set(case.required_files) <= mapped and represented == len(case.required_symbols)


def test_locator_redaction_freshness_and_audit(tmp_path: Path) -> None:
    file = tmp_path / "module.py"
    file.write_text("def alpha():\n    return 'SECRET_SOURCE_SENTINEL'\n", encoding="utf-8")
    gateway = MCPGateway(GatewayConfig(tmp_path), _identity(LOCATOR))
    pack = gateway.builder.build("Inspect module.py alpha", mode="balanced", max_context_tokens=6000)
    annotated = replace(pack, excerpts=tuple(replace(item, reasons=("Bearer fake-token-123456789012",))
                                               for item in pack.excerpts))
    mapped = gateway._locator_payload(annotated).data
    wire = json.dumps(mapped)
    assert "SECRET_SOURCE_SENTINEL" not in wire and "fake-token-123456789012" not in wire
    assert MARKER in wire
    data = gateway.context("Inspect module.py alpha")
    assert gateway.delivery_ledger.line_count == 0
    file.write_text("def alpha():\n    return 'changed'\n", encoding="utf-8")
    with pytest.raises(StaleSourceError):
        gateway.expand_context(data["fingerprint"], "selected_path", target="module.py", core=True)
    entry = json.loads((gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert not validate_initial_context_budgets((entry,), LOCATOR)
    for mutated in ({**entry, "delivery": [{"path": "module.py"}]},
                    {**entry, "new_lines_delivered": 1},
                    {**entry, "budget": {**entry["budget"], "initial_source_delivery_tokens": 1}},
                    {**entry, "budget": {**entry["budget"], "delivery_policy": "one_shot"}},
                    {**entry, "budget": {**entry["budget"], "locator_result_tokens_estimate": -1}}):
        warnings = validate_initial_context_budgets((mutated,), LOCATOR)
        assert warnings and not _infrastructure_valid("optimized", (mutated,), warnings)


def test_locator_server_rejects_source_bearing_payload(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    gateway = MCPGateway(GatewayConfig(tmp_path), _identity(LOCATOR))
    original = gateway._locator_payload

    def unsafe(pack: object) -> object:
        payload = original(pack)
        return replace(payload, data={**payload.data, "excerpts": [{"text": "source leaked"}]})

    monkeypatch.setattr(gateway, "_locator_payload", unsafe)
    with pytest.raises(ValueError, match="source-free evidence locator"):
        gateway.context("Inspect module.py alpha")
    assert gateway.delivery_ledger.line_count == 0
    entry = json.loads((gateway.config.cache_dir / "mcp_usage.jsonl").read_text(encoding="utf-8"))
    assert entry["success"] is False and entry["error_type"] == "ValueError"
    assert "delivery" not in entry


def test_official_locator_stdio_and_selected_path(pinned: Path) -> None:
    config = GatewayConfig(pinned)

    async def exercise() -> tuple[dict, dict, dict]:
        params = StdioServerParameters(command=sys.executable,
                                       args=_server_args(pinned, run_id="local-2211", task_id=TASK.id,
                                                         mode="optimized", policy=LOCATOR), cwd=pinned)
        async with Client(params, raise_exceptions=True, read_timeout_seconds=30) as client:
            first = await client.call_tool("middleman_context", {"task": ACTUAL_QUERY,
                                                                 "max_context_tokens": 5500,
                                                                 "symbols": ["WorkKind", "InferenceRequest"]})
            assert not first.is_error
            data = first.structured_content
            path = data["evidence_locator"][0]["path"]
            args = {"fingerprint": data["fingerprint"], "kind": "selected_path", "target": path,
                    "max_context_tokens": 12000}
            second = await client.call_tool("middleman_expand_context", args)
            third = await client.call_tool("middleman_expand_context", args)
            assert not second.is_error and not third.is_error
            return data, second.structured_content, third.structured_content

    first, second, third = asyncio.run(exercise())
    assert first["excerpts"] == [] and first["evidence_locator"]
    assert second["excerpts"] and third["excerpts"] == []
    entries = tuple(json.loads(line) for line in (config.cache_dir / "mcp_usage.jsonl")
                    .read_text(encoding="utf-8").splitlines()[-3:])
    assert [item["call_sequence"] for item in entries] == [1, 2, 3]
    assert not validate_initial_context_budgets(entries, LOCATOR)
    assert entries[0]["ledger_lines_before"] == entries[0]["ledger_lines_after"] == 0
    assert entries[1]["new_lines_delivered"] > 0 and entries[2]["new_lines_delivered"] == 0
