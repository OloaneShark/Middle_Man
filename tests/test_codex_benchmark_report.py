from middle_man.gateway.codex_benchmark.runner import aggregate_report, format_report


def test_invalid_pairs_have_no_aggregate_or_numeric_comparison() -> None:
    data = {
        "run_id": "test-run",
        "codex_version": "codex-test",
        "model": "test-model",
        "effort": "high",
        "planned_task_ids": ["a", "b"],
        "pairs": [{
            "title": "Invalid task",
            "valid": False,
            "quality_gate": "INVALID_INFRASTRUCTURE",
            "baseline": {"warnings": ["baseline contaminated"], "correctness_notes": []},
            "optimized": {"warnings": ["wrong MCP root"], "correctness_notes": []},
        }],
    }
    aggregate = aggregate_report(data["pairs"])
    assert aggregate["valid_pairs"] == 0
    assert aggregate["baseline_codex_input_tokens"] is None
    report = format_report(data)
    assert "Invalid A/B pair; diagnostics only" in report
    assert "Incomplete suite: 1/2 pairs completed" in report
    assert "Native reads:" not in report
    assert "Codex-reported input/output:" not in report
