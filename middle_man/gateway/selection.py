"""Local, deterministic coverage and cost planning for source excerpts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from middle_man.gateway.relevance import RelevanceCandidate


@dataclass(frozen=True, slots=True)
class SelectionEntry:
    path: str
    start_line: int
    end_line: int
    kind: str
    cost: int
    required: bool
    candidate: RelevanceCandidate | None
    affinity: bool = True
    anchor: bool = False
    is_test: bool = False


@dataclass(frozen=True, slots=True)
class SelectionDiagnostic:
    candidate_path: str
    candidate_score: float
    role: str
    matched_query_terms: tuple[str, ...]
    matched_symbols: tuple[str, ...]
    reasons: tuple[str, ...]
    proposed_source_ranges: tuple[tuple[int, int, str], ...]
    estimated_source_cost: int
    selected: bool
    omission_reason: str | None
    budget_before: int
    covered_signals: tuple[str, ...]


def allocate(entries: tuple[SelectionEntry, ...], budget: int, *, tests_requested: bool = False
             ) -> tuple[tuple[int, ...], tuple[SelectionDiagnostic, ...]]:
    """Select atomic ranges: required, novel strong evidence, then depth."""
    frequencies = Counter(signal.key for entry in entries if entry.candidate
                          for signal in entry.candidate.signals if signal.term)
    chosen: list[int] = []
    covered: set[str] = set()
    decisions: dict[int, tuple[int, tuple[str, ...], str | None]] = {}
    used = 0

    def value(index: int) -> tuple[float, tuple[str, ...]]:
        entry = entries[index]
        candidate = entry.candidate
        if candidate is None or not entry.affinity:
            return 0.0, ()
        novel = []
        gain = 0.0
        for signal in candidate.signals:
            key = ("fileterm:" + signal.term + (":test" if entry.is_test else ":source")
                   if signal.kind == "filename_term" else signal.key)
            if key in covered:
                continue
            if signal.kind in {"explicit_path", "trace_path", "exact_symbol"}:
                weight = 120.0
            elif signal.kind in {"filename_term", "symbol_term"}:
                weight = signal.weight * (1.0 + 1.0 / max(1, frequencies[signal.key]))
            elif signal.kind == "source_term":
                weight = 9.0 if frequencies[signal.key] <= 3 else 3.0
            elif signal.kind == "family_term":
                weight = 4.0 if frequencies[signal.key] <= 3 else 1.0
            elif signal.kind == "related_test" and tests_requested:
                weight = 25.0
            elif signal.kind in {"import_neighbor", "reverse_import_neighbor", "tested_source"}:
                weight = 0.0
            else:
                weight = 0.0
            if weight:
                novel.append(key)
                gain += weight
        if entry.anchor and f"anchor:{entry.path}" not in covered:
            gain += 35.0
            novel.append(f"anchor:{entry.path}")
        return gain, tuple(novel)

    remaining = set(range(len(entries)))
    for index in sorted(remaining, key=lambda number: (-entries[number].required,
                                                        -(entries[number].candidate.score if entries[number].candidate else 0),
                                                        entries[number].path, entries[number].start_line)):
        if not entries[index].required:
            continue
        _, keys = value(index)
        chosen.append(index)
        remaining.remove(index)
        decisions[index] = (used, keys, None)
        covered.update(keys)
        used += entries[index].cost

    # Coverage pass rewards novel structured evidence per estimated source cost.
    while True:
        fitting = [index for index in remaining if entries[index].cost + used <= budget]
        ranked = []
        for index in fitting:
            gain, keys = value(index)
            if gain <= 0:
                continue
            entry = entries[index]
            score = gain * (1.0 + min(entry.candidate.score, 120.0) / 600.0) / (entry.cost + 80) ** 0.65
            ranked.append((score, gain, -entry.cost, entry.path, -entry.start_line, index, keys))
        if not ranked:
            break
        _, _, _, _, _, index, keys = max(ranked)
        chosen.append(index)
        remaining.remove(index)
        decisions[index] = (used, keys, None)
        covered.update(keys)
        used += entries[index].cost

    # Depth pass uses the remaining budget for additional relevant atomic context.
    def depth_value(number: int) -> float:
        candidate = entries[number].candidate
        if candidate is None:
            return 0.0
        rare_family = any(signal.kind == "family_term" and signal.weight >= 10
                          for signal in candidate.signals)
        return candidate.score * (2.5 if rare_family else 1.0) / (entries[number].cost + 80) ** 0.4

    for index in sorted(remaining, key=lambda number: (
            -depth_value(number), entries[number].path, entries[number].start_line)):
        entry = entries[index]
        if entry.affinity and used + entry.cost <= budget:
            chosen.append(index)
            decisions[index] = (used, (), None)
            used += entry.cost
        else:
            decisions[index] = (used, (), "context_budget" if entry.affinity else "outside_task_cluster")

    by_path: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        by_path.setdefault(entry.path, []).append(index)
    selected = set(chosen)
    diagnostics = []
    for path, indices in by_path.items():
        candidate = entries[indices[0]].candidate
        chosen_any = any(index in selected for index in indices)
        reasons = {decisions[index][2] for index in indices if decisions[index][2]}
        omission = ("partial_context_budget" if chosen_any else
                    "context_budget" if "context_budget" in reasons else
                    "outside_task_cluster") if reasons else None
        diagnostics.append(SelectionDiagnostic(
            path, candidate.score if candidate else 0.0,
            candidate.role if candidate else "EXPANSION",
            candidate.matched_terms if candidate else (),
            candidate.matched_symbols if candidate else (),
            candidate.reasons if candidate else ("explicit expansion",),
            tuple((entries[index].start_line, entries[index].end_line, entries[index].kind)
                  for index in indices),
            sum(entries[index].cost for index in indices), chosen_any, omission,
            min(decisions[index][0] for index in indices),
            tuple(sorted({key for index in indices for key in decisions[index][1]}))))
    return tuple(chosen), tuple(diagnostics)
