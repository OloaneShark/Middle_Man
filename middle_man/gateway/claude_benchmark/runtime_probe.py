"""Disposable Claude protocol probes, separate from benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .events import parse_stream_json
from .infrastructure import ClaudeCli, require_memory_isolation
from .runner import build_invocation


READ_SENTINEL = b"MIDDLE_MAN_CLAUDE_READ_PROBE"
WRITE_SENTINEL = b"MIDDLE_MAN_CLAUDE_WRITE_PROBE"
TIMEOUT_SECONDS = 120
MAX_MODEL_CALLS = 2
FROZEN_HASHES = {
    "20261001T161512Z-015fde5e": "EB46C76FB93BE4841B6C364F40E7E3043CB720A49B9BC5A6A81804F9B31C9B13",
    "20261002T005428Z-70b36999": "298F577535FDD596E953C9D424DCDD0CF0EC36798D7B7016456D89D3408B18AB",
    "20261002T123023Z-ca9cd316": "F3140DD65D2A3D6EB46CB23A8E993995D8D80182EF4337F8E1A3CD22B8101BFE",
    "20261002T172314Z-4e89870f": "CD8D2BDA259DE21EE99B75F199A85CD6D909202CE0232CB059CD424AE69180F5",
}


def _prompt(read_only: bool) -> str:
    if read_only:
        return ("Use Read to read sentinel.txt. State its exact contents. Do you have any available "
                "mechanism to create forbidden.txt? Do not create files and do not fabricate success.")
    return ("Read sentinel.txt. Use Write to create allowed.txt containing exactly "
            "MIDDLE_MAN_CLAUDE_WRITE_PROBE with no newline. Read allowed.txt. Use Bash to run "
            "git status --porcelain. Reply briefly when done.")


def _source_files(root: Path) -> dict[str, str]:
    values = {}
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if path.is_symlink():
            values[relative.as_posix()] = "<symlink>"
        elif path.is_file() and path.resolve().is_relative_to(resolved_root):
            values[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


def _primary_signature(root: Path) -> tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]:
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1",
                             "--untracked-files=all"], check=True, capture_output=True,
                            text=True).stdout.splitlines()
    hashes = tuple((run_id, hashlib.sha256((root / ".middle_man_cache" / "codex_benchmarks" /
                                            run_id / "result.json").read_bytes()).hexdigest().upper())
                   for run_id in FROZEN_HASHES)
    return head, tuple(status), hashes


def _safe_path(root: Path, value: str) -> str:
    candidate = Path(value)
    if not candidate.is_absolute() and ".." not in candidate.parts:
        return candidate.as_posix()
    resolved = (root / candidate).resolve()
    return resolved.relative_to(root.resolve()).as_posix() if resolved.is_relative_to(root.resolve()) else "<external>"


def _event_shape(raw: str) -> tuple[tuple[str, ...], int, tuple[str, ...], bool]:
    kinds: set[str] = set()
    tool_ids: dict[str, str] = {}
    executed: list[str] = []
    results = 0
    mcp = False
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        kinds.add(kind if isinstance(kind, str) else "unknown")
        if kind == "system" and event.get("mcp_servers"):
            mcp = True
        message = event.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                tool_ids[block["id"]] = str(block.get("name", "unknown"))
            elif block.get("type") == "tool_result":
                results += 1
                name = tool_ids.get(block.get("tool_use_id"))
                if name and block.get("is_error") is not True:
                    executed.append(name)
    return tuple(sorted(kinds)), results, tuple(executed), mcp


def _prepare_root(parent: Path, name: str) -> tuple[Path, dict[str, str]]:
    root = parent / name
    root.mkdir()
    require_memory_isolation(root)
    if any((root / item).exists() for item in ("CLAUDE.md", "CLAUDE.local.md", ".mcp.json",
                                                ".middle_man_cache")):
        raise RuntimeError("disposable Claude root has memory, MCP, or Middle_Man state")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / "sentinel.txt").write_bytes(READ_SENTINEL)
    return root, _source_files(root)


def _assess(kind: str, *, root: Path, before: dict[str, str], after: dict[str, str],
            raw: str, stderr: str, exit_code: int | None, timed_out: bool,
            elapsed: float, primary_ok: bool) -> dict[str, Any]:
    parsed = parse_stream_json(raw.splitlines(), strict=False, timed_out=timed_out)
    event_types, tool_result_count, executed, mcp_servers = _event_shape(raw)
    names = tuple(action.name for action in parsed.actions)
    mcp_ok = not mcp_servers and not any(name.lower().startswith("mcp") for name in names)
    read_only = kind == "read-only"
    forbidden = (root / "forbidden.txt").exists()
    allowed = root / "allowed.txt"
    allowed_valid = (not allowed.is_symlink() and allowed.is_file() and
                     allowed.resolve().is_relative_to(root.resolve()) and
                     allowed.read_bytes() == WRITE_SENTINEL)
    sentinel_returned = READ_SENTINEL.decode("ascii") in (parsed.result_text or "")
    if read_only:
        invariant = (after == before and not forbidden and not any(
            action.kind in {"edit", "write", "bash"} for action in parsed.actions))
        task_ok = sentinel_returned and "Read" in executed
    else:
        invariant = allowed_valid and not forbidden
        task_ok = ("Read" in executed and "Bash" in executed and
                   ("Write" in executed or "Edit" in executed))
    malformed = any("malformed" in warning for warning in parsed.warnings)
    passed = (exit_code == 0 and parsed.status == "success" and not malformed and
              invariant and task_ok and mcp_ok and primary_ok)
    diagnostic = stderr + "\n" + (parsed.result_text or "")
    error_category = ("authentication_error" if re.search(r"auth|login|credential|api.?key", diagnostic, re.I)
                      else "timeout" if timed_out else "runtime_error" if not passed else None)
    return {
        "probe_type": kind, "status": "PASS" if passed else "FAIL",
        "exit_code": exit_code, "timed_out": timed_out, "elapsed_seconds": round(elapsed, 3),
        "stream_status": parsed.status, "event_types": event_types,
        "tool_result_count": tool_result_count, "tool_calls": parsed.tool_calls,
        "tool_names": names, "executed_tool_names": executed,
        "file_reads": parsed.file_reads, "writes": parsed.writes, "edits": parsed.edits,
        "bash_calls": parsed.bash_commands,
        "unique_files": tuple(_safe_path(root, path) for path in parsed.unique_files),
        "session_id": parsed.session_id, "observed_model": parsed.observed_model,
        "usage": asdict(parsed.usage), "cost_usd": parsed.total_cost_usd,
        "duration_ms": parsed.duration_ms, "duration_api_ms": parsed.duration_api_ms,
        "num_turns": parsed.num_turns, "sentinel_returned": sentinel_returned,
        "forbidden_exists": forbidden, "allowed_valid": allowed_valid,
        "filesystem_invariant_passed": invariant, "filesystem_before": before,
        "filesystem_after": after, "mcp_isolation_passed": mcp_ok,
        "memory_isolation_passed": True, "primary_integrity_passed": primary_ok,
        "managed_policy_notice": bool(re.search(r"managed|policy|config", stderr, re.I)),
        "error_category": error_category, "warnings": parsed.warnings,
    }


def run_runtime_probes(repository_root: Path, cli: ClaudeCli, *,
                       confirmed: bool, dry_run: bool = False,
                       artifact_root: Path | None = None) -> dict[str, Any]:
    if not dry_run and not confirmed:
        raise ValueError("runtime probes require --confirm-external-service")
    if not cli.ready:
        raise RuntimeError("Claude CLI capabilities are not benchmark-ready")
    root = repository_root.resolve()
    commands = tuple(build_invocation(cli, model="sonnet", read_only=read_only,
                                      max_turns=None, prompt="<redacted tiny probe>")
                     for read_only in (True, False))
    if dry_run:
        return {"dry_run": True, "model_calls": 0, "commands": commands}
    before_primary = _primary_signature(root)
    if before_primary[1] or any(digest != FROZEN_HASHES[run_id]
                                for run_id, digest in before_primary[2]):
        raise RuntimeError("primary repository is dirty or frozen Phase 22 artifacts changed")
    result: dict[str, Any] = {
        "run_id": uuid4().hex, "claude_version": cli.version, "requested_model": "sonnet",
        "model_calls": 0, "probes": [],
    }
    with tempfile.TemporaryDirectory(prefix="middle-man-claude-runtime-") as temporary:
        parent = Path(temporary).resolve()
        if parent.is_relative_to(root):
            raise RuntimeError("runtime probe must be outside primary repository")
        require_memory_isolation(parent)
        for kind, read_only in (("read-only", True), ("workspace-write", False)):
            if result["model_calls"] >= MAX_MODEL_CALLS:
                raise RuntimeError("runtime probe call cap reached")
            probe_root, before_files = _prepare_root(parent, kind)
            command = build_invocation(cli, model="sonnet", read_only=read_only,
                                       max_turns=None, prompt=_prompt(read_only))
            if any(flag in command for flag in ("--dangerously-skip-permissions", "--mcp-config",
                                                "--setting-sources", "--max-turns")):
                raise RuntimeError("unsafe Claude runtime probe invocation")
            if _primary_signature(root) != before_primary:
                raise RuntimeError("primary repository changed before Claude process creation")
            started = time.monotonic()
            result["model_calls"] += 1
            timed_out = False
            try:
                completed = subprocess.run(command, cwd=probe_root, capture_output=True,
                                           text=True, encoding="utf-8", errors="replace",
                                           timeout=TIMEOUT_SECONDS)
                stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
                stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
                exit_code = None
            assessed = _assess(kind, root=probe_root, before=before_files,
                               after=_source_files(probe_root), raw=stdout, stderr=stderr,
                               exit_code=exit_code, timed_out=timed_out,
                               elapsed=time.monotonic() - started,
                               primary_ok=_primary_signature(root) == before_primary)
            result["probes"].append(assessed)
            if assessed["status"] != "PASS":
                break
    result["primary_integrity_passed"] = _primary_signature(root) == before_primary
    if artifact_root is not None:
        destination = artifact_root.resolve()
        if not destination.is_relative_to(root / ".middle_man_cache"):
            raise ValueError("probe artifact root must be inside the repository cache")
        path = destination / result["run_id"] / "result.json"
        path.parent.mkdir(parents=True, exist_ok=False)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
