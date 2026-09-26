import pytest

from middle_man.lab.clock import VirtualClock
from middle_man.lab.config import LabConfig
from middle_man.lab.request import InferenceRequest, RequestState


def test_config_validates_positive_values() -> None:
    LabConfig(token_budget=1, max_active_sequences=1, kv_blocks=1, tokens_per_block=1).validate()
    with pytest.raises(ValueError):
        LabConfig(token_budget=0).validate()


def test_virtual_clock_advances_deterministically() -> None:
    clock = VirtualClock()
    clock.advance_ms(12.5)
    clock.advance_ms(2.5)
    assert clock.now_ms() == 15.0
    with pytest.raises(ValueError):
        clock.advance_ms(-1)


def test_request_lifecycle_prefill_then_decode() -> None:
    request = InferenceRequest("req-1", arrival_time_ms=10.0, prompt_tokens=4, max_output_tokens=2)
    request.mark_admitted()
    assert request.state == RequestState.PREFILLING
    request.apply_prefill(2)
    assert request.remaining_prompt_tokens == 2
    request.apply_prefill(2)
    assert request.state == RequestState.DECODING
    request.apply_decode(1, now_ms=20.0)
    assert request.first_token_time_ms == 20.0
    request.apply_decode(1, now_ms=21.0)
    assert request.state == RequestState.COMPLETED
    assert request.completion_time_ms == 21.0


def test_request_cannot_decode_before_prefill() -> None:
    request = InferenceRequest("req-1", arrival_time_ms=0.0, prompt_tokens=4, max_output_tokens=1)
    request.mark_admitted()
    with pytest.raises(ValueError):
        request.apply_decode(1, now_ms=1.0)
