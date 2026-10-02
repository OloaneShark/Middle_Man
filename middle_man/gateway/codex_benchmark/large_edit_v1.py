"""Frozen Lab batch-cancellation edit task and independent acceptance contract."""

from __future__ import annotations

from textwrap import dedent


FIXTURE_PATHS = (
    "middle_man/__init__.py",
    *(f"middle_man/lab/{name}.py" for name in (
        "__init__", "benchmarks", "clock", "comparison", "config", "engine",
        "events", "memory", "memory_control", "metrics", "preemption",
        "prefix_cache", "reporting", "request", "runner", "scheduler",
        "serialization", "suites", "trace", "visualization", "work", "workloads",
    )),
    *(f"tests/test_phase_{phase}_{name}.py" for phase, name in (
        (1, "core"), (2, "memory"), (3, "scheduler"), (5, "continuous_batching"),
        (6, "metrics"), (7, "preemption"),
    )),
)

VISIBLE_TEST_PATH = "tests/test_batch_cancellation.py"
VISIBLE_TEST = dedent('''\
    import unittest

    from middle_man.lab.engine import SimulationEngine
    from middle_man.lab.request import InferenceRequest, RequestState


    class ExistingSimulationTests(unittest.TestCase):
        def test_uncancelled_requests_complete(self):
            requests = [
                InferenceRequest("first", 0.0, 4, 2),
                InferenceRequest("second", 1.0, 3, 1),
            ]
            result = SimulationEngine().run(requests)
            self.assertEqual([item.state for item in result.requests],
                             [RequestState.COMPLETED, RequestState.COMPLETED])
            self.assertEqual(result.metrics.aggregate.completed_requests, 2)
    ''')

PROMPT = (
    "Add batch cancellation to the simulation engine. A caller may pass "
    "cancel_request_ids when starting a run. Before changing any request or engine state, "
    "reject unknown cancellation IDs with ValueError. At simulation start, cancel each "
    "requested ID once (duplicates count once) in input-request order; emit exactly one "
    "cancellation event for each at the start time. Never admit, execute, or allocate KV "
    "for those requests; keep their token counts and timing fields untouched. Other "
    "requests must continue normally, including when all requests are cancelled. Report "
    "the number of cancelled requests in aggregate metrics and keep trace output "
    "consistent with the new events. With no cancellation IDs, existing behavior must "
    "be unchanged. Add or adjust visible tests and run the test suite."
)

ACCEPTANCE_TEST = dedent('''\
    import unittest
    from dataclasses import asdict

    from middle_man.lab.config import LabConfig
    from middle_man.lab.engine import SimulationEngine
    from middle_man.lab.events import EventType
    from middle_man.lab.request import InferenceRequest, RequestState


    class IndependentCancellationAcceptance(unittest.TestCase):
        def test_unknown_id_is_rejected_before_mutation(self):
            request = InferenceRequest("known", 0.0, 4, 2)
            engine = SimulationEngine()
            with self.assertRaises(ValueError):
                engine.run([request], cancel_request_ids=("missing",))
            self.assertEqual(request.state, RequestState.QUEUED)
            self.assertEqual(request.prompt_processed, 0)
            self.assertEqual(engine.iterations, 0)
            self.assertEqual(engine.memory.snapshot().used_blocks, 0)

        def test_cancellation_is_ordered_unique_and_source_of_truth(self):
            requests = [
                InferenceRequest("late", 100.0, 8, 3),
                InferenceRequest("normal", 0.0, 3, 2),
                InferenceRequest("early", 0.0, 5, 1),
            ]
            result = SimulationEngine().run(
                requests, cancel_request_ids=("early", "late", "early"))
            self.assertEqual([item.request_id for item in result.requests
                              if item.state == RequestState.CANCELLED], ["late", "early"])
            cancelled = [event for event in result.events
                         if event.kind == EventType.REQUEST_CANCELLED]
            self.assertEqual([event.request_id for event in cancelled], ["late", "early"])
            self.assertEqual([event.time_ms for event in cancelled], [0.0, 0.0])
            for request in (requests[0], requests[2]):
                self.assertEqual((request.prompt_processed, request.output_generated), (0, 0))
                self.assertIsNone(request.first_token_time_ms)
                self.assertIsNone(request.completion_time_ms)
                self.assertEqual(request.allocated_blocks, [])
                self.assertEqual(request.shared_blocks, [])
                self.assertFalse(any(
                    event.request_id == request.request_id and event.kind in {
                        EventType.REQUEST_ADMITTED, EventType.PREFILL_EXECUTED,
                        EventType.DECODE_EXECUTED, EventType.KV_ALLOCATED,
                    } for event in result.events))
            self.assertEqual(requests[1].state, RequestState.COMPLETED)
            self.assertEqual(result.metrics.aggregate.cancelled_requests, 2)
            self.assertEqual(result.metrics.aggregate.completed_requests, 1)
            self.assertEqual(result.metrics.aggregate.total_requests, 3)
            self.assertEqual(result.metrics.aggregate.total_prompt_tokens_processed, 3)
            self.assertEqual(result.metrics.aggregate.total_output_tokens_generated, 2)

        def test_all_cancelled_has_no_work_and_no_kv(self):
            engine = SimulationEngine(LabConfig(prefix_cache_enabled=True))
            request = InferenceRequest("alone", 12.0, 16, 4,
                                       shared_prefix_tokens=8, prefix_key="p")
            result = engine.run([request], cancel_request_ids={"alone"})
            self.assertEqual(request.state, RequestState.CANCELLED)
            self.assertEqual(result.iterations, 0)
            self.assertEqual(result.metrics.aggregate.cancelled_requests, 1)
            self.assertEqual(result.metrics.aggregate.completed_requests, 0)
            self.assertEqual(engine.memory.snapshot().used_blocks, 0)
            self.assertEqual([event.kind for event in result.events],
                             [EventType.REQUEST_CANCELLED])

        def test_default_run_and_serialized_metric(self):
            request = InferenceRequest("ordinary", 0.0, 2, 1)
            result = SimulationEngine().run([request])
            self.assertEqual(request.state, RequestState.COMPLETED)
            self.assertEqual(asdict(result.metrics.aggregate)["cancelled_requests"], 0)
            self.assertFalse(any(event.kind == EventType.REQUEST_CANCELLED
                                 for event in result.events))
    ''')
