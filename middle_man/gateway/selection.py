"""Local, deterministic coverage and cost planning for source excerpts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath

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
    repair_candidate: bool = False
    coverage_gain: float = 0.0
    evicted_ranges: tuple[tuple[str, int, int], ...] = ()
    evicted_cost: int = 0
    added_cost: int = 0
    coverage_before: tuple[str, ...] = ()
    coverage_after: tuple[str, ...] = ()
    repair_reason: str | None = None


def _strengths(entry: SelectionEntry) -> dict[str, int]:
    candidate = entry.candidate
    if candidate is None:
        return {}
    result: dict[str, int] = {}
    for signal in candidate.signals:
        if not signal.term:
            continue
        if signal.kind in {"filename_term", "symbol_term"}:
            strength = 3
        elif signal.kind == "source_term" and signal.weight >= 10:
            strength = 2
        elif signal.kind == "family_term" and signal.weight >= 8:
            strength = 1
        else:
            strength = 0
        if strength:
            result[signal.term] = max(result.get(signal.term, 0), strength)
    return result


def _repair(entries: tuple[SelectionEntry, ...], chosen: list[int], budget: int,
            tests_requested: bool, coverage_selected: set[int]
            ) -> tuple[list[int], dict[int, tuple[float, tuple[int, ...], tuple[str, ...], tuple[str, ...]]]]:
    """Bounded one-way swaps for omitted evidence; never displace sole strong support."""
    repairs: dict[int, tuple[float, tuple[int, ...], tuple[str, ...], tuple[str, ...]]] = {}
    selected = set(chosen)
    used = sum(entries[index].cost for index in selected)
    strengths = [_strengths(entry) for entry in entries]
    anchor_parents = Counter(str(PurePosixPath(entries[index].path).parent)
                             for index in selected if entries[index].anchor)

    def coverage(indices: set[int]) -> dict[str, int]:
        result: dict[str, int] = {}
        for index in indices:
            for term, strength in strengths[index].items():
                result[term] = max(result.get(term, 0), strength)
        return result

    # One accepted swap prevents an equivalent candidate from swapping back.
    for _ in range(1):
        before = coverage(selected)
        options = []
        for index, entry in enumerate(entries):
            if index in selected or not entry.affinity or entry.candidate is None:
                continue
            if entry.cost > budget or entry.is_test and tests_requested and any(
                    entries[number].is_test for number in selected):
                continue
            signals = strengths[index]
            upgrades = {term: strength for term, strength in signals.items()
                        if strength > before.get(term, 0)}
            weak_support = {term for term, strength in signals.items()
                            if strength == before.get(term, 0) == 1}
            connected = any(signal.kind in {"import_neighbor", "reverse_import_neighbor", "tested_source"}
                            for signal in entry.candidate.signals)
            if not upgrades and not (connected and weak_support):
                continue
            parent = str(PurePosixPath(entry.path).parent)
            if not upgrades and not anchor_parents[parent]:
                continue
            gain = sum(18.0 * (strength - before.get(term, 0)) for term, strength in upgrades.items())
            gain += 8.0 * len(weak_support) if connected else 0.0
            gain += min(6, 3 * anchor_parents[parent])
            if gain < 8:
                continue
            options.append((-gain, -entry.candidate.score, entry.cost, entry.path, entry.start_line, index))
        options.sort()
        accepted = False
        for _, _, _, _, _, incoming in options[:12]:
            entry = entries[incoming]
            deficit = max(0, used + entry.cost - budget)
            eviction = []
            freed = 0
            # One or two inexpensive losses, chosen deterministically.
            for outgoing in sorted(selected, key=lambda number: (
                    entries[number].anchor, entries[number].required,
                    -entries[number].cost,
                    entries[number].candidate.score if entries[number].candidate else 0,
                    entries[number].path, entries[number].start_line)) if deficit else ():
                current = entries[outgoing]
                if (outgoing in coverage_selected or current.required or current.anchor or
                        current.is_test and tests_requested):
                    continue
                without = coverage(selected - {outgoing})
                if any(strength >= 2 and without.get(term, 0) < strength
                       for term, strength in strengths[outgoing].items()):
                    continue
                eviction.append(outgoing)
                freed += current.cost
                if freed >= deficit or len(eviction) == 2:
                    break
            if deficit and freed < deficit:
                continue
            after = coverage((selected - set(eviction)) | {incoming})
            if any(after.get(term, 0) < strength for term, strength in before.items()):
                continue
            improvement = sum(18.0 * (after.get(term, 0) - before.get(term, 0))
                              for term in strengths[incoming] if after.get(term, 0) > before.get(term, 0))
            if not improvement and not any(
                    strength == before.get(term, 0) == 1 for term, strength in strengths[incoming].items()):
                continue
            selected.difference_update(eviction)
            selected.add(incoming)
            used += entry.cost - freed
            repairs[incoming] = (improvement or 8.0, tuple(eviction),
                                 tuple(sorted(f"{term}:{strength}" for term, strength in before.items())),
                                 tuple(sorted(f"{term}:{strength}" for term, strength in after.items())))
            accepted = True
            break
        if not accepted:
            break
    return [index for index in chosen if index in selected] + sorted(
        index for index in selected if index not in chosen), repairs


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

    coverage_selected = set(chosen)
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

    original = set(chosen)
    chosen, repairs = _repair(entries, chosen, budget, tests_requested, coverage_selected)
    for index in original - set(chosen):
        decisions[index] = (decisions[index][0], (), "context_budget")
    for index in set(chosen) - original:
        decisions[index] = (used, (), None)

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
            tuple(sorted({key for index in indices for key in decisions[index][1]})),
            any(index in repairs for index in indices),
            sum(repairs[index][0] for index in indices if index in repairs),
            tuple((entries[evicted].path, entries[evicted].start_line, entries[evicted].end_line)
                  for index in indices if index in repairs for evicted in repairs[index][1]),
            sum(entries[evicted].cost for index in indices if index in repairs
                for evicted in repairs[index][1]),
            sum(entries[index].cost for index in indices if index in repairs),
            next((repairs[index][2] for index in indices if index in repairs), ()),
            next((repairs[index][3] for index in indices if index in repairs), ()),
            "underrepresented_query_evidence" if any(index in repairs for index in indices) else None))
    return tuple(chosen), tuple(diagnostics)
