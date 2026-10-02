"""Local-only edit-task offline locator coverage and reporting."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator, build_offline_locator
from middle_man.gateway.codex_benchmark.runner import (
    OFFLINE_LOCATOR_TASK_IDS, build_invocation, classify_native_locator_reads, format_report, snapshot_root_kind,
)
from middle_man.gateway.codex_benchmark.tasks import TASKS, prepare_pair, source_fingerprint
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery


CASES = (
    ("oauth-bug",
     {"app/auth.py", "app/state.py", "app/config.py", "tests/test_auth.py"},
     {"AuthService.callback", "StateStore.consume", "CLOCK_SKEW_SECONDS", "AuthTests.test_expired_callback"},
     "a5a4c58aaeea51731fa92657e425c30c01e1556da6bb53e311ca70964ce3bcfb"),
    ("upload-feature",
     {"app/uploads.py", "app/rules.py", "app/config.py", "tests/test_uploads.py"},
     {"UploadService.upload", "validate_size", "UploadConfig", "UploadTests.test_size_and_duplicate"},
     "68f9dda25f5752c6ab894374e91e7820081dcda631c1c82c8b1086fe5e0680ad"),
)


@pytest.mark.parametrize("task_id,required_paths,required_symbols,acceptance_hash", CASES)
def test_edit_fixture_offline_locator(task_id: str, required_paths: set[str],
                                      required_symbols: set[str], acceptance_hash: str,
                                      tmp_path: Path) -> None:
    task = next(item for item in TASKS if item.id == task_id)
    assert task.id in OFFLINE_LOCATOR_TASK_IDS and not task.read_only
    assert hashlib.sha256(task.acceptance_test.encode()).hexdigest() == acceptance_hash
    baseline_root, optimized_root, fingerprint = prepare_pair(task, tmp_path / task_id, None)
    assert source_fingerprint(baseline_root) == source_fingerprint(optimized_root) == fingerprint
    for root in (baseline_root, optimized_root):
        assert not (root / "AGENTS.md").exists()
        assert not (root / ".middle_man_cache" / "mcp_usage.jsonl").exists()
        assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain=v1"]).strip()

    config = GatewayConfig(optimized_root)
    query = ContextQuery(task.prompt)
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    locator = build_offline_locator(config, query)
    assert locator == build_offline_locator(config, query)
    assert locator.pack_fingerprint == pack.fingerprint
    assert locator.selected_source_tokens == pack.metrics.estimated_selected_tokens
    assert locator.selected_ranges == tuple((item.path, item.start_line, item.end_line) for item in pack.excerpts)
    assert required_paths <= set(locator.selected_paths)
    index = RepositoryIndexer(config).index()
    for name in required_symbols:
        matches = index.find_symbol(name)
        assert matches, name
        assert any(item.path == match.path and item.start_line <= match.start_line and
                   item.end_line >= (match.end_line or match.start_line)
                   for match in matches for item in pack.excerpts), name
    assert locator.estimated_tokens < 100
    assert "test_middleman_benchmark_acceptance" not in locator.text
    assert "assert" not in locator.text and "return " not in locator.text
    assert "pack_fingerprint" not in locator.text and "candidate_score" not in locator.text
    assert not any(line for line in locator.text.splitlines() if not line.startswith("- "))

    baseline = build_invocation("codex", task, "baseline", baseline_root, model="gpt-6-sol",
                                effort="high", windows_sandbox="unelevated", optimized_mode="offline-locator")
    optimized = build_invocation("codex", task, "optimized", optimized_root, model="gpt-6-sol",
                                 effort="high", windows_sandbox="unelevated", optimized_mode="offline-locator",
                                 locator_text=locator.text)
    original = task.prompt + " Work only inside this benchmark working copy. Do not commit or push."
    assert baseline[-1] == original
    assert optimized[-1] == append_offline_locator(original, locator.text)
    for command in (baseline, optimized):
        assert command[command.index("-s") + 1] == "workspace-write"
        assert "--ignore-user-config" in command and "--no-daemon" in command
        assert not any("mcp_servers." in part or "AGENTS.md" in part for part in command)
    print("EDIT_OFFLINE_PROOF", json.dumps({
        "task": task_id, "source_tokens": locator.selected_source_tokens,
        "locator_tokens": locator.estimated_tokens, "locator": locator.text,
        "paths": locator.selected_paths, "ranges": locator.selected_ranges,
        "required_paths": sorted(required_paths), "required_symbols": sorted(required_symbols),
    }, sort_keys=True))


def test_offline_task_allowlist_and_locator_read_classification(tmp_path: Path) -> None:
    assert OFFLINE_LOCATOR_TASK_IDS == {"preemption-v4", "oauth-bug", "upload-feature", "large-edit-v1"}
    assert snapshot_root_kind(None) == "system-temp"
    assert snapshot_root_kind(tmp_path) == "external-configured"
    events = (
        {"explicit_read_paths": ["app/auth.py", "app/other.py"]},
        {"explicit_read_paths": ["app/auth.py"]},
    )
    assert classify_native_locator_reads(events, ("app/auth.py",)) == (
        ("app/auth.py", "LOCATOR_PATH"),
        ("app/other.py", "NON_LOCATOR_PATH"),
        ("app/auth.py", "LOCATOR_PATH"),
    )
    for task_id in ("preemption", "preemption-v2", "preemption-v3"):
        task = next(item for item in TASKS if item.id == task_id)
        with pytest.raises(ValueError, match="not supported"):
            build_invocation("codex", task, "baseline", tmp_path, model="gpt-6-sol",
                             effort="high", optimized_mode="offline-locator")


def test_offline_report_labels_local_preprocessing_not_mcp() -> None:
    native = {"tool_calls": 2, "file_reads": 2, "unique_files": ["app/auth.py", "app/other.py"],
              "rereads": 0, "search_calls": 0, "listing_calls": 0}
    context = {"pack_fingerprints": [], "selected_paths": [], "candidate_tokens": 0,
               "selected_tokens": 0, "unique_source_tokens_estimate": 0,
               "repeated_source_tokens_estimate": 0, "all_mcp_result_tokens": 0,
               "non_source_pack_overhead_estimate": 0, "overlap_ratio": None,
               "overlap_available": True, "unique_source_bytes": 0, "repeated_source_bytes": 0}
    run = {"correctness": True, "native": native, "context": context,
           "mcp_calls_by_tool": [], "mcp_session_trace": [], "native_read_mcp_coverage": [],
           "codex_reported_usage": {"input_tokens": 100, "cached_input_tokens": 40,
                                    "output_tokens": 5, "reasoning_output_tokens": 0,
                                    "total_tokens": None},
           "elapsed_seconds": 1.0, "modified_files": [], "correctness_notes": [],
           "snapshot_root_kind": "external-configured", "test_exit_code": 0}
    baseline = {**run, "offline_locator_audit": None}
    optimized = {**run, "offline_locator_audit": {
        "locator_estimated_tokens": 20, "canonical_selected_source_tokens": 200,
        "locator_sha256": "abc", "selected_paths": ["app/auth.py"],
    }, "native_read_locator_coverage": [
        ["app/auth.py", "LOCATOR_PATH"], ["app/other.py", "NON_LOCATOR_PATH"],
    ]}
    pair = {"title": "OAuth", "valid": True, "quality_gate": "CORRECT", "task_version": 1,
            "baseline": baseline, "optimized": optimized}
    report = format_report({"run_id": "local", "codex_version": "test", "model": "test",
                            "effort": "high", "optimized_mode": "offline-locator", "pairs": [pair]})
    assert "Local preprocessing - offline locator" in report
    assert "Native locator reads: 1/1 paths accessed; non-locator paths: 1" in report
    assert "Snapshot root kind: baseline=external-configured optimized=external-configured" in report
    assert "Context Packs/expansions" not in report
    assert "MCP session trace:" not in report
    assert "Estimated MCP result" not in report
    assert "Aggregate optimized MCP calls/packs" not in report
    historical = {**pair, "optimized": {key: value for key, value in optimized.items()
                                        if key != "native_read_locator_coverage"}}
    old_report = format_report({"run_id": "old", "codex_version": "test", "model": "test",
                                "effort": "high", "optimized_mode": "offline-locator",
                                "pairs": [historical]})
    assert "not recorded in this historical artifact" in old_report
    assert "Native locator reads: 0/" not in old_report
    assert "Snapshot root kind: historical artifact metadata not revalidated" in old_report
