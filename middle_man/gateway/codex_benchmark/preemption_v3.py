"""Task A v3 structured evaluator and local-only required-source accounting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pathlib import Path

from middle_man.gateway.context_models import ContextPack
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.source import SourceReader

EXPECTED = {
    "victim_selection_symbol": "LargestPrivateOwnerPolicy",
    "memory_control_symbol": "MemoryController",
    "recomputation_symbol": "RECOMPUTE",
    "output_preservation_symbol": "output_generated",
    "test_file": "tests/test_phase_7_preemption.py",
}
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_TEST_NAME = re.compile(r"[A-Za-z_]\w*")


def _identifier_matches(value: object, expected: str) -> bool:
    if not isinstance(value, str):
        return False
    identifiers = [part.strip() for part in re.split(r"[;,]", value)]
    return bool(identifiers) and all(_IDENTIFIER.fullmatch(part) for part in identifiers) and any(
        expected in part.split(".") for part in identifiers)


def _test_path_matches(value: object, expected: str) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.strip().replace("\\", "/").split("::")
    if len(parts) > 2 or len(parts) == 2 and not _TEST_NAME.fullmatch(parts[1]):
        return False
    path = parts[0]
    if not path or ".." in path.split("/"):
        return False
    return path.split("/")[-2:] == expected.split("/")[-2:]


def evaluate_preemption_v3(message: str) -> tuple[str, ...]:
    try:
        result = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return ("Task A v3 response is not a JSON object",)
    if not isinstance(result, dict) or set(result) != set(EXPECTED) | {"explanation"}:
        return ("Task A v3 response does not match the required fields",)
    notes = []
    for key, expected in EXPECTED.items():
        matches = (_test_path_matches(result[key], expected) if key == "test_file" else
                   _identifier_matches(result[key], expected))
        if not matches:
            notes.append(f"incorrect structured field: {key}")
    if not isinstance(result["explanation"], str) or not result["explanation"].strip():
        notes.append("Task A v3 explanation is empty")
    return tuple(notes)


@dataclass(frozen=True, slots=True)
class RequiredSourceUnit:
    path: str
    identifier: str


# Evaluation metadata only. The production selector never imports this module.
TASK_A_V3_UNITS = (
    RequiredSourceUnit("middle_man/lab/preemption.py", "LargestPrivateOwnerPolicy"),
    RequiredSourceUnit("middle_man/lab/memory_control.py", "MemoryController"),
    RequiredSourceUnit("middle_man/lab/memory.py", "def release_request"),
    RequiredSourceUnit("middle_man/lab/scheduler.py", "WorkKind.RECOMPUTE"),
    RequiredSourceUnit("middle_man/lab/work.py", "RECOMPUTE ="),
    RequiredSourceUnit("middle_man/lab/request.py", "output_generated"),
    RequiredSourceUnit("tests/test_phase_7_preemption.py", "test_pressure_preempts_rebuilds_and_preserves_output"),
)


@dataclass(frozen=True, slots=True)
class SourceRecall:
    required_file_recall: float
    required_symbol_recall: float
    required_source_tokens: int
    selected_source_tokens: int
    selected_required_source_tokens: int
    selected_non_required_source_tokens: int
    missing_files: tuple[str, ...]
    missing_symbols: tuple[str, ...]


def measure_required_source(pack: ContextPack, units: tuple[RequiredSourceUnit, ...] = TASK_A_V3_UNITS
                            ) -> SourceRecall:
    required_paths = {unit.path for unit in units}
    selected_paths = set(pack.selected_files)
    missing_files = tuple(sorted(required_paths - selected_paths))
    missing_symbols = tuple(unit.identifier for unit in units if not any(
        excerpt.path == unit.path and unit.identifier in excerpt.text for excerpt in pack.excerpts))
    selected_required = sum((len(excerpt.text.encode("utf-8")) + 3) // 4 for excerpt in pack.excerpts
                            if excerpt.path in required_paths)
    selected_nonrequired = sum((len(excerpt.text.encode("utf-8")) + 3) // 4 for excerpt in pack.excerpts
                               if excerpt.path not in required_paths)
    config = GatewayConfig(Path(pack.repository.root))
    reader = SourceReader(config, RepositoryIndexer(config).index())
    required_tokens = sum((len(reader.read(path).text.encode("utf-8")) + 3) // 4
                          for path in sorted(required_paths))
    # This is fixture-based path accounting, not a semantic relevance or billing metric.
    return SourceRecall(1 - len(missing_files) / len(required_paths),
                        1 - len(missing_symbols) / len(units),
                        required_tokens,
                        pack.metrics.estimated_selected_tokens,
                        selected_required, selected_nonrequired, missing_files, missing_symbols)
