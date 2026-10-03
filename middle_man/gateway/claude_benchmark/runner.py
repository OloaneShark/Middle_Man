"""Dry-run-only Claude A/B preparation using the locked Phase 22 offline policy."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from middle_man.gateway.codex_benchmark.offline_auto import decide_offline_locator
from middle_man.gateway.codex_benchmark.offline_locator import append_offline_locator, build_offline_locator
from middle_man.gateway.codex_benchmark.tasks import TaskSpec, _write_fixture
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.tokens import HeuristicTokenEstimator

from .infrastructure import ClaudeCli, git_clean, require_memory_isolation, snapshot_fingerprint


MODES = ("offline-auto", "offline-locator")
READ_TOOLS = "Read,Glob,Grep"
WRITE_TOOLS = "Read,Glob,Grep,Edit,Write,Bash"


@dataclass(frozen=True, slots=True)
class ClaudePreview:
    task_id: str
    requested_model: str
    observed_model: str | None
    optimized_mode: str
    decision: str
    reason: str
    candidate_source_tokens_estimate: int
    selected_source_tokens_estimate: int
    model_visible_middle_man_tokens_estimate: int
    locator_sha256: str | None
    source_fingerprint: str
    prompt_equal: bool
    baseline_prompt_sha256: str
    optimized_prompt_sha256: str
    cli_ready: bool
    permission_profile: str
    max_turns: int | None
    setting_sources: str | None
    baseline_command: tuple[str, ...]
    optimized_command: tuple[str, ...]
    mcp_registered: bool = False
    external_inference_calls: int = 0


def prepare_snapshots(task: TaskSpec, pair_root: Path) -> tuple[Path, Path, str]:
    source = pair_root / "source"
    source.mkdir(parents=True, exist_ok=False)
    _write_fixture(task, source)
    baseline, optimized = pair_root / "baseline", pair_root / "optimized"
    shutil.copytree(source, baseline)
    shutil.copytree(source, optimized)
    fingerprint = snapshot_fingerprint(baseline)
    if fingerprint != snapshot_fingerprint(optimized):
        raise RuntimeError("Claude benchmark snapshots differ")
    for root in (baseline, optimized):
        require_memory_isolation(root)
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Middle_Man Benchmark",
                        "-c", "user.email=benchmark@example.invalid", "commit", "-q", "-m",
                        "Claude benchmark start"], check=True, capture_output=True)
        if not git_clean(root) or snapshot_fingerprint(root) != fingerprint:
            raise RuntimeError("Claude benchmark snapshot is dirty or changed")
    return baseline, optimized, fingerprint


def build_invocation(cli: ClaudeCli, *, model: str, read_only: bool,
                     max_turns: int | None, prompt: str,
                     setting_sources: str | None = None) -> tuple[str, ...]:
    if not model.strip() or not prompt.strip():
        raise ValueError("model and prompt are required")
    if max_turns is not None and max_turns < 1:
        raise ValueError("max_turns must be positive")
    if not cli.ready:
        raise RuntimeError(cli.error or "Claude CLI has unverified required flags")
    if max_turns is not None and "--max-turns" not in cli.flags:
        raise RuntimeError("installed Claude CLI does not document --max-turns")
    if setting_sources is not None and "--setting-sources" not in cli.flags:
        raise RuntimeError("installed Claude CLI does not document --setting-sources")
    return (cli.executable or "claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--model", model, "--tools", READ_TOOLS if read_only else WRITE_TOOLS,
            *(("--max-turns", str(max_turns)) if max_turns is not None else ()),
            *(("--setting-sources", setting_sources) if setting_sources is not None else ()))


def preview_pair(task: TaskSpec, root: Path, cli: ClaudeCli, *, model: str = "sonnet",
                 mode: str = "offline-auto", max_turns: int | None = None,
                 setting_sources: str | None = None) -> ClaudePreview:
    if not model.strip() or max_turns is not None and max_turns < 1:
        raise ValueError("model must be nonempty and max_turns positive if supplied")
    if mode not in MODES:
        raise ValueError("unsupported Claude offline mode")
    if task.id not in {"preemption-v4", "oauth-bug", "upload-feature", "large-edit-v1"}:
        raise ValueError("task is not supported by the frozen offline locator")
    baseline, optimized, fingerprint = prepare_snapshots(task, root)
    config = GatewayConfig(optimized)
    query = ContextQuery(task.prompt)
    locator = build_offline_locator(config, query)
    pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
    if pack.fingerprint != locator.pack_fingerprint:
        raise RuntimeError("Claude AUTO pack differs from canonical locator pack")
    decision = decide_offline_locator(pack, locator, read_only=task.read_only)
    use_locator = mode == "offline-locator" or decision.use_locator
    baseline_prompt = task.prompt
    optimized_prompt = append_offline_locator(baseline_prompt, locator.text) if use_locator else baseline_prompt
    if not task.read_only and mode == "offline-auto" and baseline_prompt != optimized_prompt:
        raise RuntimeError("workspace-write AUTO must preserve exact baseline prompt")
    if any((snapshot_fingerprint(path) != fingerprint or not git_clean(path))
           for path in (baseline, optimized)):
        raise RuntimeError("Claude preprocessing changed a benchmark snapshot")
    digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    visible = (HeuristicTokenEstimator().estimate(append_offline_locator("", locator.text))
               if use_locator else 0)
    # A preview never invokes the CLI. Command arguments are retained only when local help verified them.
    baseline_command = build_invocation(cli, model=model, read_only=task.read_only,
                                        max_turns=max_turns, prompt="<prompt redacted>",
                                        setting_sources=setting_sources) if cli.ready else ()
    optimized_command = build_invocation(cli, model=model, read_only=task.read_only,
                                         max_turns=max_turns, prompt="<prompt + source-free locator redacted>"
                                         if use_locator else "<prompt redacted>",
                                         setting_sources=setting_sources) if cli.ready else ()
    return ClaudePreview(task.id, model, None, mode, "LOCATOR_USED" if use_locator else "BYPASSED",
                         "explicit_research_mode" if mode == "offline-locator" else decision.reason,
                         decision.candidate_tokens, decision.selected_tokens, visible,
                         locator.sha256 if use_locator else None, fingerprint,
                         baseline_prompt == optimized_prompt, digest(baseline_prompt), digest(optimized_prompt),
                         cli.ready, "read-only: Read/Glob/Grep only" if task.read_only else
                         "workspace-write: Read/Glob/Grep/Edit/Write/Bash (normal CLI permissions)",
                         max_turns, setting_sources, baseline_command, optimized_command)
