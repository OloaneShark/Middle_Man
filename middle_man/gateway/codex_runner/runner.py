"""Production Codex prompt preparation. External execution is intentionally absent."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from middle_man.gateway.codex_runner.infrastructure import CodexCLI, discover_codex, repository_state, validate_repository
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.offline_navigation import append_offline_locator, build_offline_locator, decide_offline_locator
from middle_man.gateway.tokens import HeuristicTokenEstimator


DEFAULT_MODEL = "gpt-6-sol"
DEFAULT_EFFORT = "high"
EFFORTS = ("low", "medium", "high", "xhigh")


@dataclass(frozen=True, slots=True)
class CodexAudit:
    repository_root: str
    task_hash: str
    task_length_bytes: int
    task_mode: str
    codex_executable: str
    codex_version: str
    requested_model: str
    requested_effort: str
    candidate_tokens_estimate: int
    selected_tokens_estimate: int
    decision: str
    decision_reason: str
    locator_estimated_tokens: int
    model_visible_middle_man_tokens: int
    selected_paths: tuple[str, ...]
    selector_fingerprint: str | None
    locator_hash: str | None
    dry_run: bool
    external_calls: int
    repository_unchanged: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CodexPreview:
    audit: CodexAudit
    prompt: str  # Memory-only; never serialized or printed by the CLI.
    invocation: tuple[str, ...]

    @property
    def redacted_command_shape(self) -> tuple[str, ...]:
        return (*self.invocation[:-1], "<REDACTED_USER_TASK_AND_OPTIONAL_LOCATOR>")


def build_invocation(cli: CodexCLI, root: Path, prompt: str, *, mode: str,
                     model: str, effort: str) -> tuple[str, ...]:
    if mode not in {"read-only", "workspace-write"}:
        raise ValueError("invalid task mode")
    if not model or not model.strip():
        raise ValueError("model must be nonempty")
    if effort not in EFFORTS:
        raise ValueError("unsupported reasoning effort")
    return (cli.executable, "--no-daemon", "-a", "never", "exec", "--ignore-user-config",
            "--strict-config", "-C", str(root), "-s", mode, "--ephemeral", "-m", model,
            "-c", f'model_reasoning_effort="{effort}"', prompt)


def preview_codex(root: Path, task: str, *, mode: str, model: str = DEFAULT_MODEL,
                  effort: str = DEFAULT_EFFORT, cli: CodexCLI | None = None) -> CodexPreview:
    if not task or not task.strip():
        raise ValueError("task must be nonempty")
    if mode not in {"read-only", "workspace-write"}:
        raise ValueError("exactly one task mode is required")
    root = validate_repository(root)
    cli = cli or discover_codex()
    original = task.encode("utf-8")
    before = repository_state(root)
    prompt = task
    candidate = selected = locator_tokens = visible_tokens = 0
    selected_paths: tuple[str, ...] = ()
    selector_fingerprint = locator_hash = None
    reason = "workspace_write_not_validated_for_full_locator"
    decision = "BYPASSED"
    try:
        config = GatewayConfig(root, cache_writes_enabled=False)
        query = ContextQuery(task)
        pack = ContextBuilder(config).build(query, mode="balanced", max_context_tokens=6000)
        locator = build_offline_locator(config, query)
        if locator.pack_fingerprint != pack.fingerprint:
            raise RuntimeError("repository changed during context selection")
        auto = decide_offline_locator(pack, locator, read_only=(mode == "read-only"))
        candidate = auto.candidate_tokens
        selected = auto.selected_tokens
        selected_paths = locator.selected_paths
        selector_fingerprint = locator.selector_fingerprint
        reason = auto.reason
        if auto.use_locator:
            prompt = append_offline_locator(task, locator.text)
            decision = "LOCATOR USED"
            locator_tokens = locator.estimated_tokens
            visible_tokens = HeuristicTokenEstimator().estimate(prompt[len(task):])
            locator_hash = locator.sha256
        invocation = build_invocation(cli, root, prompt, mode=mode, model=model, effort=effort)
    finally:
        after = repository_state(root)
        if after != before:
            raise RuntimeError("repository changed during local Codex preprocessing")
    audit = CodexAudit(str(root), hashlib.sha256(original).hexdigest(), len(original), mode,
                       cli.executable, cli.version, model, effort, candidate, selected, decision,
                       reason, locator_tokens, visible_tokens, selected_paths,
                       selector_fingerprint, locator_hash, True, 0, True)
    return CodexPreview(audit, prompt, invocation)
