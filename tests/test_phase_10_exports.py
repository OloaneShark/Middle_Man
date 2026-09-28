import csv
import json

import pytest

from middle_man.cli.main import main
from middle_man.lab.reporting import format_benchmark_suite
from middle_man.lab.suites import build_suite


def test_cli_writes_json_and_csv_under_selected_directory(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([
        "benchmark", "prefix-cache", "--seed", "17",
        "--json", "--csv", "--output-dir", str(tmp_path),
    ])
    output = capsys.readouterr().out
    json_path = tmp_path / "prefix-cache.json"
    csv_path = tmp_path / "prefix-cache.csv"

    assert "SIMULATED PERFORMANCE" in output
    assert json_path.is_file() and csv_path.is_file()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["metadata"]["simulated"] is True
    assert all(case["seed"] == 17 for case in data["suite"]["cases"])
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert all(row["final_kv_used_blocks"] == "0" for row in rows)


def test_chunked_prefill_report_uses_observed_work_events() -> None:
    result = build_suite("chunked-prefill").run()
    report = format_benchmark_suite(result)
    chunks = []
    for case in result.cases:
        count = sum(
            event.kind.value == "prefill_executed" and event.request_id == "long-02"
            for event in case.events
        )
        chunks.append(count)
        assert f"Long prompt long-02: {count} prefill chunks" in report
    assert chunks[0] > chunks[1]
