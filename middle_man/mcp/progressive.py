"""Benchmark-only source seeding over an unchanged canonical Context Pack."""

from __future__ import annotations

from middle_man.gateway.context_models import ContextPack, SourceExcerpt
from middle_man.gateway.tokens import HeuristicTokenEstimator


_PRIORITY = {"REQUIRED": 0, "COVERAGE": 1, "REPAIR": 2, "DEPTH": 3}


def plan_seed(pack: ContextPack, source_budget: int) -> tuple[tuple[SourceExcerpt, ...], int]:
    if source_budget < 1:
        raise ValueError("source delivery budget must be positive")
    phase_by_range = {
        (diagnostic.candidate_path, phase.start_line, phase.end_line): phase.phase
        for diagnostic in pack.selection_diagnostics for phase in diagnostic.selected_range_phases
    }
    ranked = sorted(enumerate(pack.excerpts), key=lambda pair: (
        _PRIORITY.get(phase_by_range.get((pair[1].path, pair[1].start_line,
                                           pair[1].end_line), "DEPTH"), 3), pair[0]))
    estimator = HeuristicTokenEstimator()
    selected: set[int] = set()
    used = 0
    for index, excerpt in ranked:
        cost = estimator.estimate(excerpt.text)
        phase = phase_by_range.get((excerpt.path, excerpt.start_line, excerpt.end_line), "DEPTH")
        if phase == "REQUIRED" or used + cost <= source_budget:
            selected.add(index)
            used += cost
    return tuple(excerpt for index, excerpt in enumerate(pack.excerpts) if index in selected), max(0, used - source_budget)
