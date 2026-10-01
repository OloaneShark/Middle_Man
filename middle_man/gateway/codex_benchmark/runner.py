"""Isolated, correctness-first real Codex A/B benchmark runner."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from middle_man.gateway.codex_benchmark.events import CodexUsage, NativeExploration, parse_codex_events
from middle_man.gateway.codex_benchmark.infrastructure import WINDOWS_SANDBOX, primary_usage_signature
from middle_man.gateway.codex_benchmark.overlap import ContextDelivery, measure_delivery
from middle_man.gateway.codex_benchmark.preemption_v3 import evaluate_preemption_v3
from middle_man.gateway.codex_benchmark.preemption_v4 import evaluate_preemption_v4
from middle_man.gateway.codex_benchmark.tasks import TASKS, TaskSpec, add_acceptance_tests, prepare_pair, source_fingerprint
from middle_man.gateway.secrets import SecretRedactor
from middle_man.mcp.benchmark_receipts import BenchmarkPolicy
from middle_man.mcp.usage import server_implementation_identity

DEFAULT_MODEL = "gpt-6-sol"
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = 360


@dataclass(frozen=True, slots=True)
class CodexBenchmarkRun:
    task_id: str
    mode: str
    order: int
    codex_version: str
    model: str
    effort: str
    model_verification: str
    starting_fingerprint: str
    starting_head: str
    timestamp_utc: str
    exit_code: int | None
    elapsed_seconds: float
    correctness: bool
    correctness_notes: tuple[str, ...]
    git_before: tuple[str, ...]
    git_after_codex: tuple[str, ...]
    modified_files: tuple[str, ...]
    test_exit_code: int | None
    test_output: str | None
    native: NativeExploration
    mcp_calls_by_tool: tuple[tuple[str, int], ...]
    mcp_calls_in_events: int
    context: ContextDelivery
    codex_reported_usage: CodexUsage
    thread_id: str | None
    final_message: str
    event_count: int
    warnings: tuple[str, ...]
    valid: bool
    sandbox_platform: str = "native-windows"
    sandbox_mode: str = WINDOWS_SANDBOX
    snapshot_root_kind: str = "system-temp"
    mcp_root_verified: bool = False
    primary_repo_usage_unchanged: bool = False
    preflight_passed: bool = False
    task_version: int = 1
    evaluator_version: int = 1
    tool_profile: str = "none"
    source_commit: str | None = None
    source_tree_fingerprint: str | None = None
    benchmark_run_id: str | None = None
    server_session_ids: tuple[str, ...] = ()
    mcp_session_trace: tuple[tuple[int | None, str, str | None], ...] = ()
    native_read_mcp_coverage: tuple[tuple[str, str], ...] = ()


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]


@dataclass(frozen=True, slots=True)
class CodexBenchmarkPair:
    task_id: str
    title: str
    source_fingerprint: str
    baseline: CodexBenchmarkRun
    optimized: CodexBenchmarkRun
    valid: bool
    quality_gate: str
    task_version: int = 1
    source_commit: str | None = None
    source_tree_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class CodexBenchmarkSuite:
    run_id: str
    created_at_utc: str
    codex_version: str
    model: str
    effort: str
    pairs: tuple[CodexBenchmarkPair, ...]
    artifact_root: str
    planned_task_ids: tuple[str, ...]
    aborted_reason: str | None = None


def _codex_executable() -> str:
    command = shutil.which("codex")
    if command is None:
        raise RuntimeError("Codex CLI is not on PATH")
    return command


def _codex_version(command: str) -> str:
    return subprocess.run([command, "--version"], capture_output=True, text=True, check=True).stdout.strip()


def _server_args(root: Path, *, run_id: str = "", task_id: str = "", mode: str = "") -> list[str]:
    source_root = Path(__file__).resolve().parents[3]
    launcher = ("import sys;sys.path.insert(0,sys.argv.pop(1));"
                "from middle_man.cli.main import main;main()")
    args = ["-I", "-c", launcher, str(source_root), "mcp", "serve", "--repo", str(root.resolve())]
    if run_id and task_id and mode:
        task = next(item for item in TASKS if item.id == task_id)
        args.extend(["--benchmark-run-id", run_id, "--benchmark-task-id", task_id,
                     "--benchmark-mode", mode, "--benchmark-source-commit", task.source_ref or "fixture",
                     "--benchmark-context-budget", str(BenchmarkPolicy().initial_context_budget),
                     "--benchmark-expansion-budget", str(BenchmarkPolicy().expansion_ceiling)])
    return [*args, "--tool-profile", "codex-core"]


def _overrides(mode: str, root: Path, *, run_id: str = "", task_id: str = "") -> list[str]:
    settings = []
    if mode == "optimized":
        settings = ["mcp_servers.middle-man.command=" + json.dumps(str(Path(sys.executable).resolve())),
                    "mcp_servers.middle-man.args=" + json.dumps(_server_args(
                        root, run_id=run_id, task_id=task_id, mode=mode)),
                    "mcp_servers.middle-man.enabled=true", "mcp_servers.middle-man.required=true"]
    return [part for setting in settings for part in ("-c", setting)]

def build_invocation(command: str, task: TaskSpec, mode: str, root: Path, *, model: str,
                     effort: str, windows_sandbox: str = WINDOWS_SANDBOX,
                     run_id: str = "") -> list[str]:
    if mode not in {"baseline", "optimized"}:
        raise ValueError("unknown benchmark mode")
    if windows_sandbox not in {"elevated", "unelevated"}:
        raise ValueError("unsupported Windows sandbox implementation")
    sandbox = "read-only" if task.read_only else "workspace-write"
    return [command, "--no-daemon", "-a", "never", "exec", "--ignore-user-config", "--strict-config",
            "-c", f'windows.sandbox="{windows_sandbox}"',
            *_overrides(mode, root, run_id=run_id, task_id=task.id), "-C", str(root.resolve()),
            "-s", sandbox, "--ephemeral", "--json", "-m", model,
            "-c", f'model_reasoning_effort="{effort}"',
            *(["--output-schema", str(Path(__file__).with_name(
                "preemption_v4.schema.json" if task.schema_version == 4 else "preemption_v2.schema.json").resolve())]
              if task.schema_version >= 2 else []),
            task.prompt + " Work only inside this benchmark working copy. Do not commit or push."]


def _mcp_preflight(command: str, mode: str, root: Path, *, run_id: str = "", task_id: str = "") -> None:
    if mode == "baseline":
        return
    result = subprocess.run([command, *_overrides(mode, root, run_id=run_id, task_id=task_id),
                             "mcp", "get", "middle-man", "--json"],
                            capture_output=True, text=True, check=True)
    config = json.loads(result.stdout)
    if not config["enabled"]:
        raise RuntimeError("optimized Middle_Man MCP server is disabled")
    if config["transport"]["args"][config["transport"]["args"].index("--repo") + 1] != str(root.resolve()):
        raise RuntimeError("optimized MCP server is not scoped to its benchmark snapshot")
    if config["transport"]["args"] != _server_args(root, run_id=run_id, task_id=task_id, mode=mode):
        raise RuntimeError("optimized MCP arguments do not pin the current implementation and codex-core profile")
    if Path(config["transport"]["command"]).resolve() != Path(sys.executable).resolve():
        raise RuntimeError("optimized MCP command differs from the benchmark Python environment")

def _status(root: Path) -> tuple[str, ...]:
    result = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                            capture_output=True, text=True, check=True)
    return tuple(result.stdout.splitlines())


def _head(root: Path) -> str:
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _usage_entries(root: Path) -> tuple[dict[str, Any], ...]:
    path = root / ".middle_man_cache" / "mcp_usage.jsonl"
    if not path.exists():
        return ()
    return tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def isolation_warnings(mode: str, entries: tuple[dict[str, Any], ...],
                       mcp_calls: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    middleman_calls = sum(server == "middle-man" for server, _ in mcp_calls)
    warnings = []
    if mode == "baseline" and (entries or mcp_calls):
        warnings.append("baseline contaminated by an MCP call")
    if mode == "optimized" and not entries:
        warnings.append("optimized run made no snapshot-scoped Middle_Man MCP calls")
    if mode == "optimized" and middleman_calls and not entries:
        warnings.append("Middle_Man calls lacked snapshot usage records; server may target another repository")
    if len(entries) != middleman_calls:
        warnings.append("MCP event and usage-log call counts differ")
    return tuple(warnings)


def validate_initial_context_budgets(entries: tuple[dict[str, Any], ...], cap: int) -> tuple[str, ...]:
    warnings = []
    for entry in entries:
        if entry.get("tool") != "middleman_context" or not entry.get("success"):
            continue
        budget = entry.get("budget")
        effective = budget.get("effective_context_tokens") if isinstance(budget, dict) else None
        recorded_cap = budget.get("benchmark_context_cap") if isinstance(budget, dict) else None
        if (type(effective) is not int or type(recorded_cap) is not int or
                recorded_cap != cap or not 1 <= effective <= cap):
            warnings.append("optimized initial context budget invalid or unverified")
        if isinstance(budget, dict) and budget.get("force_replay") is True:
            warnings.append("optimized model-facing context replay violates benchmark policy")
    return tuple(warnings)


def _infrastructure_valid(mode: str, entries: tuple[dict[str, Any], ...],
                          warnings: tuple[str, ...] | list[str]) -> bool:
    return not (mode == "optimized" and not entries) and not any(
        "contaminated" in item or "no Middle_Man" in item or "call counts differ" in item or
        "differs from configured" in item or "implementation identity differs" in item or
        "initial context budget invalid" in item or "model-facing context replay" in item or
        "primary repository MCP usage log changed" in item
        for item in warnings)


def classify_native_read_coverage(root: Path, paths: tuple[str, ...],
                                  entries: tuple[dict[str, Any], ...]) -> tuple[tuple[str, str], ...]:
    delivered: dict[str, set[int]] = {}
    for entry in entries:
        if not entry.get("success"):
            continue
        for excerpt in entry.get("delivery") or ():
            delivered.setdefault(excerpt["path"], set()).update(
                range(int(excerpt["start_line"]), int(excerpt["end_line"]) + 1))
    result = []
    for path in paths:
        file = (root / path).resolve()
        covered = delivered.get(path, set())
        if not file.is_relative_to(root.resolve()) or not file.is_file() or not covered:
            classification = "ABSENT_FROM_MCP"
        else:
            total = len(file.read_bytes().splitlines())
            classification = "COMPLETE_IN_MCP" if all(line in covered for line in range(1, total + 1)) else "PARTIAL_IN_MCP"
        result.append((path, classification))
    return tuple(result)

def _changed_paths(status: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({line[3:].split(" -> ")[-1] for line in status if len(line) >= 4}))


def _tests(root: Path) -> tuple[int, str]:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                            cwd=root, capture_output=True, text=True, timeout=60)
    output = SecretRedactor().redact((result.stdout + "\n" + result.stderr)[-4000:]).text
    return result.returncode, output


_TASK_A_V2_EXPECTED = {
    "victim_selection_symbol": "LargestPrivateOwnerPolicy",
    "memory_control_symbol": "MemoryController",
    "recomputation_symbol": "RECOMPUTE",
    "output_preservation_symbol": "output_generated",
    "test_file": "tests/test_phase_7_preemption.py",
}


def evaluate_preemption_v2(message: str) -> tuple[str, ...]:
    try:
        result = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return ("Task A v2 response is not a JSON object",)
    if not isinstance(result, dict) or set(result) != set(_TASK_A_V2_EXPECTED) | {"explanation"}:
        return ("Task A v2 response does not match the required fields",)
    notes = [f"incorrect structured field: {key}" for key, expected in _TASK_A_V2_EXPECTED.items()
             if not isinstance(result[key], str) or result[key].strip().replace("\\", "/") != expected]
    if not isinstance(result["explanation"], str) or not result["explanation"].strip():
        notes.append("Task A v2 explanation is empty")
    return tuple(notes)

def _evaluate(task: TaskSpec, root: Path, message: str, changed: tuple[str, ...],
              git_before: tuple[str, ...], git_after: tuple[str, ...], exit_code: int | None,
              file_change_events: int) -> tuple[bool, tuple[str, ...], int | None, str | None]:
    notes: list[str] = []
    if exit_code != 0:
        notes.append(f"Codex exited with {exit_code}")
    test_exit = None
    test_output = None
    if task.read_only:
        if task.schema_version == 2:
            notes.extend(evaluate_preemption_v2(message))
        elif task.schema_version == 3:
            notes.extend(evaluate_preemption_v3(message))
        elif task.schema_version == 4:
            notes.extend(evaluate_preemption_v4(message))
        for fact in task.required_facts:
            if fact.casefold() not in message.casefold():
                notes.append(f"missing factual marker: {fact}")
        if git_before != git_after or file_change_events:
            notes.append("read-only repository was modified")
    else:
        add_acceptance_tests(task, root)
        test_exit, test_output = _tests(root)
        if test_exit != 0:
            notes.append("visible or independent acceptance tests failed")
        required = {"app/state.py"} if task.id == "oauth-bug" else {"app/config.py", "app/rules.py", "app/uploads.py"}
        if not required.issubset(changed):
            notes.append("required production/helper/config modules were not all changed")
        if not any(path.startswith("tests/") for path in changed):
            notes.append("the requested tests were not added or adjusted")
        unexpected = [path for path in changed if not (path.startswith("app/") or path.startswith("tests/"))]
        if unexpected:
            notes.append("unexpected files modified: " + ", ".join(unexpected))
    return not notes, tuple(notes), test_exit, test_output


def run_one(task: TaskSpec, mode: str, root: Path, fingerprint: str, *, order: int,
            codex_command: str, codex_version: str, model: str, effort: str, timeout: int,
            artifact_root: Path, primary_repository_root: Path, windows_sandbox: str,
            run_id: str | None = None) -> CodexBenchmarkRun:
    if source_fingerprint(root) != fingerprint:
        raise RuntimeError("benchmark snapshot changed before Codex invocation")
    before = _status(root)
    if before:
        raise RuntimeError("benchmark snapshot is not clean before Codex invocation")
    run_id = run_id or _new_run_id()
    _mcp_preflight(codex_command, mode, root, run_id=run_id, task_id=task.id)
    primary_before = primary_usage_signature(primary_repository_root)
    start_head = _head(root)
    command = build_invocation(codex_command, task, mode, root, model=model, effort=effort,
                               windows_sandbox=windows_sandbox, run_id=run_id)
    if _status(root):
        raise RuntimeError("benchmark snapshot is not clean immediately before Codex process creation")
    timestamp = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    warnings: list[str] = []
    try:
        process = subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=timeout)
        output, exit_code = process.stdout, process.returncode
        if process.stderr:
            warnings.append("Codex stderr: " + SecretRedactor().redact(process.stderr[-500:]).text)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        exit_code = None
        warnings.append(f"Codex timed out after {timeout} seconds")
    elapsed = round(time.perf_counter() - started, 3)
    after = _status(root)
    changed = _changed_paths(after)
    trace = parse_codex_events(output.splitlines(), root)
    entries = _usage_entries(root)
    primary_unchanged = primary_before == primary_usage_signature(primary_repository_root)
    if not primary_unchanged:
        warnings.append("primary repository MCP usage log changed during benchmark run")
    middleman_events = tuple((server, tool) for server, tool in trace.mcp_calls if server == "middle-man")
    warnings.extend(isolation_warnings(mode, entries, trace.mcp_calls))
    if mode == "optimized":
        warnings.extend(validate_initial_context_budgets(entries, BenchmarkPolicy().initial_context_budget))
        sessions = {entry.get("server_session_id") for entry in entries
                    if isinstance(entry.get("server_session_id"), str)}
        if len(sessions) > 1:
            warnings.append("optimized MCP calls spanned multiple server sessions")
    if mode == "optimized" and any(
        entry.get("server_implementation") != server_implementation_identity() for entry in entries
    ):
        warnings.append("optimized MCP implementation identity differs from current benchmark environment")

    if source_fingerprint(root) == fingerprint and not task.read_only:
        warnings.append("edit task made no source changes")
    if trace.reported_model and trace.reported_model != model:
        warnings.append("reported model differs from configured model")
    if trace.reported_effort and trace.reported_effort != effort:
        warnings.append("reported reasoning effort differs from configured effort")
    passed, notes, test_exit, test_output = _evaluate(task, root, trace.final_message, changed, before, after,
                                                       exit_code, trace.file_change_events)
    counts = Counter(entry.get("tool", "unknown") for entry in entries)
    delivery = measure_delivery(entries)
    verification = "event-verified" if trace.reported_model == model and trace.reported_effort == effort else "explicit CLI configuration; not event-verified"
    safe_event_path = artifact_root / f"{task.id}-{mode}-events.json"
    safe_event_path.write_text(json.dumps(trace.sanitized_events, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    valid = _infrastructure_valid(mode, entries, warnings)
    return CodexBenchmarkRun(task.id, mode, order, codex_version, model, effort, verification, fingerprint,
                             start_head, timestamp, exit_code, elapsed, passed, notes, before, after, changed,
                             test_exit, test_output, trace.native, tuple(sorted(counts.items())),
                             len(middleman_events), delivery, trace.usage, trace.thread_id,
                             trace.final_message, trace.event_count, tuple(warnings + list(trace.errors)), valid,
                             mcp_root_verified=mode == "optimized" and len(entries) == len(middleman_events) and
                             bool(entries) and primary_unchanged,
                             primary_repo_usage_unchanged=primary_unchanged, preflight_passed=True,
                             sandbox_mode=windows_sandbox, task_version=task.schema_version,
                             evaluator_version=task.schema_version,
                             tool_profile="codex-core" if mode == "optimized" else "none",
                             source_commit=task.source_ref, source_tree_fingerprint=fingerprint,
                             benchmark_run_id=run_id,
                             server_session_ids=tuple(sorted({entry["server_session_id"] for entry in entries
                                                               if isinstance(entry.get("server_session_id"), str)})),
                             mcp_session_trace=tuple((entry.get("call_sequence"), entry.get("tool", "unknown"),
                                                      entry.get("server_session_id")) for entry in entries),
                             native_read_mcp_coverage=classify_native_read_coverage(
                                 root, trace.native.unique_files, entries))


def _pair(task: TaskSpec, root: Path, instructions: str, *, first: str, order: int, command: str,
          version: str, model: str, effort: str, timeout: int, artifacts: Path,
          primary_repository_root: Path, windows_sandbox: str, run_id: str) -> CodexBenchmarkPair:
    baseline, optimized, fingerprint = prepare_pair(task, root, instructions)
    if task.id == "oauth-bug":
        for snapshot in (baseline, optimized):
            if _tests(snapshot)[0] == 0:
                raise RuntimeError("OAuth bug fixture does not fail before Codex")
    if task.id == "upload-feature":
        for snapshot in (baseline, optimized):
            if _tests(snapshot)[0] != 0:
                raise RuntimeError("upload fixture is not green before Codex")
    first_root = baseline if first == "baseline" else optimized
    second_root = optimized if first == "baseline" else baseline
    first_run = run_one(task, first, first_root, fingerprint, order=order, codex_command=command,
                        codex_version=version, model=model, effort=effort, timeout=timeout, artifact_root=artifacts, primary_repository_root=primary_repository_root, windows_sandbox=windows_sandbox, run_id=run_id)
    second_mode = "optimized" if first == "baseline" else "baseline"
    second_run = run_one(task, second_mode, second_root, fingerprint, order=order + 1, codex_command=command,
                         codex_version=version, model=model, effort=effort, timeout=timeout, artifact_root=artifacts, primary_repository_root=primary_repository_root, windows_sandbox=windows_sandbox, run_id=run_id)
    baseline_run = first_run if first == "baseline" else second_run
    optimized_run = first_run if first == "optimized" else second_run
    valid = baseline_run.valid and optimized_run.valid and baseline_run.starting_fingerprint == optimized_run.starting_fingerprint
    if not valid:
        gate = "INVALID_INFRASTRUCTURE"
    elif baseline_run.correctness and not optimized_run.correctness:
        gate = "CORRECTNESS_REGRESSION"
    elif not baseline_run.correctness or not optimized_run.correctness:
        gate = "TASK_FAILURE"
    elif (optimized_run.native.file_reads < baseline_run.native.file_reads or
          optimized_run.native.search_calls + optimized_run.native.listing_calls <
          baseline_run.native.search_calls + baseline_run.native.listing_calls):
        gate = "CORRECT_WITH_LESS_NATIVE_EXPLORATION"
    else:
        gate = "CORRECT_NO_MEASURED_EXPLORATION_GAIN"
    return CodexBenchmarkPair(task.id, task.title, fingerprint, baseline_run, optimized_run, valid, gate,
                              task.schema_version, task.source_ref, fingerprint)


def run_suite(task_ids: tuple[str, ...], *, repository_root: Path, artifact_base: Path,
              model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT,
              timeout: int = DEFAULT_TIMEOUT, windows_sandbox: str = WINDOWS_SANDBOX,
              snapshot_root: Path | None = None) -> CodexBenchmarkSuite:
    from middle_man.gateway.codex_benchmark.infrastructure import run_local_preflight

    if len({task_id for task_id in task_ids if task_id in
            {"preemption", "preemption-v2", "preemption-v3", "preemption-v4"}}) > 1:
        raise ValueError("cannot run and aggregate different Task A versions in the same suite")
    command = _codex_executable()
    preflight = run_local_preflight(command, model=model, effort=effort, windows_sandbox=windows_sandbox,
                                    snapshot_root=snapshot_root, repository_root=repository_root)
    if not preflight.passed:
        raise RuntimeError("Codex infrastructure preflight failed; no benchmark runs started: " +
                           "; ".join(preflight.errors))
    version = _codex_version(command)
    run_id = _new_run_id()
    artifacts = artifact_base.resolve() / run_id
    if not artifacts.is_relative_to(repository_root.resolve()):
        raise ValueError("benchmark artifacts must stay inside the repository")
    artifacts.mkdir(parents=True, exist_ok=False)
    parent = snapshot_root.resolve() if snapshot_root is not None else Path(tempfile.gettempdir()).resolve()
    snapshots = parent / f"middle-man-codex-{run_id}"
    if any((ancestor / "AGENTS.md").exists() for ancestor in snapshots.parents):
        raise RuntimeError("benchmark snapshot ancestors contain AGENTS.md and would contaminate the baseline")
    snapshots.mkdir(parents=True, exist_ok=False)
    instructions = (repository_root / "AGENTS.md").read_text(encoding="utf-8")
    wanted = [task for task in TASKS if task.id in task_ids]
    if len(wanted) != len(set(task_ids)):
        raise ValueError("unknown or duplicate task ID")
    pairs: list[CodexBenchmarkPair] = []
    for index, task in enumerate(wanted):
        pair_root = snapshots / task.id
        pair_root.mkdir()
        first = "optimized" if index % 2 else "baseline"
        pair = _pair(task, pair_root, instructions, first=first, order=index * 2 + 1,
                     command=command, version=version, model=model, effort=effort,
                     timeout=timeout, artifacts=artifacts, primary_repository_root=repository_root, windows_sandbox=windows_sandbox,
                     run_id=run_id)
        pairs.append(pair)
        reason = f"stopped after infrastructure-invalid pair: {task.id}" if not pair.valid else None
        partial = CodexBenchmarkSuite(run_id, datetime.now(timezone.utc).isoformat(), version,
                                      model, effort, tuple(pairs), str(artifacts), task_ids, reason)
        result = asdict(partial)
        result["aggregate"] = aggregate_report(result["pairs"])
        (artifacts / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
        if reason:
            break
    return partial


def load_suite(repository_root: Path, run_id: str) -> dict[str, Any]:
    if Path(run_id).name != run_id or not run_id:
        raise ValueError("invalid benchmark run ID")
    path = repository_root / ".middle_man_cache" / "codex_benchmarks" / run_id / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def pair_input_diagnostics(pair: dict[str, Any]) -> dict[str, int | None] | None:
    """Descriptive Codex usage arithmetic, only for infrastructure-valid correct pairs."""
    if not pair.get("valid") or not all(pair.get(mode, {}).get("correctness") for mode in ("baseline", "optimized")):
        return None

    def count(value: Any) -> int | None:
        return value if type(value) is int and value >= 0 else None

    def usage(mode: str, field: str) -> int | None:
        return count(pair[mode].get("codex_reported_usage", {}).get(field))

    def difference(left: int | None, right: int | None) -> int | None:
        return left - right if left is not None and right is not None else None

    baseline_input, optimized_input = usage("baseline", "input_tokens"), usage("optimized", "input_tokens")
    baseline_cached, optimized_cached = usage("baseline", "cached_input_tokens"), usage("optimized", "cached_input_tokens")
    baseline_uncached = (difference(baseline_input, baseline_cached)
                         if baseline_input is not None and baseline_cached is not None
                         and baseline_cached <= baseline_input else None)
    optimized_uncached = (difference(optimized_input, optimized_cached)
                          if optimized_input is not None and optimized_cached is not None
                          and optimized_cached <= optimized_input else None)
    context = pair["optimized"].get("context", {})
    return {
        "baseline_uncached_input_diagnostic": baseline_uncached,
        "optimized_uncached_input_diagnostic": optimized_uncached,
        "input_delta_diagnostic": difference(optimized_input, baseline_input),
        "cached_input_delta_diagnostic": difference(optimized_cached, baseline_cached),
        "uncached_input_delta_diagnostic": difference(optimized_uncached, baseline_uncached),
        "optimized_mcp_result_tokens_estimate": count(context.get("all_mcp_result_tokens")),
        "optimized_selected_source_tokens_estimate": count(context.get("selected_tokens")),
    }


def aggregate_report(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    versions = {(pair.get("task_id", "legacy"), pair.get("task_version", 1)) for pair in pairs}
    by_family: dict[str, set[int]] = {}
    for task_id, task_version in versions:
        family = "preemption" if task_id in {"preemption", "preemption-v2", "preemption-v3", "preemption-v4"} else task_id
        by_family.setdefault(family, set()).add(task_version)
    if any(len(items) > 1 for items in by_family.values()):
        raise ValueError("cannot aggregate different versions of the same benchmark task")
    valid = [pair for pair in pairs if pair["valid"]]

    def summed(values: list[int]) -> int | None:
        return sum(values) if valid else None

    def native(mode: str, field: str) -> int | None:
        return summed([pair[mode]["native"][field] for pair in valid])

    def official(mode: str, field: str) -> int | None:
        values = [pair[mode]["codex_reported_usage"][field] for pair in valid]
        return sum(values) if values and all(value is not None for value in values) else None

    contexts = [pair["optimized"]["context"] for pair in valid]
    overlap_available = bool(contexts) and all(item["overlap_available"] for item in contexts)
    unique_bytes = sum(item["unique_source_bytes"] for item in contexts) if overlap_available else None
    repeated_bytes = sum(item["repeated_source_bytes"] for item in contexts) if overlap_available else None
    delivered_bytes = (unique_bytes + repeated_bytes) if overlap_available else None
    result: dict[str, Any] = {"total_pairs": len(pairs), "valid_pairs": len(valid),
                              "invalid_pairs": len(pairs) - len(valid)}
    for mode in ("baseline", "optimized"):
        result[f"{mode}_successes"] = sum(pair[mode]["correctness"] for pair in valid)
        result[f"{mode}_test_passes"] = sum(pair[mode]["test_exit_code"] == 0 for pair in valid)
        result[f"{mode}_native_reads"] = native(mode, "file_reads")
        result[f"{mode}_native_rereads"] = native(mode, "rereads")
        result[f"{mode}_native_searches"] = native(mode, "search_calls")
        result[f"{mode}_native_listings"] = native(mode, "listing_calls")
        result[f"{mode}_unique_file_accesses"] = summed(
            [len(pair[mode]["native"]["unique_files"]) for pair in valid])
        native_calls = [pair[mode]["native"].get("tool_calls") for pair in valid]
        result[f"{mode}_native_tool_calls"] = (sum(native_calls) if native_calls and
                                               all(type(value) is int and value >= 0 for value in native_calls) else None)
        mcp_calls = summed([sum(count for _, count in pair[mode]["mcp_calls_by_tool"]) for pair in valid])
        result[f"{mode}_mcp_calls"] = mcp_calls
        result[f"{mode}_observed_tool_interactions"] = (
            result[f"{mode}_native_tool_calls"] + mcp_calls
            if result[f"{mode}_native_tool_calls"] is not None and mcp_calls is not None else None)
        for field in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
                      "total_tokens"):
            result[f"{mode}_codex_{field}"] = official(mode, field)
    result.update({
        "correct_both": sum(pair["baseline"]["correctness"] and pair["optimized"]["correctness"]
                            for pair in valid),
        "optimized_mcp_calls": summed([sum(count for _, count in pair["optimized"]["mcp_calls_by_tool"])
                                       for pair in valid]),
        "optimized_context_packs": summed([len(item["pack_fingerprints"]) for item in contexts]),
        "optimized_candidate_source_tokens_estimate": summed([item["candidate_tokens"] for item in contexts]),
        "optimized_selected_source_tokens_estimate": summed([item["selected_tokens"] for item in contexts]),
        "optimized_unique_source_bytes": unique_bytes,
        "optimized_repeated_source_bytes": repeated_bytes,
        "optimized_unique_source_tokens_estimate": (unique_bytes + 3) // 4 if unique_bytes is not None else None,
        "optimized_repeated_source_tokens_estimate": (repeated_bytes + 3) // 4 if repeated_bytes is not None else None,
        "optimized_overlap_ratio": (repeated_bytes / delivered_bytes) if delivered_bytes else None,
        "optimized_non_source_pack_overhead_tokens_estimate": summed(
            [item["non_source_pack_overhead_estimate"] for item in contexts]),
        "correct_pair_input_diagnostics": [
            {"task_id": pair.get("task_id"), **diagnostics}
            for pair in valid if (diagnostics := pair_input_diagnostics(pair)) is not None],
    })
    return result

def format_report(data: dict[str, Any]) -> str:
    lines = ["MIDDLE_MAN CODEX A/B BENCHMARK", f"Run: {data['run_id']}",
             f"Codex: {data['codex_version']}  Model: {data['model']}  Effort: {data['effort']}"]
    for pair in data["pairs"]:
        baseline, optimized = pair["baseline"], pair["optimized"]
        lines.append(f"Source commit: {pair.get('source_commit') or 'synthetic fixture'}; source fingerprint: {pair.get('source_tree_fingerprint') or pair.get('source_fingerprint', 'unknown')}")
        if not pair["valid"]:
            lines.extend(["", f"{pair['title']} v{pair.get('task_version', 1)} [{pair['quality_gate']}]",
                          f"Invalid A/B pair; diagnostics only. baseline warnings={baseline['warnings']} "
                          f"optimized warnings={optimized['warnings']}",
                          f"Optimized MCP session trace: {optimized.get('mcp_session_trace', [])}",
                          f"Correctness notes: baseline={baseline['correctness_notes']} "
                          f"optimized={optimized['correctness_notes']}"])
            continue
        lines.extend(["", f"{pair['title']} v{pair.get('task_version', 1)} [{pair['quality_gate']}]",
                      f"Correctness: baseline={baseline['correctness']} optimized={optimized['correctness']}",
                      f"Native tool calls: {baseline['native'].get('tool_calls')} -> {optimized['native'].get('tool_calls')}",
                      f"Native reads: {baseline['native']['file_reads']} -> {optimized['native']['file_reads']}; "
                      f"unique files: {len(baseline['native']['unique_files'])} -> {len(optimized['native']['unique_files'])}; "
                      f"rereads: {baseline['native']['rereads']} -> {optimized['native']['rereads']}",
                      f"Search/listing: {baseline['native']['search_calls'] + baseline['native']['listing_calls']} -> "
                      f"{optimized['native']['search_calls'] + optimized['native']['listing_calls']}",
                      f"Context Packs/expansions: {len(optimized['context']['pack_fingerprints'])}; "
                      f"delivered files: {len(optimized['context']['selected_paths'])}",
                      f"Middle_Man calls: {sum(count for _, count in optimized['mcp_calls_by_tool'])} "
                      f"{dict(optimized['mcp_calls_by_tool'])}",
                      f"Total observed tool interactions (native + MCP): "
                      f"{baseline['native'].get('tool_calls', 0) + sum(count for _, count in baseline['mcp_calls_by_tool'])} -> "
                      f"{optimized['native'].get('tool_calls', 0) + sum(count for _, count in optimized['mcp_calls_by_tool'])}",
                      f"MCP session trace: {optimized.get('mcp_session_trace', [])}; "
                      f"native read MCP coverage: {optimized.get('native_read_mcp_coverage', [])}",
                      f"Estimated candidate/selected/unique/repeated source tokens: "
                      f"{optimized['context']['candidate_tokens']}/{optimized['context']['selected_tokens']}/"
                      f"{optimized['context']['unique_source_tokens_estimate']}/"
                      f"{optimized['context']['repeated_source_tokens_estimate']}",
                      f"Estimated MCP result/pack overhead tokens: "
                      f"{optimized['context']['all_mcp_result_tokens']}/"
                      f"{optimized['context']['non_source_pack_overhead_estimate']}",
                      f"Overlap: {optimized['context']['overlap_ratio']}; "
                      f"duration: {baseline['elapsed_seconds']}s -> {optimized['elapsed_seconds']}s",
                      f"Codex-reported input/output: {baseline['codex_reported_usage']['input_tokens']}/"
                      f"{baseline['codex_reported_usage']['output_tokens']} -> "
                      f"{optimized['codex_reported_usage']['input_tokens']}/"
                      f"{optimized['codex_reported_usage']['output_tokens']}",
                      f"Modified files: baseline={baseline['modified_files']} optimized={optimized['modified_files']}"])
        diagnostics = pair_input_diagnostics(pair)
        if diagnostics is not None:
            lines.append(f"Codex input diagnostics (not billing or quota): "
                         f"input delta={diagnostics['input_delta_diagnostic']}; "
                         f"cached delta={diagnostics['cached_input_delta_diagnostic']}; "
                         f"input-minus-cached={diagnostics['baseline_uncached_input_diagnostic']} -> "
                         f"{diagnostics['optimized_uncached_input_diagnostic']} "
                         f"(delta={diagnostics['uncached_input_delta_diagnostic']}); "
                         f"optimized MCP result/selected source estimates="
                         f"{diagnostics['optimized_mcp_result_tokens_estimate']}/"
                         f"{diagnostics['optimized_selected_source_tokens_estimate']}")
        if baseline["correctness_notes"] or optimized["correctness_notes"]:
            lines.append(f"Correctness notes: baseline={baseline['correctness_notes']} optimized={optimized['correctness_notes']}")
    if len(data["pairs"]) < len(data.get("planned_task_ids", data["pairs"])):
        lines.append(f"Incomplete suite: {len(data['pairs'])}/{len(data['planned_task_ids'])} pairs completed")
    aggregate = data.get("aggregate") or aggregate_report(data["pairs"])
    lines.append(f"Valid pairs: {aggregate['valid_pairs']}; both correct: {aggregate['correct_both']}")
    if aggregate["valid_pairs"]:
        lines.append(f"Aggregate successes/tests passed: {aggregate['baseline_successes']}/{aggregate['baseline_test_passes']} -> "
                     f"{aggregate['optimized_successes']}/{aggregate['optimized_test_passes']}")
        lines.append(f"Aggregate native reads/rereads/unique file accesses: "
                     f"{aggregate['baseline_native_reads']}/{aggregate['baseline_native_rereads']}/{aggregate['baseline_unique_file_accesses']} -> "
                     f"{aggregate['optimized_native_reads']}/{aggregate['optimized_native_rereads']}/{aggregate['optimized_unique_file_accesses']}")
        if aggregate.get("baseline_observed_tool_interactions") is not None:
            lines.append(f"Aggregate native calls / MCP calls / observed interactions: "
                         f"{aggregate['baseline_native_tool_calls']}/{aggregate['baseline_mcp_calls']}/"
                         f"{aggregate['baseline_observed_tool_interactions']} -> "
                         f"{aggregate['optimized_native_tool_calls']}/{aggregate['optimized_mcp_calls']}/"
                         f"{aggregate['optimized_observed_tool_interactions']}")
        lines.append(f"Aggregate searches/listings: {aggregate['baseline_native_searches']}/{aggregate['baseline_native_listings']} -> "
                     f"{aggregate['optimized_native_searches']}/{aggregate['optimized_native_listings']}")
        lines.append(f"Aggregate optimized MCP calls/packs: {aggregate['optimized_mcp_calls']}/{aggregate['optimized_context_packs']}; "
                     f"unique/repeated source tokens estimated: {aggregate['optimized_unique_source_tokens_estimate']}/"
                     f"{aggregate['optimized_repeated_source_tokens_estimate']}; overlap: {aggregate['optimized_overlap_ratio']}")
        lines.append(f"Aggregate Codex-reported input tokens: {aggregate['baseline_codex_input_tokens']} -> "
                     f"{aggregate['optimized_codex_input_tokens']}")
    if data.get("aborted_reason"):
        lines.append(f"Aborted: {data['aborted_reason']}")
    lines.append("Middle_Man context sizes are heuristic estimates, not Codex billing or plan usage.")
    return "\n".join(lines)
