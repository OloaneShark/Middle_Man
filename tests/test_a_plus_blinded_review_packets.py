"""Blinding and reproducibility checks; no locator or inference is invoked."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import prepare_a_plus_review_packets as packets


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_packet_is_exactly_the_frozen_task_projection() -> None:
    corpus = packets.load_frozen_corpus()
    packet = _json(packets.OUTPUTS["packet"])
    assert corpus["corpus_sha256"] == packets.CORPUS_SHA256
    assert set(packet) == {"schema", "source", "instructions", "tasks"}
    assert packet["source"] == {"commit": packets.SOURCE_COMMIT, "tree": packets.SOURCE_TREE}
    assert len(packet["instructions"]) == 5
    assert len(packet["tasks"]) == 16
    assert [item["task_id"] for item in packet["tasks"]] == list(packets.TASK_IDS)
    for source, visible in zip(corpus["tasks"], packet["tasks"], strict=True):
        assert set(visible) == {"task_id", "task", "sha256", "evidence"}
        assert {key: visible[key] for key in ("task_id", "task", "sha256")} == {
            key: source[key] for key in ("task_id", "task", "sha256")
        }
        assert visible["sha256"] == hashlib.sha256(visible["task"].encode("utf-8")).hexdigest()
        assert visible["evidence"] == packets._blank_evidence()


def test_two_submissions_are_identical_except_for_slot_and_remain_blank() -> None:
    packet = _json(packets.OUTPUTS["packet"])
    first = _json(packets.OUTPUTS["reviewer_1"])
    second = _json(packets.OUTPUTS["reviewer_2"])
    for document, slot in ((first, "reviewer_1"), (second, "reviewer_2")):
        assert set(document) == {"schema", "reviewer_slot", "review_status", "packet"}
        assert document["reviewer_slot"] == slot
        assert document["review_status"] == "PENDING"
        assert document["packet"] == packet
    assert first["packet"] == second["packet"]


def test_no_provenance_reference_or_candidate_data_leaks() -> None:
    packet = _json(packets.OUTPUTS["packet"])
    serialized = json.dumps(packet, sort_keys=True)
    for forbidden in (
        "authoring_provenance", "source_paths_checked", "ambiguity_notes",
        "explicit_paths_supplied", "explicit_symbols_supplied", "reference_labels",
        "candidate_output", "navigation_score", "selector_result",
        "locator_shadow_corpus", "shadow_result", "a_plus_locator",
    ):
        assert forbidden not in serialized
    for item in packet["tasks"]:
        evidence = item["evidence"]
        assert evidence["status"] == "PENDING"
        assert evidence["source_grounded_reasoning"] is None
        assert all(not value for key, value in evidence.items() if key not in {
            "status", "source_grounded_reasoning",
        })
    mutated = deepcopy(packets.load_frozen_corpus())
    mutated["tasks"][0]["authoring_provenance"] = {"source_paths_checked": ["SENTINEL"]}
    mutated["tasks"][0]["ambiguity_notes"] = "SENTINEL"
    assert "SENTINEL" not in json.dumps(packets.build_packet(mutated))


def test_generator_is_deterministic_and_reads_only_frozen_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[Path] = []
    real_read_text = Path.read_text

    def tracked_read_text(path: Path, *args: object, **kwargs: object) -> str:
        reads.append(path.resolve())
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)
    corpus = packets.load_frozen_corpus()
    rendered = packets.rendered_outputs(corpus)
    assert reads == [packets.CORPUS.resolve()]
    for name, content in rendered.items():
        assert real_read_text(packets.OUTPUTS[name], encoding="utf-8") == content
    assert rendered == packets.rendered_outputs(corpus)


def test_frozen_inputs_reject_drift(tmp_path: Path) -> None:
    corpus = packets.load_frozen_corpus()
    corpus["tasks"][0]["task"] += " changed"
    altered = tmp_path / "altered.json"
    altered.write_text(json.dumps(corpus), encoding="utf-8")
    with pytest.raises(ValueError, match="corpus checksum changed"):
        packets.load_frozen_corpus(altered)
