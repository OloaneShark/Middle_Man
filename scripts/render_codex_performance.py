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


def _svg(width: int, height: int, title: str, description: str) -> ET.Element:
    root = ET.Element(f"{{{NS}}}svg", {"width": str(width), "height": str(height),
               "viewBox": f"0 0 {width} {height}", "role": "img",
               "aria-labelledby": "chart-title chart-description"})
    _element(root, "title", id="chart-title").text = title
    _element(root, "desc", id="chart-description").text = description
    _element(root, "rect", x=0, y=0, width=width, height=height, fill="#FFFFFF")
    return root


def input_chart(data: dict) -> ET.Element:
    rows = data["pairs"]
    svg = _svg(1030, 655, "Codex-reported input tokens by frozen pair",
               "Paired horizontal bars compare baseline and Middle_Man input tokens for five complete pairs. "
               "One anchor run has no optimized provider usage. Each row is an independent run, not a pooled estimate.")
    _text(svg, 28, 42, "Codex-reported input tokens", size=25, weight=700)
    _text(svg, 28, 68, "Independent frozen pairs | lower is less input within a pair", color=MUTED)
    _element(svg, "rect", x=30, y=83, width=14, height=10, fill=BASE)
    _text(svg, 51, 94, "Baseline", size=13)
    _element(svg, "rect", x=140, y=83, width=14, height=10, fill=GOOD)
    _text(svg, 161, 94, "Middle_Man lower", size=13)
    _element(svg, "rect", x=319, y=83, width=14, height=10, fill=BAD)
    _text(svg, 340, 94, "Middle_Man higher", size=13)
    max_value = max(max(row[side]["usage"]["input_tokens"] or 0 for side in ("baseline", "optimized"))
                    for row in rows if row["optimized"]["usage"]["input_tokens"] is not None)
    axis, extent = 282, 480
    for index, row in enumerate(rows):
        top = 112 + index * 84
        if index == 3:
            _element(svg, "line", x1=28, y1=top-10, x2=1000, y2=top-10, stroke=LINE, stroke_width=2)
        else:
            _element(svg, "line", x1=28, y1=top-10, x2=1000, y2=top-10, stroke=LINE)
        _text(svg, 28, top+11, row["label"], size=14, weight=700)
        _text(svg, 28, top+32, row["task_kind"] + " | " +
              ("PASS/PASS" if row["baseline"]["correct"] and row["optimized"]["correct"] else
               "FAIL/FAIL" if not row["baseline"]["correct"] and not row["optimized"]["correct"] else
               "PASS/FAIL"), size=12, color=MUTED)
        base = row["baseline"]["usage"]["input_tokens"]
        opt = row["optimized"]["usage"]["input_tokens"]
        if opt is None:
            _text(svg, axis, top+25, f"Baseline {number(base)}; optimized N/A (timeout)", color=MUTED)
            continue
        for offset, value, fill in ((14, base, BASE), (37, opt, GOOD if opt < base else BAD)):
            _element(svg, "rect", x=axis, y=top+offset, width=round(extent*value/max_value, 2),
                     height=12, rx=2, fill=fill)
            _text(svg, 780, top+offset+11, number(value), size=13, weight=700)
        _text(svg, 892, top+39, change(delta(base, opt)), size=15,
              color=GOOD if opt < base else BAD, weight=700)
    _text(svg, 28, 630, "Cached input is part of input, not an additional token count. Missing usage is not zero.",
          size=12, color=MUTED)
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
    return {"codex_input.svg": svg_text(input_chart(data)),
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
