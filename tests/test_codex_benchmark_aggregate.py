from middle_man.gateway.codex_benchmark.runner import aggregate_report


def _run(*, correct: bool, reads: int, input_tokens: int) -> dict:
    return {
        "correctness": correct,
        "test_exit_code": 0,
        "native": {"file_reads": reads, "rereads": 1, "search_calls": 2,
                   "listing_calls": 1, "unique_files": ["app/state.py"]},
        "codex_reported_usage": {"input_tokens": input_tokens, "cached_input_tokens": 10,
                                 "output_tokens": 3, "reasoning_output_tokens": 2,
                                 "total_tokens": None},
        "mcp_calls_by_tool": [("middleman_context_pack", 2)],
        "context": {"overlap_available": True, "unique_source_bytes": 12,
                    "repeated_source_bytes": 4, "pack_fingerprints": ["a", "b"],
                    "candidate_tokens": 50, "selected_tokens": 20,
                    "non_source_pack_overhead_estimate": 7},
    }


def test_aggregate_excludes_invalid_pairs_and_weights_overlap() -> None:
    valid = {"valid": True, "baseline": _run(correct=True, reads=4, input_tokens=100),
             "optimized": _run(correct=True, reads=2, input_tokens=80)}
    invalid = {"valid": False, "baseline": _run(correct=False, reads=999, input_tokens=999),
               "optimized": _run(correct=False, reads=999, input_tokens=999)}
    result = aggregate_report([valid, invalid])
    assert (result["total_pairs"], result["valid_pairs"], result["invalid_pairs"]) == (2, 1, 1)
    assert (result["baseline_successes"], result["optimized_successes"]) == (1, 1)
    assert (result["baseline_native_reads"], result["optimized_native_reads"]) == (4, 2)
    assert result["optimized_context_packs"] == 2
    assert result["optimized_mcp_calls"] == 2
    assert result["optimized_overlap_ratio"] == 0.25
    assert result["optimized_unique_source_tokens_estimate"] == 3
    assert result["baseline_codex_input_tokens"] == 100
    assert result["optimized_codex_total_tokens"] is None
