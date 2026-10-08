"""Preregistered, one-process native repository read smoke test."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

from middle_man.experiments.codex_pair import ArmObservation, SourcePin, run_arm, verify_snapshot
from middle_man.gateway.codex_runner.infrastructure import CodexCLI


TASK = ("Using native shell execution, calculate the SHA-256 hash of the working-tree file bytes "
        "for README.md, AGENTS.md, and middle_man/gateway/codex_runner/runner.py. Return each "
        "repository-relative path and its lowercase 64-character SHA-256 digest. Do not quote "
        "source text. Do not use MCP, external tools, or GitHub.")
TASK_SHA256 = "2e3be1b58d63d7a95095a54654dad28a61a42d41d4726b287963f415f70b24aa"
SOURCE = SourcePin("db187e0f48f54222dd250502a2e40b7f1fb16401",
                   "c597226461db5975ffafd50a769404e03442fda6",
                   "1a91d487a2629d4c82cbae7072ac873e8fcb516597fe954d53f74b649c4241fa")
AGENTS_BLOB = "0c8baf10e4f781c6b9eaa03c38a24b40d4e1978c"
PATHS = ("README.md", "AGENTS.md", "middle_man/gateway/codex_runner/runner.py")
CLI_VERSION = "codex-cli 0.162.0-alpha.2"
VALIDITY_RULES = (
    "pinned_clean_source_and_tracked_guidance",
    "explicit_unelevated_read_only_isolation",
    "successful_native_hash_command_with_worktree_output_for_all_targets",
    "all_three_lowercase_final_hashes_match_independent_worktree_sha256",
    "zero_mcp_or_unexpected_external_tool_activity",
    "successful_parsed_final_result_and_zero_process_exit",
    "unchanged_head_status_git_visible_content_and_target_hashes",
    "sanitized_receipt_saved_before_console_rendering",
)
_HEX64 = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
_HASH_COMMAND = re.compile(r"(?i)\b(?:Get-FileHash|sha256sum|shasum\s+-a\s+256)\b")


def load_plan(path: Path) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    execution = plan.get("execution", {})
    source = plan.get("source", {})
    if (plan.get("schema_version") != 1 or plan.get("status") != "PREREGISTERED_NO_MODEL_RUN"
            or plan.get("model_processes_authorized_by_this_phase") != 0
            or plan.get("maximum_processes_per_authorized_run") != 1
            or plan.get("task", {}).get("text") != TASK
            or plan["task"].get("utf8_sha256") != TASK_SHA256
            or plan["task"].get("utf8_bytes") != len(TASK.encode("utf-8"))
            or hashlib.sha256(TASK.encode("utf-8")).hexdigest() != TASK_SHA256
            or source != {"commit": SOURCE.commit, "tree": SOURCE.tree,
                          "content_fingerprint": SOURCE.content_fingerprint,
                          "agents_blob": AGENTS_BLOB}
            or execution != {"cli_version": CLI_VERSION, "model": "gpt-6-sol",
                             "effort": "high", "timeout_seconds": 360,
                             "sandbox": "read-only", "windows_backend": "unelevated",
                             "arm": "BASELINE", "apps": "disabled", "plugins": "disabled",
                             "user_config": "ignored", "strict_config": True,
                             "no_daemon": True, "ephemeral": True, "mcp_registered": False}
            or plan.get("validity_rules") != list(VALIDITY_RULES)
            or set(plan.get("expected_worktree_sha256", {})) != set(PATHS)
            or any(not re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in plan["expected_worktree_sha256"].values())):
        raise ValueError("native-read smoke plan differs from locked preregistration")
    return plan


def worktree_hashes(root: Path) -> dict[str, str]:
    root = root.resolve()
    hashes = {}
    for relative in PATHS:
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise RuntimeError("smoke target is not a regular in-root file")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def verify_source(root: Path, expected: dict[str, str]) -> None:
    verify_snapshot(root, SOURCE)
    blob = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD:AGENTS.md"],
                          check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    if blob != AGENTS_BLOB or worktree_hashes(root) != expected:
        raise RuntimeError("smoke snapshot guidance or working-tree hashes differ from pin")


def _path_in(value: str, root: Path, relative: str) -> bool:
    normalized = value.replace("\\", "/").casefold()
    target = re.escape(relative.casefold())
    root_prefix = str(root.resolve()).replace("\\", "/").casefold() + "/"
    for match in re.finditer(r"(?<![\w.])" + target + r"(?![\w./])", normalized):
        prefix = normalized[:match.start()]
        if prefix.endswith(root_prefix):
            return True
        if prefix.endswith("./") and (len(prefix) == 2 or
                                       (not prefix[-3].isalnum() and prefix[-3] not in "_/.")):
            return True
        if not prefix or prefix[-1] not in "/.":
            return True
    return False


def inspect_native_hash_events(raw: str, root: Path, expected: dict[str, str]) -> dict[str, object]:
    completed = successful = 0
    matches: set[str] = set()
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        completed += 1
        command = item.get("command")
        if isinstance(command, list) and all(isinstance(part, str) for part in command):
            command = " ".join(command)
        if not isinstance(command, str) or not _HASH_COMMAND.search(command):
            continue
        if item.get("exit_code") != 0 or item.get("status", "completed") != "completed":
            continue
        output = item.get("aggregated_output")
        if not isinstance(output, str) or len(output) > 100_000:
            continue
        successful += 1
        lines = output.splitlines()
        for relative, digest in expected.items():
            if not _path_in(command, root, relative):
                continue
            for index, output_line in enumerate(lines):
                if not _path_in(output_line, root, relative):
                    continue
                if digest in output_line.casefold() and sum(
                        _path_in(output_line, root, other) for other in PATHS) == 1:
                    matches.add(relative)
                    break
                neighborhood = " ".join(lines[max(0, index - 1):index + 2])
                if digest in neighborhood.casefold() and sum(
                        _path_in(neighborhood, root, other) for other in PATHS) == 1:
                    matches.add(relative)
                    break
    return {"valid": successful > 0 and matches == set(PATHS),
            "completed_native_commands": completed,
            "successful_hash_commands": successful,
            "matched_output_paths": sorted(matches),
            "missing_output_paths": sorted(set(PATHS) - matches)}


def answer_matches(answer: str, root: Path, expected: dict[str, str]) -> dict[str, object]:
    matched = set()
    for relative, digest in expected.items():
        entries = [line for line in answer.splitlines() if _path_in(line, root, relative)]
        if len(entries) != 1:
            continue
        hashes = _HEX64.findall(entries[0])
        if hashes == [digest]:
            matched.add(relative)
    return {"valid": matched == set(PATHS), "matched_answer_paths": sorted(matched),
            "missing_answer_paths": sorted(set(PATHS) - matched)}


def run_smoke(root: Path, plan_path: Path, cli: CodexCLI, *,
              confirm_external_service: bool = False) -> ArmObservation:
    if not confirm_external_service:
        raise ValueError("native-read smoke requires explicit external-service confirmation")
    plan = load_plan(plan_path)
    expected = plan["expected_worktree_sha256"]
    if cli.version != CLI_VERSION:
        raise RuntimeError("Codex CLI differs from native-read smoke pin")
    verify_source(root, expected)
    observation = run_arm(root, TASK, arm="BASELINE", pin=SOURCE, cli=cli,
                          expected_cli_version=CLI_VERSION, windows_sandbox="unelevated",
                          timeout=360, model="gpt-6-sol", effort="high",
                          research_event_inspector=lambda raw, path: inspect_native_hash_events(
                              raw, path, expected))
    evidence = observation.receipt.get("research_evidence") or {}
    final = answer_matches(observation.final_answer, root, expected)
    repository = observation.receipt["repository"]
    try:
        post_hashes_match = worktree_hashes(root) == expected
    except OSError:
        post_hashes_match = False
    passed = (observation.receipt["status"] == "SUCCESS"
              and evidence.get("valid") is True and final["valid"] is True
              and observation.receipt["windows_sandbox"] == "unelevated"
              and repository["unchanged"] is True and post_hashes_match)
    evaluation = {"passed": passed, "native_evidence": evidence, "final_answer": final,
                  "post_run_target_hashes_match": post_hashes_match}
    return replace(observation, receipt={**observation.receipt, "smoke_evaluation": evaluation},
                   final_answer="")
