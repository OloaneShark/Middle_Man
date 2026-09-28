from middle_man.lab.config import LabConfig
from middle_man.lab.engine import SimulationEngine
from middle_man.lab.events import EventType
from middle_man.lab.request import InferenceRequest, RequestState


def test_later_request_enters_while_long_request_is_unfinished() -> None:
    engine = SimulationEngine(LabConfig(token_budget=4, max_active_sequences=2))
    requests = [
        InferenceRequest("long", 0.0, prompt_tokens=2, max_output_tokens=10),
        InferenceRequest("short", 0.0, prompt_tokens=2, max_output_tokens=1),
        InferenceRequest("later", 2.0, prompt_tokens=2, max_output_tokens=1),
    ]

    result = engine.run(requests)
    events = result.events
    short_done = next(index for index, event in enumerate(events)
                      if event.kind == EventType.REQUEST_COMPLETED and event.request_id == "short")
    later_entered = next(index for index, event in enumerate(events)
                         if event.kind == EventType.REQUEST_ADMITTED and event.request_id == "later")
    long_done = next(index for index, event in enumerate(events)
                     if event.kind == EventType.REQUEST_COMPLETED and event.request_id == "long")

    assert short_done < later_entered < long_done
    assert events[later_entered].time_ms >= 2.0
    assert any(event.kind == EventType.DECODE_EXECUTED and event.request_id == "long"
               for event in events[later_entered:long_done])
    assert all(request.state == RequestState.COMPLETED for request in requests)
    assert engine.memory.free_block_count == engine.memory.total_blocks
