"""Conservative, local-only decision for benchmark offline navigation."""

from __future__ import annotations

from dataclasses import dataclass

from middle_man.gateway.codex_benchmark.offline_locator import OfflineLocator
from middle_man.gateway.context_models import ContextPack


MIN_CANDIDATE_SOURCE_TOKENS = 10_000


@dataclass(frozen=True, slots=True)
class OfflineLocatorDecision:
    use_locator: bool
    reason: str
    candidate_tokens: int
    selected_tokens: int
    locator_tokens: int
    candidate_paths: int
    selected_paths: int


def decide_offline_locator(pack: ContextPack, locator: OfflineLocator) -> OfflineLocatorDecision:
    candidate = pack.metrics.estimated_raw_candidate_tokens
    use_locator = bool(locator.selected_paths) and candidate >= MIN_CANDIDATE_SOURCE_TOKENS
    return OfflineLocatorDecision(
        use_locator=use_locator,
        reason=("candidate_source_at_least_10000" if use_locator else
                "candidate_source_below_10000_or_no_selected_paths"),
        candidate_tokens=candidate,
        selected_tokens=pack.metrics.estimated_selected_tokens,
        locator_tokens=locator.estimated_tokens,
        candidate_paths=len({item.path for item in pack.candidates}),
        selected_paths=len(locator.selected_paths),
    )
