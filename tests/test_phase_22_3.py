from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from middle_man.gateway.codex_benchmark.preemption_v3 import TASK_A_V3_UNITS, measure_required_source
from middle_man.gateway.codex_benchmark.runner import _server_args, run_one
from middle_man.gateway.codex_benchmark.tasks import (
    TASKS, TASK_A_SOURCE_COMMIT, _write_fixture, prepare_pair, source_fingerprint,
)
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.mcp.benchmark_receipts import BenchmarkIdentity
from middle_man.mcp.gateway import MCPGateway


TASK = next(item for item in TASKS if item.id == "preemption-v3")


@pytest.fixture(scope="module")
def pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    root = tmp_path_factory.mktemp("phase-22-3")
    return prepare_pair(TASK, root / "pair", "Use middleman_context with the concrete engineering request.\n")


def _status(root: Path) -> str:
    return subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1",
                           "--untracked-files=all"], check=True, capture_output=True, text=True).stdout


def _delivered(data: dict) -> tuple[tuple[str, int, int, str], ...]:
    return tuple((item["path"], item["start_line"], item["end_line"], item["text"])
                 for item in data["excerpts"])


def _recall(excerpts: tuple[tuple[str, int, int, str], ...]) -> tuple[int, int]:
    paths = {item[0] for item in excerpts}
    files = sum(unit.path in paths for unit in TASK_A_V3_UNITS)
    symbols = sum(any(path == unit.path and unit.identifier in text
                      for path, _, _, text in excerpts) for unit in TASK_A_V3_UNITS)
    return files, symbols


async def _stdio(root: Path, arguments: dict) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=_server_args(root, run_id="local-parity", task_id=TASK.id, mode="optimized"),
    )
    async with Client(params, raise_exceptions=True, read_timeout_seconds=30) as client:
        result = await client.call_tool("middleman_context", arguments)
        assert not result.is_error
        return result.structured_content


def test_pinned_commit_and_clean_snapshots(pair: tuple[Path, Path, str]) -> None:
    baseline, optimized, fingerprint = pair
    assert TASK.source_ref == TASK_A_SOURCE_COMMIT
    assert subprocess.run(["git", "cat-file", "-t", TASK_A_SOURCE_COMMIT],
                          check=True, capture_output=True, text=True).stdout.strip() == "commit"
    assert _status(baseline) == _status(optimized) == ""
    assert not (baseline / "AGENTS.md").exists()
    assert (optimized / "AGENTS.md").exists()
    assert source_fingerprint(baseline) == source_fingerprint(optimized) == fingerprint
    for root in (baseline, optimized):
        for absent in ("middle_man/gateway/codex_benchmark", "middle_man/mcp",
                       "docs/CODEX_BENCHMARKS.md", "tests/test_phase_22_2.py"):
            assert not (root / absent).exists()
        for unit in TASK_A_V3_UNITS:
            assert unit.identifier in (root / unit.path).read_text(encoding="utf-8")


def test_missing_source_commit_never_falls_back(tmp_path: Path) -> None:
    missing = replace(TASK, source_ref="0" * 40)
    with pytest.raises(ValueError, match="source commit unavailable"):
        prepare_pair(missing, tmp_path / "missing", "guidance")


@pytest.mark.parametrize("mode,kind", [
    ("baseline", "deleted-agents"), ("baseline", "changed-source"), ("baseline", "untracked"),
    ("optimized", "deleted-agents"), ("optimized", "changed-source"), ("optimized", "untracked"),
])
def test_dirty_snapshot_never_launches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                        mode: str, kind: str) -> None:
    baseline, optimized, _ = prepare_pair(TASK, tmp_path / "pair", "Use middleman_context.\n")
    root = baseline if mode == "baseline" else optimized
    if kind == "deleted-agents":
        if mode == "baseline":
            (root / "AGENTS.md").write_text("tracked only in this test\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test",
                            "-c", "user.email=test@example.invalid", "commit", "-qm", "tracked guidance"], check=True)
        (root / "AGENTS.md").unlink()
    elif kind == "changed-source":
        (root / "middle_man/lab/work.py").write_text("changed\n", encoding="utf-8")
    else:
        (root / "stray.txt").write_text("stray\n", encoding="utf-8")
    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner._mcp_preflight",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("MCP preflight was reached with a dirty snapshot")))
    original = subprocess.run

    def spy(command: list[str], *args: object, **kwargs: object):
        if command[0] == "codex" or "exec" in command:
            raise AssertionError("Codex process launcher was reached")
        return original(command, *args, **kwargs)

    monkeypatch.setattr("middle_man.gateway.codex_benchmark.runner.subprocess.run", spy)
    with pytest.raises(RuntimeError, match="not clean"):
        run_one(TASK, mode, root, source_fingerprint(root), order=1, codex_command="codex",
                codex_version="test", model="test", effort="high", timeout=1,
                artifact_root=tmp_path, primary_repository_root=tmp_path, windows_sandbox="unelevated")
    assert _status(root)


def test_direct_gateway_stdio_parity_and_privacy(pair: tuple[Path, Path, str]) -> None:
    _, root, fingerprint = pair
    config = GatewayConfig(root)
    identity = BenchmarkIdentity("local-parity", TASK.id, "optimized", TASK_A_SOURCE_COMMIT)
    pack = ContextBuilder(config).build(TASK.prompt, mode="balanced", max_context_tokens=6000)
    direct = MCPGateway(config, benchmark_identity=identity).context(
        TASK.prompt, mode="balanced", max_context_tokens=6000)
    stdio_default = asyncio.run(_stdio(root, {"task": TASK.prompt}))
    stdio_explicit = asyncio.run(_stdio(root, {
        "task": TASK.prompt, "mode": "balanced", "max_context_tokens": 6000}))
    expected = tuple((item.path, item.start_line, item.end_line, item.text) for item in pack.excerpts)
    assert source_fingerprint(root) == fingerprint
    for result in (direct, stdio_default, stdio_explicit):
        assert result["fingerprint"] == pack.fingerprint
        assert _delivered(result) == expected
        assert tuple(dict.fromkeys(item[0] for item in expected)) == pack.selected_files
        assert result["metrics"]["selected_tokens"] == pack.metrics.estimated_selected_tokens
        assert result["warnings"] == list(pack.warnings)
        assert _recall(_delivered(result)) == (7, 7)
    assert measure_required_source(pack).required_file_recall == 1.0
    assert _status(root) == ""
    receipts = [json.loads(line) for line in
                (root / ".middle_man_cache/benchmark_receipts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(receipts) == 3
    assert all(item["query"]["signature"] and item["selection"]["pack_fingerprint"] == pack.fingerprint
               for item in receipts)
    usage_entries = [json.loads(line) for line in
                     (root / ".middle_man_cache/mcp_usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [item["query"]["signature"] for item in receipts] == [
        item["query_fingerprint"] for item in usage_entries]
    assert TASK.prompt not in json.dumps(receipts)
    assert "text" not in receipts[0]["selection"]["ranges"][0]
    usage = (root / ".middle_man_cache/mcp_usage.jsonl").read_text(encoding="utf-8")
    assert TASK.prompt not in usage
    assert "excerpts" not in usage
    print("PHASE22_3_PARITY", json.dumps({
        "source_fingerprint": fingerprint, "pack_fingerprint": pack.fingerprint,
        "query_signature": receipts[0]["query"]["signature"],
        "selected_paths": pack.selected_files, "ranges": len(expected),
        "selected_tokens": pack.metrics.estimated_selected_tokens,
        "recall": _recall(expected), "warnings": pack.warnings,
    }, sort_keys=True))


def test_benchmark_receipt_redacts_secret_and_normal_log_is_metadata_only(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def investigate(): pass\n", encoding="utf-8")
    secret = "not-a-real-bearer-token-123456789"
    query = "Investigate app.py Bearer " + secret
    identity = BenchmarkIdentity("local-secret", TASK.id, "optimized", "fixture")
    MCPGateway(GatewayConfig(tmp_path), benchmark_identity=identity).context(query)
    receipt = (tmp_path / ".middle_man_cache/benchmark_receipts.jsonl").read_text(encoding="utf-8")
    usage = (tmp_path / ".middle_man_cache/mcp_usage.jsonl").read_text(encoding="utf-8")
    assert secret not in receipt and secret not in usage
    assert query not in receipt and query not in usage
    assert "excerpts" not in receipt
    assert "def investigate" not in receipt
    assert "query_fingerprint" in usage
    normal = tmp_path / "normal"
    normal.mkdir()
    (normal / "app.py").write_text("def investigate(): pass\n", encoding="utf-8")
    MCPGateway(GatewayConfig(normal)).context(query)
    assert not (normal / ".middle_man_cache/benchmark_receipts.jsonl").exists()
    normal_usage = (normal / ".middle_man_cache/mcp_usage.jsonl").read_text(encoding="utf-8")
    assert secret not in normal_usage and query not in normal_usage


def test_query_sensitivity_and_current_head_contamination(
        pair: tuple[Path, Path, str], tmp_path: Path) -> None:
    _, pinned, _ = pair
    head = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    current = tmp_path / "current-head"
    current.mkdir()
    _write_fixture(replace(TASK, source_ref=head), current)
    queries = {
        "exact": TASK.prompt,
        "short": "Find the KV preemption implementation and tests",
        "behavior": "Need context for victim selection, KV release, recomputation, and output preservation",
        "generic": "inspect the Middle_Man architecture",
    }
    results = {}
    for name, query in queries.items():
        pack = ContextBuilder(GatewayConfig(pinned)).build(
            query, mode="balanced", max_context_tokens=6000)
        results[name] = {"recall": _recall(tuple(
            (item.path, item.start_line, item.end_line, item.text) for item in pack.excerpts)),
            "tokens": pack.metrics.estimated_selected_tokens, "paths": pack.selected_files}
    head_pack = ContextBuilder(GatewayConfig(current)).build(
        TASK.prompt, mode="balanced", max_context_tokens=6000)
    top = head_pack.candidates[:20]
    categories = {
        "gateway": sum(item.path.startswith("middle_man/gateway/") for item in top),
        "mcp": sum(item.path.startswith("middle_man/mcp/") for item in top),
        "codex_benchmark": sum("codex_benchmark/" in item.path for item in top),
        "phase22_tests_docs": sum(item.path.startswith("tests/test_phase_22_")
                                  or item.path == "docs/CODEX_BENCHMARKS.md" for item in top),
    }
    assert results["exact"]["recall"] == (7, 7)
    assert categories["gateway"] > 0
    print("PHASE22_3_SENSITIVITY", json.dumps(results, sort_keys=True))
    print("PHASE22_3_HEAD", json.dumps({
        "top20_categories": categories,
        "top20_paths": [item.path for item in top],
        "selected_paths": head_pack.selected_files,
        "recall": _recall(tuple((item.path, item.start_line, item.end_line, item.text)
                               for item in head_pack.excerpts)),
    }, sort_keys=True))


def test_frozen_corpus_22_1_vs_22_2(pair: tuple[Path, Path, str], tmp_path: Path) -> None:
    _, pinned, _ = pair
    old = subprocess.run(["git", "rev-parse", "886a687^{commit}"], check=True,
                         capture_output=True, text=True).stdout.strip()
    implementation = tmp_path / "phase-22-1"
    implementation.mkdir()
    _write_fixture(replace(TASK, source_ref=old), implementation)
    script = (
        "import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]);"
        "from middle_man.gateway.config import GatewayConfig;"
        "from middle_man.gateway.context_builder import ContextBuilder;"
        "p=ContextBuilder(GatewayConfig(Path(sys.argv[2]))).build(sys.argv[3],mode='balanced',max_context_tokens=6000);"
        "print(json.dumps({'paths':p.selected_files,'ranges':[(e.path,e.start_line,e.end_line,e.text) for e in p.excerpts],"
        "'tokens':p.metrics.estimated_selected_tokens}))"
    )
    result = subprocess.run([sys.executable, "-I", "-c", script, str(implementation),
                             str(pinned), TASK.prompt], check=True, capture_output=True, text=True)
    old_pack = json.loads(result.stdout)
    new_pack = ContextBuilder(GatewayConfig(pinned)).build(
        TASK.prompt, mode="balanced", max_context_tokens=6000)
    print("PHASE22_3_SELECTOR_COMPARISON", json.dumps({
        "source_commit": TASK_A_SOURCE_COMMIT,
        "phase_22_1": {"recall": _recall(tuple(old_pack["ranges"])),
                        "tokens": old_pack["tokens"], "files": old_pack["paths"]},
        "phase_22_2": {"recall": _recall(tuple(
            (item.path, item.start_line, item.end_line, item.text) for item in new_pack.excerpts)),
                        "tokens": new_pack.metrics.estimated_selected_tokens,
                        "files": new_pack.selected_files},
    }, sort_keys=True))
    assert old_pack["tokens"] <= 6000
    assert new_pack.metrics.estimated_selected_tokens <= 6000
