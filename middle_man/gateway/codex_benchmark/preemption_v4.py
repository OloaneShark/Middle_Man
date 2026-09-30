"""Task A v4 structured evaluator; these expected values are benchmark-only."""

from __future__ import annotations

import json
import re

from middle_man.gateway.codex_benchmark.preemption_v3 import _test_path_matches


EXPECTED = {
    "victim_selection_policy": "LargestPrivateOwnerPolicy",
    "memory_control_component": "MemoryController",
    "recomputation_work_kind": "RECOMPUTE",
    "output_progress_field": "output_generated",
    "proving_test_file": "tests/test_phase_7_preemption.py",
}
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def _identifier_matches(value: object, expected: str) -> bool:
    if not isinstance(value, str):
        return False
    identifier = value.strip()
    return bool(_IDENTIFIER.fullmatch(identifier)) and identifier.split(".")[-1] == expected


def evaluate_preemption_v4(message: str) -> tuple[str, ...]:
    try:
        result = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return ("Task A v4 response is not a JSON object",)
    if not isinstance(result, dict) or set(result) != set(EXPECTED) | {"explanation"}:
        return ("Task A v4 response does not match the required fields",)
    notes = []
    for key, expected in EXPECTED.items():
        matches = (_test_path_matches(result[key], expected) if key == "proving_test_file" else
                   _identifier_matches(result[key], expected))
        if not matches:
            notes.append(f"incorrect structured field: {key}")
    if not isinstance(result["explanation"], str) or not result["explanation"].strip():
        notes.append("Task A v4 explanation is empty")
    return tuple(notes)
