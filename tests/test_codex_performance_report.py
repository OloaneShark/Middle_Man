"""Keep the static performance report tied to exact frozen observations."""

from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts.render_codex_performance import ASSETS, DATA, PAIRS, ROOT, SOURCE, change, delta, extract, number, render


def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_source_hashed_snapshot_and_key_outcomes() -> None:
    data = _data()
    assert [row["run_id"] for row in data["pairs"]] == [item[0] for item in PAIRS]
    assert [row["result_sha256"] for row in data["pairs"]] == [item[1] for item in PAIRS]
    assert [row["task_kind"] for row in data["pairs"]] == ["read-only"] * 3 + ["edit"] * 3
    task_a, large_edit, anchors = data["pairs"][2], data["pairs"][4], data["pairs"][5]
    assert (task_a["baseline"]["usage"]["input_tokens"], task_a["optimized"]["usage"]["input_tokens"]) == (86515, 38269)
    assert round(delta(86515, 38269), 1) == -55.8
    assert task_a["baseline"]["correct"] and task_a["optimized"]["correct"]
    assert (large_edit["baseline"]["usage"]["input_tokens"], large_edit["optimized"]["usage"]["input_tokens"]) == (363533, 494991)
    assert round(delta(363533, 494991), 1) == 36.2
    assert anchors["optimized"]["usage"]["input_tokens"] is None
    assert anchors["baseline"]["correct"] and not anchors["optimized"]["correct"]
    assert all(row["optimized"]["usage"]["input_tokens"] > row["baseline"]["usage"]["input_tokens"]
               for row in data["pairs"][:2])
    serialized = DATA.read_text(encoding="utf-8")
    assert all(forbidden not in serialized for forbidden in
               ("final_message", "thread_id", "test_output", "redacted_task", "source_excerpt", "command_text"))


def test_exact_frozen_results_match_when_available(tmp_path: Path) -> None:
    if not (SOURCE / PAIRS[0][0] / "result.json").exists():
        pytest.skip("ignored Phase 22 records are not distributed")
    assert extract() == _data()
    for row in _data()["pairs"]:
        for side in ("baseline", "optimized"):
            paths = list((SOURCE / row["run_id"]).glob(f"*-{side}-events.json"))
            assert len(paths) == 1
            events = json.loads(paths[0].read_text(encoding="utf-8"))
            kinds = Counter(event.get("item_type") for event in events
                            if event.get("type") == "item.completed")
            assert kinds["command_execution"] == row[side]["native_calls"]
            assert kinds["mcp_tool_call"] == row[side]["mcp_calls"]
            turns = [event["usage"] for event in events if event.get("type") == "turn.completed"]
            if all(value is None for value in row[side]["usage"].values()):
                assert not turns
            else:
                assert len(turns) == 1
                assert all(turns[0][key] == value for key, value in row[side]["usage"].items())
    source = tmp_path / PAIRS[0][0]
    source.mkdir()
    (source / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen result hash mismatch"):
        extract(tmp_path)


def test_figures_are_deterministic_accessible_and_documented() -> None:
    data = _data()
    expected = render(data)
    for filename, content in expected.items():
        assert (ASSETS / filename).read_text(encoding="utf-8") == content
        svg = ET.fromstring(content)
        assert svg.attrib["role"] == "img"
        assert svg.attrib["aria-labelledby"] == "chart-title chart-description"
        assert svg.find("{http://www.w3.org/2000/svg}title") is not None
        assert svg.find("{http://www.w3.org/2000/svg}desc") is not None
        for row in data["pairs"]:
            assert row["label"] in content
    report = (ROOT / "docs" / "CODEX_PERFORMANCE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/assets/codex_input.svg" in readme
    assert "docs/CODEX_PERFORMANCE.md" in readme
    for row in data["pairs"]:
        lines = [line for line in report.splitlines() if line.startswith(f'| {row["label"]} |')]
        assert len(lines) == 2
        provider, exploration = lines
        assert row["run_id"] in DATA.read_text(encoding="utf-8")
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            pair = f'{number(row["baseline"]["usage"][key])} -> {number(row["optimized"]["usage"][key])}'
            assert pair in provider
        input_base = row["baseline"]["usage"]["input_tokens"]
        input_optimized = row["optimized"]["usage"]["input_tokens"]
        assert change(delta(input_base, input_optimized)) in provider
        for key in ("native_calls", "explicit_file_reads", "elapsed_seconds"):
            pair = f'{number(row["baseline"][key])} -> {number(row["optimized"][key])}'
            assert pair in exploration
            assert change(delta(row["baseline"][key], row["optimized"][key])) in exploration
