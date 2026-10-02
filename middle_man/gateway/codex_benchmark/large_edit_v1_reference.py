"""Disposable-only reference implementation for the frozen large-edit fixture."""

from __future__ import annotations

from pathlib import Path


def _replace_once(root: Path, relative: str, before: str, after: str) -> None:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    if source.count(before) != 1:
        raise RuntimeError(f"reference solution source drift: {relative}")
    path.write_text(source.replace(before, after), encoding="utf-8")


def apply_reference_solution(root: Path) -> None:
    """Apply a known-good solution only to a disposable, unsolved snapshot."""
    _replace_once(
        root, "middle_man/lab/events.py",
        '    REQUEST_COMPLETED = "request_completed"\n',
        '    REQUEST_COMPLETED = "request_completed"\n'
        '    REQUEST_CANCELLED = "request_cancelled"\n',
    )
    _replace_once(
        root, "middle_man/lab/metrics.py",
        '    failed_requests: int\n',
        '    failed_requests: int\n'
        '    cancelled_requests: int\n',
    )
    _replace_once(
        root, "middle_man/lab/metrics.py",
        '            failed_requests=sum(request.state == RequestState.FAILED for request in requests),\n',
        '            failed_requests=sum(request.state == RequestState.FAILED for request in requests),\n'
        '            cancelled_requests=sum(request.state == RequestState.CANCELLED for request in requests),\n',
    )
    _replace_once(
        root, "middle_man/lab/engine.py",
        'from dataclasses import dataclass\n',
        'from collections.abc import Iterable\n'
        'from dataclasses import dataclass\n',
    )
    _replace_once(
        root, "middle_man/lab/engine.py",
        '    def run(self, requests: list[InferenceRequest]) -> EngineResult:\n'
        '        by_id = {request.request_id: request for request in requests}\n'
        '        if len(by_id) != len(requests):\n'
        '            raise ValueError("request IDs must be unique")\n',
        '    def run(\n'
        '        self, requests: list[InferenceRequest], *,\n'
        '        cancel_request_ids: Iterable[str] = (),\n'
        '    ) -> EngineResult:\n'
        '        by_id = {request.request_id: request for request in requests}\n'
        '        if len(by_id) != len(requests):\n'
        '            raise ValueError("request IDs must be unique")\n'
        '        cancel_ids = set(cancel_request_ids)\n'
        '        if cancel_ids - by_id.keys():\n'
        '            raise ValueError("unknown cancellation request ID")\n',
    )
    _replace_once(
        root, "middle_man/lab/engine.py",
        '        pending = sorted(requests, key=lambda request: request.arrival_time_ms)\n',
        '        pending = sorted(\n'
        '            (request for request in requests if request.request_id not in cancel_ids),\n'
        '            key=lambda request: request.arrival_time_ms,\n'
        '        )\n',
    )
    _replace_once(
        root, "middle_man/lab/engine.py",
        '        start_ms = self.clock.now_ms()\n\n'
        '        try:\n',
        '        start_ms = self.clock.now_ms()\n'
        '        for request in requests:\n'
        '            if request.request_id in cancel_ids:\n'
        '                request.cancel()\n'
        '                freed = self.memory.release_request(request.request_id)\n'
        '                request.allocated_blocks.clear()\n'
        '                request.shared_blocks.clear()\n'
        '                if freed:\n'
        '                    collector.sample(start_ms)\n'
        '                events.append(SimulationEvent(\n'
        '                    EventType.REQUEST_CANCELLED, start_ms, request.request_id\n'
        '                ))\n\n'
        '        try:\n',
    )
    _replace_once(
        root, "tests/test_batch_cancellation.py",
        'class ExistingSimulationTests(unittest.TestCase):\n',
        'class ExistingSimulationTests(unittest.TestCase):\n'
        '    def test_cancelled_request_does_not_run(self):\n'
        '        requests = [InferenceRequest("cancel", 0.0, 5, 2),\n'
        '                    InferenceRequest("keep", 0.0, 3, 1)]\n'
        '        result = SimulationEngine().run(requests, cancel_request_ids=("cancel",))\n'
        '        self.assertEqual(requests[0].state, RequestState.CANCELLED)\n'
        '        self.assertEqual(requests[1].state, RequestState.COMPLETED)\n'
        '        self.assertEqual(result.metrics.aggregate.cancelled_requests, 1)\n\n',
    )
