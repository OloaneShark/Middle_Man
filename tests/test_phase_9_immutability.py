import csv
from dataclasses import FrozenInstanceError

import pytest

from middle_man.lab.request import InferenceRequest
from middle_man.lab.serialization import save_csv
from middle_man.lab.suites import build_suite
from middle_man.lab.workloads import RequestSpec, WorkloadSpec


def test_workload_rejects_mutable_request_objects() -> None:
    mutable = InferenceRequest("mutable", 0.0, 1, 1)
    with pytest.raises(TypeError, match="RequestSpec"):
        WorkloadSpec("invalid", "", 7, (mutable,))
    with pytest.raises(TypeError, match="tuple"):
        WorkloadSpec("invalid", "", 7, [RequestSpec("immutable", 0.0, 1, 1)])

    spec = RequestSpec("immutable", 0.0, 1, 1)
    with pytest.raises(FrozenInstanceError):
        spec.prompt_tokens = 99


def test_csv_contains_all_lab_configuration_fields(tmp_path) -> None:
    result = build_suite("mixed", seed=31).run()
    destination = save_csv(result, tmp_path)
    with destination.open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))

    assert row["random_seed"] == "31"
    assert row["debug"] == "False"
    assert row["runner_costs"].startswith("{")
