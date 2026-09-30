"""Small, non-inference checks before real Codex benchmark runs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import contextmanager

import platform
import shutil
import subprocess
import tempfile
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from middle_man.gateway.secrets import SecretRedactor

WINDOWS_SANDBOX = "elevated"


@dataclass(frozen=True, slots=True)
class CodexInfrastructurePreflight:
    codex_version: str | None
    sandbox_platform: str
    sandbox_mode: str
    snapshot_root_kind: str
    fixture_path_has_spaces_and_apostrophe: bool
    baseline_isolated_by_invocation: bool
    optimized_mcp_root_verified: bool
    read_exit_code: int | None
    read_succeeded: bool
    readonly_write_blocked: bool
    write_exit_code: int | None
    write_succeeded: bool
    model_effort_event_verified: bool
    passed: bool
    errors: tuple[str, ...]
    primary_repo_usage_unchanged: bool = False


def primary_usage_signature(repository_root: Path) -> tuple[int, str] | None:
    path = repository_root / ".middle_man_cache" / "mcp_usage.jsonl"
    if not path.exists():
        return None
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


@contextmanager
def _disposable_root(parent: Path) -> Iterator[Path]:
    root = parent / f"middle-man benchmark copy O'Loane {uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        resolved = root.resolve()
        if not resolved.is_relative_to(parent.resolve()) or not root.name.startswith("middle-man benchmark copy "):
            raise RuntimeError("unsafe preflight cleanup target")
        shutil.rmtree(root)

def _probe(command: str, root: Path, permission: str, script: str,
           windows_sandbox: str = WINDOWS_SANDBOX) -> subprocess.CompletedProcess[str]:
    shell = shutil.which("powershell.exe") or shutil.which("powershell")
    if shell is None:
        raise RuntimeError("PowerShell is unavailable for native Windows sandbox preflight")
    return subprocess.run(
        [command, "-c", f'windows.sandbox="{windows_sandbox}"', "sandbox", "-P", permission,
         "-C", str(root), shell, "-NoProfile", "-Command", script],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
    )


def _marker_scripts(root: Path) -> tuple[str, str, str]:
    resolved_root = root.resolve()
    marker = (resolved_root / "marker.txt").resolve()
    if not marker.is_relative_to(resolved_root):
        raise ValueError("preflight marker must stay inside the disposable root")
    literal = "'" + str(marker).replace("'", "''") + "'"
    return (f"Get-Content -LiteralPath {literal}",
            f"Set-Content -LiteralPath {literal} -Value 'forbidden' -ErrorAction Stop",
            f"Set-Content -LiteralPath {literal} -Value 'written' -ErrorAction Stop")


async def _snapshot_mcp_call(root: Path) -> bool:
    from mcp import Client, StdioServerParameters

    from middle_man.gateway.codex_benchmark.runner import _server_args

    params = StdioServerParameters(command=str(Path(sys.executable).resolve()),
                                   args=_server_args(root), cwd=root)
    async with Client(params, raise_exceptions=True, read_timeout_seconds=15) as client:
        response = await client.call_tool("middleman_project_state", {})
        return not response.is_error

def run_local_preflight(command: str, *, model: str, effort: str,
                        windows_sandbox: str = WINDOWS_SANDBOX,
                        snapshot_root: Path | None = None,
                        repository_root: Path | None = None) -> CodexInfrastructurePreflight:
    from middle_man.gateway.codex_benchmark.runner import _codex_version, _mcp_preflight, build_invocation
    from middle_man.gateway.codex_benchmark.tasks import TASKS

    errors: list[str] = []
    if windows_sandbox not in {"elevated", "unelevated"}:
        raise ValueError("unsupported Windows sandbox implementation")
    version = None
    read_exit = write_exit = None
    read_ok = readonly_blocked = write_ok = root_ok = baseline_ok = False
    primary_unchanged = repository_root is not None
    primary_before = primary_usage_signature(repository_root) if repository_root is not None else None
    if platform.system() != "Windows":
        return CodexInfrastructurePreflight(None, platform.system(), windows_sandbox, "system-temp", False,
                                            False, False, None, False, False, None, False, False, False,
                                            ("native Windows preflight requires Windows",))
    try:
        version = _codex_version(command)
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"Codex version unavailable: {type(exc).__name__}")
    parent = snapshot_root.resolve() if snapshot_root is not None else Path(tempfile.gettempdir()).resolve()
    if not parent.is_dir():
        raise ValueError("snapshot root must be an existing directory")
    if any((ancestor / "AGENTS.md").exists() for ancestor in (parent, *parent.parents)):
        raise ValueError("snapshot root inherits AGENTS.md and would contaminate baseline")
    kind = "configured-external" if snapshot_root is not None else "system-temp"
    with _disposable_root(parent) as root:
        # The runner uses Path.mkdir; tempfile.TemporaryDirectory can create a different Windows ACL.

        root = root.resolve()
        path_ok = " " in str(root) and "'" in str(root)
        marker = root / "marker.txt"
        read_script, readonly_script, write_script = _marker_scripts(root)
        marker.write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], capture_output=True, check=True)
        baseline = build_invocation(command, TASKS[0], "baseline", root, model=model, effort=effort, windows_sandbox=windows_sandbox)
        optimized = build_invocation(command, TASKS[0], "optimized", root, model=model, effort=effort, windows_sandbox=windows_sandbox)
        baseline_ok = ("--ignore-user-config" in baseline and "--ignore-user-config" in optimized and
                       not any("mcp_servers." in part for part in baseline) and
                       f'windows.sandbox="{windows_sandbox}"' in baseline and
                       f'windows.sandbox="{windows_sandbox}"' in optimized and
                       "danger-full-access" not in baseline and "danger-full-access" not in optimized)
        if not baseline_ok:
            errors.append("baseline invocation is not isolated or sandboxed")
        try:
            _mcp_preflight(command, "optimized", root)
            response_ok = asyncio.run(_snapshot_mcp_call(root))
            snapshot_log = root / ".middle_man_cache" / "mcp_usage.jsonl"
            primary_unchanged = repository_root is not None and primary_before == primary_usage_signature(repository_root)
            from middle_man.mcp.usage import server_implementation_identity

            records = [json.loads(line) for line in snapshot_log.read_text(encoding="utf-8").splitlines()] if snapshot_log.is_file() else []
            root_ok = (response_ok and bool(records) and primary_unchanged and
                       all(item.get("server_implementation") == server_implementation_identity()
                           for item in records))
            if not root_ok:
                errors.append("snapshot MCP call did not produce an isolated snapshot-local usage record")
        except Exception as exc:
            errors.append(f"optimized MCP override check failed: {type(exc).__name__}: {exc}")
        try:
            read = _probe(command, root, ":read-only", read_script, windows_sandbox)
            read_exit = read.returncode
            read_ok = read.returncode == 0 and "original" in read.stdout and marker.read_text(encoding="utf-8") == "original\n"
            if not read_ok:
                errors.append("sandbox read failed: " + SecretRedactor().redact(read.stderr[-500:]).text)
            readonly = _probe(command, root, ":read-only", readonly_script, windows_sandbox)
            readonly_blocked = read_ok and readonly.returncode != 0 and marker.read_text(encoding="utf-8") == "original\n"
            if not readonly_blocked:
                errors.append("read-only sandbox did not prove mutation was blocked")
            write = _probe(command, root, ":workspace", write_script, windows_sandbox)
            write_exit = write.returncode
            write_ok = write.returncode == 0 and marker.read_text(encoding="utf-8").strip() == "written"
            if not write_ok:
                errors.append("workspace-write sandbox failed: " + SecretRedactor().redact(write.stderr[-500:]).text)
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            errors.append(f"sandbox probe failed: {type(exc).__name__}: {exc}")
        passed = bool(version and path_ok and baseline_ok and root_ok and read_ok and readonly_blocked and write_ok)
        return CodexInfrastructurePreflight(version, "native-windows", windows_sandbox, kind,
                                            path_ok, baseline_ok, root_ok, read_exit, read_ok, readonly_blocked,
                                            write_exit, write_ok, False, passed, tuple(errors), primary_unchanged)
