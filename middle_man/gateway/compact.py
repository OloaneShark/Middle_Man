"""Deterministic, secret-safe compaction of developer tool output."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from middle_man.gateway.git_diff import GitDiff
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator, TokenEstimator

_PASS = re.compile(r"\bPASSED\s*$")
_TRACE_END = re.compile(r"^(?:[A-Za-z_][\w.]*(?:Error|Exception|Warning)|E\s+\w+|AssertionError)\b")


@dataclass(frozen=True, slots=True)
class CompactionResult:
    output_type: str
    compacted_text: str
    original_sha256: str
    original_bytes: int
    compacted_bytes: int
    estimated_original_tokens: int
    estimated_compacted_tokens: int
    estimated_tokens_avoided: int
    estimated_reduction_percent: float
    original_lines: int
    compacted_lines: int
    repeated_lines_removed: int
    omitted_lines: int
    truncated: bool
    warnings: tuple[str, ...]
    redaction_categories: tuple[str, ...]
    fingerprint: str


def _collapse_consecutive(lines: list[str]) -> tuple[list[str], int]:
    result: list[str] = []
    removed = 0
    blocks = _trace_blocks(lines)
    position = 0
    while position < len(blocks):
        block, priority = blocks[position]
        if priority == 4:
            result.extend(block)
            position += 1
            continue
        end = position + 1
        while end < len(blocks) and blocks[end][1] != 4 and blocks[end][0] == block:
            end += 1
        count = end - position
        result.append(block[0] + (f" [repeated {count}x]" if count > 1 else ""))
        removed += count - 1
        position = end
    return result, removed


def _trace_blocks(lines: list[str]) -> list[tuple[list[str], int]]:
    blocks: list[tuple[list[str], int]] = []
    position = 0
    while position < len(lines):
        if "Traceback (most recent call last):" in lines[position]:
            end = position + 1
            while end < len(lines):
                if _TRACE_END.match(lines[end].strip()) or lines[end].startswith("E   "):
                    end += 1
                    break
                end += 1
            blocks.append((lines[position:end], 4))
            position = end
        else:
            line = lines[position]
            priority = 3 if re.search(r"(?i)\b(?:ERROR|FATAL|FAILED|Exception|AssertionError)\b", line) else 2 if re.search(r"(?i)\bWARN(?:ING)?\b", line) else 0
            blocks.append(([line], priority))
            position += 1
    return blocks


def _limit(lines: list[str], budget: int, estimator: TokenEstimator) -> tuple[list[str], int, bool]:
    blocks = _trace_blocks(lines)
    costs = [estimator.estimate("\n".join(block)) for block, _ in blocks]
    selected = {index for index, (_, priority) in enumerate(blocks) if priority >= 2}
    used = sum(costs[index] for index in selected)
    for index in sorted((n for n in range(len(blocks)) if n not in selected),
                        key=lambda n: (-blocks[n][1], min(n, len(blocks) - n - 1), n)):
        if used + costs[index] <= budget:
            selected.add(index)
            used += costs[index]
    output: list[str] = []
    omitted = 0
    pending = 0
    for index, (block, _) in enumerate(blocks):
        if index in selected:
            if pending:
                output.append(f"[Middle_Man omitted {pending} low-priority log lines]")
                pending = 0
            output.extend(block)
        else:
            pending += len(block)
            omitted += len(block)
    if pending:
        output.append(f"[Middle_Man omitted {pending} low-priority log lines]")
    return output, omitted, used > budget


class PytestCompactor:
    def prepare(self, text: str) -> tuple[list[str], int]:
        lines = text.splitlines()
        passing = sum(bool(_PASS.search(line)) for line in lines)
        retained = [line for line in lines if not _PASS.search(line) and not re.fullmatch(r"[.sFExX\[\] 0-9%]+", line)]
        if passing:
            retained.insert(0, f"[Middle_Man condensed {passing} passing test lines]")
        return retained, passing


class GenericLogCompactor:
    def prepare(self, text: str) -> tuple[list[str], int]:
        return text.splitlines(), 0


class GitStatusCompactor:
    def prepare(self, text: str) -> tuple[list[str], int]:
        groups: dict[str, list[str]] = {name: [] for name in ("Modified", "Added", "Deleted", "Renamed", "Untracked")}
        section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Untracked files:"):
                section = "Untracked"
                continue
            if stripped.startswith(("Changes to be committed:", "Changes not staged for commit:")):
                section = "Changed"
                continue
            if stripped.startswith(("On branch ", "Your branch ", "nothing to commit", "no changes added", "## ", "(")):
                continue
            if len(line) >= 4 and line[2] == " " and line[:2].strip() and all(char in " MADRCU?!" for char in line[:2]):
                flags, path = line[:2], line[3:]
                category = "Untracked" if flags == "??" else "Renamed" if "R" in flags else "Deleted" if "D" in flags else "Added" if "A" in flags else "Modified"
            elif match := re.match(r"^(modified|new file|deleted|renamed):\s*(.+)$", stripped, re.IGNORECASE):
                category = {"modified": "Modified", "new file": "Added", "deleted": "Deleted", "renamed": "Renamed"}[match.group(1).lower()]
                path = match.group(2)
            elif section == "Untracked" and line[0].isspace():
                category, path = "Untracked", stripped
            else:
                continue
            groups[category].append(path)
        result = []
        for category, paths in groups.items():
            if paths:
                result.append(f"{category} ({len(paths)}):")
                result.extend(f"- {path}" for path in paths)
        return result, 0

class GitDiffCompactor:
    def prepare(self, diff: GitDiff) -> str:
        lines = []
        for file in diff.files:
            lines.append(f"{file.path} [{file.status}]" + (f" (from {file.old_path})" if file.old_path else ""))
            if file.binary_changed:
                lines.append("  binary changed")
            if file.affected_symbols:
                lines.append("  affected symbols: " + ", ".join(file.affected_symbols))
            for hunk in file.hunks:
                lines.append(f"  @@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@")
                lines.extend(f"  {line.kind}{line.text}" for line in hunk.lines if line.kind in {"+", "-"})
        return "\n".join(lines)


class OutputCompactor:
    def __init__(self, *, estimator: TokenEstimator | None = None, redactor: SecretRedactor | None = None) -> None:
        self.estimator = estimator or HeuristicTokenEstimator()
        self.redactor = redactor or SecretRedactor()
        self._pytest = PytestCompactor()
        self._generic = GenericLogCompactor()
        self._status = GitStatusCompactor()
        self._diff = GitDiffCompactor()

    def compact(self, output_type: str, text: str, *, max_tokens: int | None = None) -> CompactionResult:
        if output_type not in {"pytest", "log", "docker", "git-status"}:
            raise ValueError(f"unknown output type: {output_type}")
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        sanitized = self.redactor.redact(text)
        adapter = self._pytest if output_type == "pytest" else self._status if output_type == "git-status" else self._generic
        prepared, passing_removed = adapter.prepare(sanitized.text)
        compacted, repeats_removed = _collapse_consecutive(prepared)
        omitted = 0
        over_budget = False
        if max_tokens is not None and self.estimator.estimate("\n".join(compacted)) > max_tokens:
            if output_type == "git-status":
                over_budget = True
            else:
                compacted, omitted, over_budget = _limit(compacted, max_tokens, self.estimator)
        result_text = "\n".join(compacted) + ("\n" if compacted else "")
        return self._result(output_type, text, result_text, passing_removed + repeats_removed, omitted,
                            over_budget, sanitized.categories)

    def compact_git_diff(self, diff: GitDiff, *, max_tokens: int | None = None) -> CompactionResult:
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        structured = self._diff.prepare(diff)
        sanitized = self.redactor.redact(structured)
        over_budget = max_tokens is not None and self.estimator.estimate(sanitized.text) > max_tokens
        return self._result("git-diff", structured, sanitized.text, 0, 0, over_budget, sanitized.categories)

    def _result(self, output_type: str, original: str, compacted: str, repeated: int, omitted: int,
                over_budget: bool, categories: tuple[str, ...]) -> CompactionResult:
        original_bytes = len(original.encode("utf-8"))
        compacted_bytes = len(compacted.encode("utf-8"))
        raw_tokens = self.estimator.estimate(original)
        compacted_tokens = self.estimator.estimate(compacted)
        warnings = []
        if categories:
            warnings.append("REDACTIONS_APPLIED")
        if omitted:
            warnings.append("LOW_PRIORITY_LINES_OMITTED")
        if over_budget:
            warnings.append("BUDGET_EXCEEDED_FOR_REQUIRED_OUTPUT")
        return CompactionResult(output_type, compacted, hashlib.sha256(original.encode("utf-8")).hexdigest(),
                                original_bytes, compacted_bytes, raw_tokens, compacted_tokens,
                                max(0, raw_tokens - compacted_tokens),
                                round(100 * max(0, raw_tokens - compacted_tokens) / raw_tokens, 2) if raw_tokens else 0.0,
                                len(original.splitlines()), len(compacted.splitlines()), repeated, omitted, bool(omitted),
                                tuple(warnings), categories, hashlib.sha256(compacted.encode("utf-8")).hexdigest())
