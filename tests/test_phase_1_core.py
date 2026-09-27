import pytest

from middle_man.lab.clock import VirtualClock
from middle_man.lab.config import LabConfig
from middle_man.lab.request import InferenceRequest, RequestState


def test_config_validates_positive_values() -> None:
    config = LabConfig(token_budget=1, max_active_sequences=1, kv_blocks=1, tokens_per_block=1)
    config.validate()
    assert config.prefix_cache_enabled is False
    assert config.preemption_enabled is False
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
    request.mark_admitted(now_ms=10.0)
    assert request.state == RequestState.PREFILLING
    request.apply_prefill(2, now_ms=12.0)
    assert request.remaining_prompt_tokens == 2
    request.apply_prefill(2, now_ms=14.0)
    assert request.state == RequestState.DECODING
    request.apply_decode(1, now_ms=20.0)
    assert request.first_token_time_ms == 20.0
    request.apply_decode(1, now_ms=21.0)
    assert request.state == RequestState.COMPLETED
    assert request.completion_time_ms == 21.0


def test_request_cannot_decode_before_prefill() -> None:
    request = InferenceRequest("req-1", arrival_time_ms=0.0, prompt_tokens=4, max_output_tokens=1)
    request.mark_admitted(now_ms=0.0)
    with pytest.raises(ValueError):
        request.apply_decode(1, now_ms=1.0)


def test_zero_prompt_request_can_decode_immediately() -> None:
    request = InferenceRequest("req-1", arrival_time_ms=5.0, prompt_tokens=0, max_output_tokens=2)
    request.mark_admitted(now_ms=5.0)
    assert request.state == RequestState.DECODING
    request.apply_decode(2, now_ms=6.0)
    assert request.state == RequestState.COMPLETED
    assert request.output_generated == 2


def test_zero_prompt_and_output_request_completes_on_admission() -> None:
    request = InferenceRequest("req-1", arrival_time_ms=5.0, prompt_tokens=0, max_output_tokens=0)
    request.mark_admitted(now_ms=7.0)
    assert request.state == RequestState.COMPLETED
    assert request.completion_time_ms == 7.0


def test_request_rejects_work_beyond_declared_token_limits() -> None:
    request = InferenceRequest("req-1", arrival_time_ms=0.0, prompt_tokens=2, max_output_tokens=1)
    request.mark_admitted(now_ms=0.0)
    with pytest.raises(ValueError):
        request.apply_prefill(3, now_ms=1.0)

    request.apply_prefill(2, now_ms=1.0)
    with pytest.raises(ValueError):
        request.apply_decode(2, now_ms=2.0)


def test_completed_request_cannot_resume_work() -> None:
    request = InferenceRequest("req-1", arrival_time_ms=0.0, prompt_tokens=1, max_output_tokens=1)
    request.mark_admitted(now_ms=0.0)
    request.apply_prefill(1, now_ms=1.0)
    request.apply_decode(1, now_ms=2.0)

    with pytest.raises(ValueError):
        request.apply_prefill(1, now_ms=3.0)
    with pytest.raises(ValueError):
        request.apply_decode(1, now_ms=3.0)
