import random

import pytest

from middle_man.lab.request import RequestState
from middle_man.lab.workloads import WorkloadPreset, make_workload


@pytest.mark.parametrize("preset", list(WorkloadPreset))
def test_each_preset_creates_fresh_requests(preset: WorkloadPreset) -> None:
    workload = make_workload(preset, seed=23)
    first = workload.create_requests()
    second = workload.create_requests()

    assert workload.requests
    assert len({spec.request_id for spec in workload.requests}) == len(workload.requests)
    assert first == second
    assert all(left is not right for left, right in zip(first, second))
    assert all(request.state == RequestState.QUEUED for request in second)


def test_workload_seed_is_deterministic_without_global_random_mutation() -> None:
    before = random.getstate()
    first = make_workload(WorkloadPreset.SHORT_CHAT, seed=11)
    second = make_workload(WorkloadPreset.SHORT_CHAT, seed=11)
    different = make_workload(WorkloadPreset.SHORT_CHAT, seed=12)

    assert first == second
    assert first.requests != different.requests
    assert random.getstate() == before
