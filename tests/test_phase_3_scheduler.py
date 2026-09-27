import pytest

from middle_man.lab.request import InferenceRequest
from middle_man.lab.scheduler import BalancedScheduler, DecodePriorityScheduler
from middle_man.lab.work import WorkKind


def make_prefilling(request_id: str, prompt_tokens: int) -> InferenceRequest:
    request = InferenceRequest(request_id, 0.0, prompt_tokens=prompt_tokens, max_output_tokens=4)
    request.mark_admitted(now_ms=0.0)
    return request


def make_decoding(request_id: str) -> InferenceRequest:
    request = InferenceRequest(request_id, 0.0, prompt_tokens=2, max_output_tokens=4)
    request.mark_admitted(now_ms=0.0)
    request.apply_prefill(2, now_ms=1.0)
    return request


def test_decode_priority_enforces_token_budget_and_decode_first() -> None:
    decoding = make_decoding("decode")
    prefilling = make_prefilling("prefill", prompt_tokens=100)
    plan = DecodePriorityScheduler().plan([prefilling, decoding], token_budget=8)
    assert plan.scheduled_tokens == 8
    assert plan.items[0].request_id == "decode"
    assert plan.items[0].kind == WorkKind.DECODE
    assert plan.items[1].tokens == 7
    plan.validate()


def test_chunked_prefill_limits_large_prompt_to_remaining_budget() -> None:
    request = make_prefilling("long", prompt_tokens=500)
    plan = DecodePriorityScheduler().plan([request], token_budget=64)
    assert len(plan.items) == 1
    assert plan.items[0].kind == WorkKind.PREFILL
    assert plan.items[0].tokens == 64


def test_balanced_scheduler_gives_prefill_progress_with_decoders_present() -> None:
    decoders = [make_decoding(f"decode-{index}") for index in range(4)]
    prefilling = make_prefilling("prefill", prompt_tokens=100)
    plan = BalancedScheduler().plan([*decoders, prefilling], token_budget=8)
    assert plan.scheduled_tokens <= 8
    assert any(item.kind == WorkKind.PREFILL for item in plan.items)
    assert any(item.kind == WorkKind.DECODE for item in plan.items)


@pytest.mark.parametrize("scheduler", [DecodePriorityScheduler(), BalancedScheduler()])
@pytest.mark.parametrize(
    ("decoder_count", "prefill_count", "budget", "prompt_tokens"),
    [
        (5, 0, 2, 10),
        (0, 4, 3, 10),
        (3, 3, 2, 10),
        (0, 1, 1, 500),
        (5, 5, 7, 100),
    ],
)
def test_scheduler_plans_never_exceed_budget(
    scheduler: DecodePriorityScheduler | BalancedScheduler,
    decoder_count: int,
    prefill_count: int,
    budget: int,
    prompt_tokens: int,
) -> None:
    requests = [make_decoding(f"decode-{index}") for index in range(decoder_count)]
    requests.extend(make_prefilling(f"prefill-{index}", prompt_tokens) for index in range(prefill_count))

    plan = scheduler.plan(requests, token_budget=budget)

    plan.validate()
    assert plan.scheduled_tokens <= budget
