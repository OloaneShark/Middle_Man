"""Validate AI-proposed references against pinned Git source, without locator runs."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections import Counter
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "docs/a_plus_ai_proposed_references.json"
PACKET = ROOT / "docs/a_plus_blinded_review_packet.json"
COMMIT = "8a6dca9e3cfadd144f14e860d182ec44ac0faedc"
TREE = "467f280dfc781897099d726085974223cf9d6754"
PACKET_SHA256 = "a6cc580cbc71b88c55619095c39f322cec7180cdfed8368efff72518734eebdb"
REFERENCE_SHA256 = "d9511d4d626e900faf570953fe6a80443217f086f00c9d62bb47ec2cff490b1c"


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", timeout=15,
    ).strip()


@lru_cache(maxsize=None)
def _pinned_source(path: str) -> str:
    return _git("show", f"{COMMIT}:{path}")


@lru_cache(maxsize=None)
def _symbols(path: str) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for node in ast.parse(_pinned_source(path)).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result[node.name] = (node.lineno, node.end_lineno)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        result[f"{node.name}.{child.name}"] = (child.lineno, child.end_lineno)
    return result


def _canonical_hash(value: object) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _load() -> tuple[dict, dict]:
    return (json.loads(REFERENCES.read_text(encoding="utf-8")),
            json.loads(PACKET.read_text(encoding="utf-8")))


def test_dataset_identity_and_one_pass_status() -> None:
    references, packet = _load()
    assert _git("rev-parse", f"{COMMIT}^{{tree}}") == TREE
    assert references["schema"] == "middle_man.a_plus_ai_proposed_references.v1"
    assert references["status"] == "AI_PROPOSED_SOURCE_GROUNDED_NOT_HUMAN_VALIDATED"
    assert "one AI-assisted" in references["review_method"]
    assert references["source"] == packet["source"] == {"commit": COMMIT, "tree": TREE}
    assert references["packet_canonical_sha256"] == _canonical_hash(packet) == PACKET_SHA256
    assert references["reference_sha256"] == _canonical_hash(references["tasks"]) == REFERENCE_SHA256
    assert len(references["tasks"]) == len(packet["tasks"]) == 16
    assert [item["task_id"] for item in references["tasks"]] == [
        item["task_id"] for item in packet["tasks"]
    ]
    assert Counter(item["reference_status"] for item in references["tasks"]) == {
        "COMPLETE_PROPOSED": 10, "PARTIAL_UNRESOLVED": 6,
    }
    for reference, task in zip(references["tasks"], packet["tasks"], strict=True):
        assert reference["task_sha256"] == task["sha256"]
        assert hashlib.sha256(task["task"].encode("utf-8")).hexdigest() == task["sha256"]
        assert reference["source_grounded_summary"]
        assert reference["areas"] and reference["supporting_tests"]
        assert len({area["area"] for area in reference["areas"]}) == len(reference["areas"])
        if reference["reference_status"] == "PARTIAL_UNRESOLVED":
            assert reference["unresolved_interpretations"]


def test_every_evidence_span_is_real_at_pinned_source() -> None:
    references, _ = _load()
    tracked = set(_git("ls-tree", "-r", "--name-only", COMMIT).splitlines())
    for task in references["tasks"]:
        for area in task["areas"]:
            assert area["area"] and area["explanation"]
            assert area["alternatives"]
            for option in area["alternatives"]:
                assert option
        spans = [span for area in task["areas"] for option in area["alternatives"]
                 for span in option] + task["supporting_tests"]
        for span in spans:
            assert isinstance(span, list) and len(span) == 4
            path, symbol, first, last = span
            assert isinstance(path, str) and path in tracked and path.endswith(".py")
            assert path.startswith(("middle_man/", "tests/"))
            assert path not in {".", ".."} and ".." not in Path(path).parts
            assert isinstance(symbol, str) and symbol in _symbols(path)
            assert (first, last) == _symbols(path)[symbol]
            assert 1 <= first <= last <= len(_pinned_source(path).splitlines())
        assert all(span[0].startswith("tests/") and span[1].startswith("test_")
                   for span in task["supporting_tests"])


def test_no_human_claim_or_candidate_artifact_in_dataset() -> None:
    references, _ = _load()
    serialized = json.dumps(references, sort_keys=True).lower()
    for forbidden in (
        "human_reviewer_id", "human_adjudicator_id", '"human_validated": true',
    ):
        assert forbidden not in serialized
    for task in references["tasks"]:
        spans = [span for area in task["areas"] for option in area["alternatives"]
                 for span in option] + task["supporting_tests"]
        assert all(not span[0].startswith(("docs/", ".middle_man_cache/")) for span in spans)
        assert all("locator" not in span[1].lower() for span in spans)
