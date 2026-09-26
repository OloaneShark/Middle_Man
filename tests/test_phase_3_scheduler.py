from middle_man.lab.request import InferenceRequest
from middle_man.lab.scheduler import BalancedScheduler, DecodePriorityScheduler
from middle_man.lab.work import WorkKind


def make_prefilling(request_id: str, prompt_tokens: int) -> InferenceRequest:
    request = InferenceRequest(request_id, 0.0, prompt_tokens=prompt_tokens, max_output_tokens=4)
    request.mark_admitted()
    return request


def make_decoding(request_id: str) -> InferenceRequest:
    request = InferenceRequest(request_id, 0.0, prompt_tokens=2, max_output_tokens=4)
    request.mark_admitted()
    request.apply_prefill(2)
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
