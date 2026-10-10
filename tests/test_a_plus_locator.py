"""Synthetic-only checks for the frozen prospective A-plus locator rule."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from middle_man.experiments.a_plus_locator import (
    APPENDIX_LIMIT, build_a_plus_locator, run_a_plus_dry_run,
)
from middle_man.gateway.codex_runner.infrastructure import capture_repository_state
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.models import RepositoryIndex, Symbol
from middle_man.gateway.offline_navigation import OfflineLocator, append_offline_locator
from middle_man.gateway.relevance import ContextQuery, RelevanceCandidate, RelevanceEngine
from middle_man.gateway.tokens import HeuristicTokenEstimator
from middle_man.mcp.benchmark_receipts import selector_implementation_fingerprint


SOURCE = """class Owner:
    def release_cache(self):
        return 'PRIVATE_SOURCE_SENTINEL'

    def release_victim(self):
        return 'PRIVATE_SOURCE_SENTINEL'
"""


def _fixture(root: Path, sources: dict[str, str]) -> tuple[GatewayConfig, RepositoryIndex]:
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    config = GatewayConfig(root, cache_writes_enabled=False)
    return config, RepositoryIndexer(config).index()


def _baseline(text: str) -> OfflineLocator:
    return OfflineLocator(text, hashlib.sha256(text.encode()).hexdigest(),
                          HeuristicTokenEstimator().estimate(text), "synthetic-pack",
                          selector_implementation_fingerprint(), 0, (), ())


def _ranked(monkeypatch: pytest.MonkeyPatch, paths: list[str]) -> None:
    def find(self: RelevanceEngine, query: ContextQuery, *, top_k: int | None = None,
             minimum_score: float | None = None) -> tuple[RelevanceCandidate, ...]:
        assert top_k == 100 and minimum_score is None
        return tuple(RelevanceCandidate(path, 100 - rank, "PRIMARY", (), ())
                     for rank, path in enumerate(paths))
    monkeypatch.setattr(RelevanceEngine, "find", find)


def _build(config: GatewayConfig, index: RepositoryIndex, task: str, text: str):
    return build_a_plus_locator(config, index, ContextQuery(task), _baseline(text))


def test_preserves_a_bytes_and_adds_separate_same_file_hint(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"src/owner.py": SOURCE})
    original = "- src/owner.py:1-6 (Owner)"
    result = _build(config, index, "Explain src/owner.py release_cache", original)
    assert result.text.startswith(original + "\n- src/owner.py:")
    assert result.text.splitlines()[0] == original
    assert len(result.supplemental_hints) == 1 and result.new_file_count == 0
    assert result.baseline_sha256 == hashlib.sha256(original.encode()).hexdigest()
    assert result.appendix_estimated_tokens <= APPENDIX_LIMIT
    assert "PRIVATE_SOURCE_SENTINEL" not in result.text + str(result.receipt())


def test_exact_qualified_symbol_outweighs_lexical_competitor(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"src/owner.py": SOURCE})
    result = _build(config, index, "Owner.release_cache and release victim", "- src/owner.py:1-1")
    assert result.supplemental_hints == (("src/owner.py", 2, 3, "Owner.release_cache"),)


def test_unique_two_term_method_without_explicit_path(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"base.py": "def other():\n    pass\n",
                                           "src/owner.py": SOURCE})
    result = _build(config, index, "Explain release cache behavior", "- base.py:1-2")
    assert result.supplemental_hints == (("src/owner.py", 2, 3, "Owner.release_cache"),)
    assert result.new_file_count == 1


def test_equal_best_methods_abstain_and_graph_only_is_not_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiguous = "def release_cache_one():\n    pass\n\ndef release_cache_two():\n    pass\n"
    config, index = _fixture(tmp_path, {"base.py": "def other():\n    pass\n",
                                           "ambiguous.py": ambiguous,
                                           "related.py": "def idle():\n    pass\n"})
    _ranked(monkeypatch, ["ambiguous.py", "related.py"])
    result = _build(config, index, "Explain release cache", "- base.py:1-2")
    assert not result.supplemental_hints
    assert dict(result.skip_reasons) == {"AMBIGUOUS_METHOD": 1, "NO_METHOD_EVIDENCE": 1}


def test_top_100_cap_and_exact_path_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, index = _fixture(tmp_path, {"base.py": "def other():\n    pass\n",
                                           "target.py": "def release_cache():\n    pass\n"})
    ranked = [f"missing/{number}.py" for number in range(100)] + ["target.py"]
    _ranked(monkeypatch, ranked)
    base = "- base.py:1-2"
    assert not _build(config, index, "release cache", base).supplemental_hints
    selected = _build(config, index, "target.py release cache", base)
    assert selected.supplemental_hints == (("target.py", 1, 2, "release_cache"),)


def test_duplicate_and_contained_identical_symbol_are_skipped(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"src/owner.py": SOURCE})
    exact = _build(config, index, "Owner.release_cache", "- src/owner.py:2-3 (Owner.release_cache)")
    contained = _build(config, index, "Owner.release_cache", "- src/owner.py:1-6 (Owner.release_cache)")
    assert not exact.supplemental_hints and not contained.supplemental_hints
    assert dict(exact.skip_reasons)["DUPLICATE_OR_REDUNDANT"] == 1
    assert dict(contained.skip_reasons)["DUPLICATE_OR_REDUNDANT"] == 1


def test_three_hints_and_two_new_files_limit(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    config, index = _fixture(tmp_path, {
        "base.py": "def release_cache():\n    pass\n",
        "new1.py": "def release_cache():\n    pass\n",
        "new2.py": "def release_cache():\n    pass\n",
        "new3.py": "def release_cache():\n    pass\n",
    })
    _ranked(monkeypatch, ["base.py", "new1.py", "new2.py", "new3.py"])
    result = _build(config, index, "release cache", "- base.py:1-1")
    assert len(result.supplemental_hints) == 3
    assert result.new_file_count == 2
    assert {item[0] for item in result.supplemental_hints} == {"base.py", "new1.py", "new2.py"}
    assert dict(result.skip_reasons)["THREE_HINT_LIMIT"] == 1


def test_two_new_file_limit_when_three_slots_remain(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    config, index = _fixture(tmp_path, {
        "base.py": "def idle():\n    pass\n",
        **{f"new{n}.py": "def release_cache():\n    pass\n" for n in range(3)},
    })
    _ranked(monkeypatch, ["new0.py", "new1.py", "new2.py"])
    result = _build(config, index, "release cache", "- base.py:1-2")
    assert len(result.supplemental_hints) == 2 and result.new_file_count == 2
    assert dict(result.skip_reasons)["TWO_NEW_FILE_LIMIT"] == 1


def test_fixed_full_appendix_ceiling_and_baseline_over_budget(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"base.py": "def release_cache():\n    pass\n"})
    text = "- base.py:1-1"
    estimator = HeuristicTokenEstimator()
    while estimator.estimate(append_offline_locator("", text + "; 1-1")) <= APPENDIX_LIMIT:
        text += "; 1-1"
    at_limit = _build(config, index, "release cache", text)
    assert at_limit.text == text and not at_limit.feasibility_failure
    assert dict(at_limit.skip_reasons)["APPENDIX_BUDGET"] == 1
    over = _build(config, index, "release cache", text + "; 1-1")
    assert over.text == text + "; 1-1" and over.feasibility_failure
    assert dict(over.skip_reasons) == {"BASELINE_OVER_BUDGET": 1}


def test_invalid_spans_and_stale_content_abstain(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"base.py": "def release_cache():\n    pass\n"})
    record = index.get_file("base.py")
    assert record is not None
    invalid = replace(record, symbols=(Symbol("base.py", "release_cache", "release_cache",
                                               "function", 50, 60),))
    tampered = replace(index, files=(invalid,))
    result = _build(config, tampered, "release cache", "- base.py:1-1")
    assert dict(result.skip_reasons)["INVALID_INDEXED_SYMBOL"] == 1
    wrong_location = replace(record, symbols=(Symbol("base.py", "release_cache", "release_cache",
                                                       "function", 2, 2),))
    misleading = _build(config, replace(index, files=(wrong_location,)),
                         "release cache", "- base.py:1-1")
    assert dict(misleading.skip_reasons)["INVALID_INDEXED_SYMBOL"] == 1
    (tmp_path / "base.py").write_text("def release_cache():\n    return 4\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="source changed since indexing"):
        _build(config, index, "release cache", "- base.py:1-1")


def test_invalid_ownership_and_sensitive_symbol_abstain(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"base.py": SOURCE})
    record = index.get_file("base.py")
    assert record is not None
    ownerless = replace(record, symbols=(Symbol("base.py", "release_cache", "Owner.release_cache",
                                                 "method", 2, 3, "Owner"),))
    result = _build(config, replace(index, files=(ownerless,)), "Owner.release_cache", "- base.py:1-1")
    assert dict(result.skip_reasons)["INVALID_INDEXED_SYMBOL"] == 1
    secret = replace(record, symbols=(Symbol("base.py", "release_cache", "TOKEN=privatevalue",
                                              "function", 2, 3),))
    query = ContextQuery("TOKEN=privatevalue release cache")
    hidden = build_a_plus_locator(config, replace(index, files=(secret,)), query,
                                  _baseline("- base.py:1-1"))
    assert "privatevalue" not in hidden.text + str(hidden.receipt())
    assert not hidden.supplemental_hints


def test_unsafe_paths_and_symlinks_abstain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, index = _fixture(tmp_path, {"base.py": "def idle():\n    pass\n"})
    _ranked(monkeypatch, ["../outside.py", "C:/outside.py"])
    result = _build(config, index, "release cache", "- base.py:1-2")
    assert dict(result.skip_reasons)["UNSAFE_OR_STALE_FILE"] == 2
    link = tmp_path / "linked.py"
    link.write_text("def release_cache():\n    pass\n", encoding="utf-8")
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == link or real_is_symlink(self))
    _ranked(monkeypatch, ["linked.py"])
    linked = _build(config, index, "release cache", "- base.py:1-2")
    assert dict(linked.skip_reasons)["UNSAFE_OR_STALE_FILE"] == 1


def test_sensitive_path_never_appears(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = "PASSWORD=privatevalue.py"
    config, index = _fixture(tmp_path, {"base.py": "def idle():\n    pass\n",
                                           path: "def release_cache():\n    pass\n"})
    _ranked(monkeypatch, [path])
    result = _build(config, index, "release cache", "- base.py:1-2")
    assert not result.supplemental_hints
    assert "privatevalue" not in result.text + str(result.receipt())


def test_determinism_and_metadata_only_receipt(tmp_path: Path) -> None:
    config, index = _fixture(tmp_path, {"base.py": "def idle():\n    pass\n",
                                           "new.py": "def release_cache():\n    pass\n"})
    first = _build(config, index, "release cache", "- base.py:1-2")
    second = _build(config, index, "release cache", "- base.py:1-2")
    assert first == second
    assert "new.py" not in str(first.receipt())
    assert "PRIVATE_SOURCE_SENTINEL" not in first.text + str(first.receipt())


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def test_dry_run_pins_clean_git_and_does_not_mutate(tmp_path: Path) -> None:
    _fixture(tmp_path, {"src/owner.py": SOURCE})
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-q", "-m", "synthetic source")
    head = _git(tmp_path, "rev-parse", "HEAD")
    before = capture_repository_state(tmp_path)
    report = run_a_plus_dry_run(tmp_path, ContextQuery("Explain src/owner.py release_cache"),
                                expected_head=head)
    assert capture_repository_state(tmp_path) == before
    assert report["repository_integrity"] == report["safety_status"] == "PASS"
    assert report["external_calls"] == 0
    assert len(report["a_locator_hash"]) == len(report["a_plus_locator_hash"]) == 64
    assert len(report["index_fingerprint"]) == 64
    assert "PRIVATE_SOURCE_SENTINEL" not in str(report)
    with pytest.raises(ValueError, match="pinned clean"):
        run_a_plus_dry_run(tmp_path, ContextQuery("release cache"), expected_head="0" * 40)
    with pytest.raises(RuntimeError, match="index fingerprint"):
        run_a_plus_dry_run(tmp_path, ContextQuery("release cache"), expected_head=head,
                           expected_index_fingerprint="0" * 64)
