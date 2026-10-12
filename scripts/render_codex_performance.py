"""Render source-hashed, sanitized Phase 22 Codex observations as static SVGs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data" / "codex_performance.json"
ASSETS = ROOT / "docs" / "assets"
SOURCE = ROOT / ".middle_man_cache" / "codex_benchmarks"

# These are hashes of the frozen, ignored result.json files, not model outputs.
PAIRS = (
    ("20260930T102955Z-ea96eff7", "b6d3f5065a0d6fc98f810c343d913b958e0895e8093b41b0a12612d32d400309",
     "Task A v4 / MCP one-shot", "read-only", "mcp", "preemption-v4"),
    ("20261001T135609Z-65fcdc63", "feba63d045f3cf1dafb92f3734500afa68622e8a3a527999c486b1b02cd6a304",
     "Task A v4 / MCP progressive", "read-only", "mcp", "preemption-v4"),
    ("20261001T161512Z-015fde5e", "eb46c76fb93be4841b6c364f40e7e3043cb720a49b9bc5a6a81804f9b31c9b13",
     "Task A v4 / offline locator", "read-only", "offline-locator", "preemption-v4"),
    ("20261002T005428Z-70b36999", "298f577535fdd596e953c9d424dcdd0cf0ec36798d7b7016456d89d3408b18ab",
     "OAuth / forced locator", "edit", "offline-locator", "oauth-bug"),
    ("20261002T123023Z-ca9cd316", "f3140dd65d2a3d6eb46cb23a8e993995d8d80182ef4337f8e1a3cd22b8101bfe",
     "Large edit / full locator", "edit", "offline-auto", "large-edit-v1"),
    ("20261002T172314Z-4e89870f", "cd8d2bda259de21ee99b75f199a85cd6d909202ce0232cb059cd424ae69180f5",
     "Large edit / compact anchors", "edit", "offline-anchor", "large-edit-v1"),
)
USAGE = ("input_tokens", "cached_input_tokens", "output_tokens")
INK = "#202C33"
MUTED = "#5B6870"
BASE = "#66727C"
GOOD = "#087E72"
BAD = "#B44C39"
LINE = "#DCE3E5"
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


def extract(source: Path = SOURCE) -> dict:
    """Copy only numeric/boolean metrics from exact frozen records."""
    rows = []
    for run_id, digest, label, kind, mode, task_id in PAIRS:
        path = source / run_id / "result.json"
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Frozen result hash mismatch: {run_id}")
        record = json.loads(raw)
        if len(record["pairs"]) != 1 or record["pairs"][0]["task_id"] != task_id:
            raise ValueError(f"Unexpected task or pair count: {run_id}")
        pair = record["pairs"][0]
        if not pair["valid"] or record.get("optimized_mode", "mcp") != mode:
            raise ValueError(f"Invalid pair or delivery mode: {run_id}")

        def side(name: str) -> dict:
            item = pair[name]
            if not item["valid"]:
                raise ValueError(f"Invalid {name} side: {run_id}")
            usage = {key: item["codex_reported_usage"].get(key) for key in USAGE}
            if any(value is not None and (type(value) is not int or value < 0)
                   for value in usage.values()):
                raise ValueError(f"Invalid provider usage: {run_id}")
            calls = item["native"]["tool_calls"]
            reads = item["native"]["file_reads"]
            elapsed = item["elapsed_seconds"]
            if (type(calls) is not int or type(reads) is not int or calls < 0 or reads < 0
                    or not isinstance(elapsed, (int, float)) or elapsed < 0):
                raise ValueError(f"Invalid exploration metrics: {run_id}")
            return {
                "correct": item["correctness"],
                "usage": usage,
                "native_calls": calls,
                "explicit_file_reads": reads,
                "elapsed_seconds": elapsed,
                "mcp_calls": sum(count for _, count in item["mcp_calls_by_tool"]),
            }

        optimized = pair["optimized"]
        if mode == "mcp":
            local_type = "initial MCP result estimate"
            local_tokens = optimized["context"]["pack_result_tokens"]
        elif mode == "offline-anchor":
            local_type = "anchor text estimate"
            local_tokens = optimized["offline_anchor_audit"]["anchor_estimated_tokens"]
        else:
            local_type = "locator text estimate"
            local_tokens = optimized["offline_locator_audit"]["locator_estimated_tokens"]
        rows.append({
            "run_id": run_id, "result_sha256": digest, "label": label,
            "task_id": task_id, "task_kind": kind, "delivery_mode": mode,
            "quality_gate": pair["quality_gate"],
            "local_estimate": {"kind": local_type, "tokens": local_tokens},
            "baseline": side("baseline"), "optimized": side("optimized"),
        })
    return {"schema_version": 1, "pairs": rows}


def delta(base: int | float | None, optimized: int | float | None) -> float | None:
    if base is None or optimized is None or base == 0:
        return None
    return (optimized - base) * 100 / base


def number(value: int | float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.3f}" if isinstance(value, float) else f"{value:,}"


def change(value: float | None) -> str:
    return "N/A" if value is None else "0.0%" if value == 0 else f"{value:+.1f}%"


def _element(parent: ET.Element, kind: str, **attributes: object) -> ET.Element:
    return ET.SubElement(parent, f"{{{NS}}}{kind}", {key.replace("_", "-"): str(value)
                                                  for key, value in attributes.items()})


def _text(parent: ET.Element, x: int | float, y: int | float, content: str,
          *, size: int = 14, color: str = INK, weight: int = 400) -> None:
    _element(parent, "text", x=x, y=y, fill=color, font_family="Arial, sans-serif",
             font_size=size, font_weight=weight).text = content


def _svg(width: int, height: int, title: str, description: str,
         *, background: str = "#FFFFFF") -> ET.Element:
    root = ET.Element(f"{{{NS}}}svg", {"width": str(width), "height": str(height),
               "viewBox": f"0 0 {width} {height}", "role": "img",
               "aria-labelledby": "chart-title chart-description"})
    _element(root, "title", id="chart-title").text = title
    _element(root, "desc", id="chart-description").text = description
    _element(root, "rect", x=0, y=0, width=width, height=height, fill=background)
    return root


def highlight_chart(data: dict) -> ET.Element:
    row = next(item for item in data["pairs"] if item["task_id"] == "preemption-v4"
               and item["delivery_mode"] == "offline-locator")
    baseline, optimized = row["baseline"], row["optimized"]
    before, after = (side["usage"]["input_tokens"] for side in (baseline, optimized))
    if (before is None or after is None or before <= after
            or not (baseline["correct"] and optimized["correct"])):
        raise ValueError("Featured locator pair needs reduced reported usage and PASS/PASS correctness")
    green, white, muted, border = "#67E6A5", "#F5FAFC", "#B9C9D1", "#344C57"
    svg = _svg(800, 426, "Task A v4 offline-locator recorded improvement",
               f"One read-only Task A v4 pair: Codex-reported input fell from {number(before)} to "
               f"{number(after)} tokens, {number(before-after)} fewer or {abs(delta(before, after)):.1f}%. "
               f"Native tool calls were {baseline['native_calls']} to {optimized['native_calls']}; "
               f"elapsed time was {number(baseline['elapsed_seconds'])} to "
               f"{number(optimized['elapsed_seconds'])} seconds. Both structured answers passed. "
               "This is one observation, not a general guarantee.", background="#101C24")
    _element(svg, "rect", x=1, y=1, width=798, height=424, fill="none", stroke=border)
    _text(svg, 32, 38, "RECORDED PERFORMANCE  /  READ-ONLY TASK A v4", size=15,
          color=muted, weight=700)
    _text(svg, 32, 114, f"{abs(delta(before, after)):.1f}%", size=68, color=green, weight=700)
    _text(svg, 280, 96, "fewer input tokens", size=28, color=white, weight=700)
    _text(svg, 282, 126, f"{number(before-after)} fewer Codex-reported tokens", size=17,
          color=muted)

    bar_x, bar_width = 192, 456
    for y, label, value, fill in ((174, "Baseline", before, "#718895"),
                                  (223, "Middle_Man", after, green)):
        _text(svg, 32, y+17, label, size=17, color=white, weight=700)
        _element(svg, "rect", x=bar_x, y=y, width=bar_width, height=22, fill="#293B46")
        _element(svg, "rect", x=bar_x, y=y, width=round(bar_width*value/before, 2),
                 height=22, fill=fill)
        _text(svg, 672, y+18, number(value), size=18, color=white, weight=700)

    _element(svg, "line", x1=32, y1=277, x2=768, y2=277, stroke=border)
    indicators = (
        (32, "INPUT TOKENS", f"-{number(before-after)}",
         f"{abs(delta(before, after)):.1f}% less"),
        (282, "NATIVE TOOL CALLS", f"{baseline['native_calls']} -> {optimized['native_calls']}",
         f"{abs(delta(baseline['native_calls'], optimized['native_calls'])):.1f}% fewer"),
        (532, "EXECUTION TIME", f"{number(baseline['elapsed_seconds'])}s -> "
         f"{number(optimized['elapsed_seconds'])}s",
         f"{abs(delta(baseline['elapsed_seconds'], optimized['elapsed_seconds'])):.1f}% shorter"),
    )
    for x, label, value, detail in indicators:
        _text(svg, x, 306, label, size=14, color=muted, weight=700)
        _text(svg, x, 343, value, size=22 if label != "EXECUTION TIME" else 19,
              color=white, weight=700)
        _text(svg, x, 365, detail, size=14, color=green)
    _text(svg, 32, 395, "STRUCTURED CORRECTNESS", size=14, color=muted, weight=700)
    _text(svg, 282, 395, "PASS / PASS", size=18, color=green, weight=700)
    _text(svg, 768, 395, "ONE RECORDED PAIR  /  NOT A GENERAL GUARANTEE", size=12,
          color=muted, weight=700)
    svg[-1].set("text-anchor", "end")
    return svg


def input_chart(data: dict) -> ET.Element:
    rows = data["pairs"]
    groups = (
        ("READ-ONLY REPOSITORY NAVIGATION", [row for row in rows if row["task_kind"] == "read-only"
                                               and row["delivery_mode"] == "offline-locator"]),
        ("HISTORICAL MCP DELIVERY", [row for row in rows if row["delivery_mode"] == "mcp"]),
        ("EDIT-TASK EXPERIMENTS (HISTORICAL)", [row for row in rows if row["task_kind"] == "edit"]),
    )
    if sum(len(group) for _, group in groups) != len(rows):
        raise ValueError("Uncategorized performance pair")
    svg = _svg(800, 743, "Codex input changes across six independent frozen pairs",
               "Grouped comparison of read-only offline navigation, historical MCP delivery, and edit-task "
               "experiments. One offline pair used fewer input tokens; MCP and two edit pairs "
               "used more. A timed-out edit run has no optimized token measurement. Bars show signed "
               "within-pair percentage changes on one shared scale from minus 100 to plus 100 percent.")
    _element(svg, "rect", x=1, y=1, width=798, height=741, fill="none", stroke=LINE)
    _text(svg, 28, 42, "Input-token change by experiment", size=25, weight=700)
    _text(svg, 28, 69, "Codex-reported usage | independent pairs, not pooled savings", color=MUTED)
    _text(svg, 320, 101, "-100%  /  fewer", size=13, color=GOOD, weight=700)
    _text(svg, 495, 101, "0", size=13, color=MUTED)
    _text(svg, 604, 101, "+100%  /  more", size=13, color=BAD, weight=700)
    axis, extent, top = 500, 150, 120
    for heading, group in groups:
        _element(svg, "rect", x=20, y=top, width=760, height=30, fill="#EBF1F3")
        _text(svg, 28, top+21, heading, size=14, weight=700)
        top += 34
        for row in group:
            base = row["baseline"]["usage"]["input_tokens"]
            opt = row["optimized"]["usage"]["input_tokens"]
            pct = delta(base, opt)
            outcome = ("PASS / PASS" if row["baseline"]["correct"] and row["optimized"]["correct"]
                       else "FAIL / FAIL" if not row["baseline"]["correct"] and not row["optimized"]["correct"]
                       else "PASS / FAIL")
            _text(svg, 28, top+19, row["label"], size=15, weight=700)
            _text(svg, 28, top+41, outcome + (" (timeout)" if opt is None else ""), size=13,
                  color=BAD if outcome != "PASS / PASS" else GOOD, weight=700)
            _text(svg, 320, top+19, f"{number(base)} -> {number(opt)} input", size=14, weight=700)
            _text(svg, 758, top+19, change(pct), size=17,
                  color=MUTED if pct is None else GOOD if pct < 0 else BAD, weight=700)
            svg[-1].set("text-anchor", "end")
            _element(svg, "line", x1=axis-extent, y1=top+49, x2=axis+extent, y2=top+49,
                     stroke=LINE, stroke_width=8)
            _element(svg, "line", x1=axis, y1=top+38, x2=axis, y2=top+60,
                     stroke="#677880", stroke_width=2)
            if pct is not None:
                _element(svg, "rect", x=axis+min(0, pct)*extent/100, y=top+44,
                         width=abs(pct)*extent/100, height=10,
                         fill=GOOD if pct < 0 else BAD)
            top += 75
        top += 12
    _text(svg, 28, 718, "Edit hints are historical; current AUTO bypasses edits. N/A is unreported, not zero.",
          size=13, color=MUTED)
    return svg


def metric_chart(data: dict) -> ET.Element:
    svg = _svg(1230, 665, "Cached and output usage, native exploration, duration, and correctness",
               "A color-coded matrix shows baseline to Middle_Man values and within-pair percentage change. "
               "Green means lower measured usage; red means higher. Missing provider usage is marked N/A.")
    _text(svg, 25, 42, "Usage, exploration, time and correctness", size=24, weight=700)
    _text(svg, 25, 67, "B = baseline; M = Middle_Man | each percentage compares only its own pair", color=MUTED)
    columns = (("Cached input", lambda s: s["usage"]["cached_input_tokens"]),
               ("Output", lambda s: s["usage"]["output_tokens"]),
               ("Native calls", lambda s: s["native_calls"]),
               ("File reads", lambda s: s["explicit_file_reads"]),
               ("Duration (s)", lambda s: s["elapsed_seconds"]))
    left, step = 249, 164
    for idx, (title, _) in enumerate(columns):
        _text(svg, left+idx*step+8, 113, title, size=14, weight=700)
    _text(svg, 1082, 113, "Correctness", size=14, weight=700)
    for index, row in enumerate(data["pairs"]):
        top = 126 + index*81
        _element(svg, "line", x1=25, y1=top, x2=1200, y2=top, stroke=LINE,
                 stroke_width=2 if index == 3 else 1)
        _text(svg, 25, top+29, row["label"], size=13, weight=700)
        _text(svg, 25, top+49, row["task_kind"], size=12, color=MUTED)
        for col, (_, get) in enumerate(columns):
            base, opt = get(row["baseline"]), get(row["optimized"])
            pct = delta(base, opt)
            color = MUTED if pct is None or pct == 0 else GOOD if pct < 0 else BAD
            x = left+col*step
            _element(svg, "rect", x=x, y=top+9, width=156, height=61, rx=4,
                     fill="#EDF7F5" if pct is not None and pct < 0 else
                          "#FBEFEC" if pct is not None and pct > 0 else "#F2F4F5")
            _text(svg, x+8, top+34, f"{number(base)} → {number(opt)}", size=12, weight=700)
            _text(svg, x+8, top+56, change(pct), size=13, color=color, weight=700)
        outcome = ("PASS / PASS" if row["baseline"]["correct"] and row["optimized"]["correct"] else
                   "FAIL / FAIL" if not row["baseline"]["correct"] and not row["optimized"]["correct"] else
                   "PASS / FAIL")
        _text(svg, 1082, top+39, outcome, size=13,
              color=BAD if outcome != "PASS / PASS" else GOOD, weight=700)
    _text(svg, 25, 641, "Green/red describes measured direction, not answer quality or causal attribution.",
          size=12, color=MUTED)
    return svg


def svg_text(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def render(data: dict) -> dict[str, str]:
    if data.get("schema_version") != 1 or [row.get("run_id") for row in data.get("pairs", [])] != [p[0] for p in PAIRS]:
        raise ValueError("Unexpected performance dataset")
    for row, expected in zip(data["pairs"], PAIRS):
        if row.get("result_sha256") != expected[1]:
            raise ValueError(f"Result provenance mismatch: {expected[0]}")
    return {"codex_highlight.svg": svg_text(highlight_chart(data)),
            "codex_input.svg": svg_text(input_chart(data)),
            "codex_metrics.svg": svg_text(metric_chart(data))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true", help="Refresh sanitized data from exact local frozen result hashes")
    parser.add_argument("--check", action="store_true", help="Compare generated output without writing files")
    args = parser.parse_args()
    if args.extract:
        extracted = json.dumps(extract(), indent=2, sort_keys=True) + "\n"
        if args.check:
            if DATA.read_text(encoding="utf-8") != extracted:
                raise SystemExit("Sanitized data differs from frozen results")
        else:
            DATA.parent.mkdir(parents=True, exist_ok=True)
            DATA.write_text(extracted, encoding="utf-8")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    for filename, content in render(data).items():
        path = ASSETS / filename
        if args.check:
            if path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Generated chart differs: {filename}")
        else:
            ASSETS.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
