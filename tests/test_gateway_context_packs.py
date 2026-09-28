from __future__ import annotations

import json
from pathlib import Path

import pytest

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.context_models import ContextMode, ExpansionRequest
from middle_man.gateway.context_output import format_context_pack, save_context_pack_json
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.quality import run_context_benchmarks
from middle_man.gateway.source import SourceReader, UnsafeSourceError


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "helper.py").write_text("def validate(value):\n    return value == 'ok'\n", encoding="utf-8")
    filler = "".join(f"def unrelated_{i}():\n    return {i}\n\n" for i in range(100))
    (tmp_path / "app" / "session.py").write_text(
        "from .helper import validate\n\n" + filler +
        "class OAuthStateValidator:\n"
        "    @staticmethod\n"
        "    def check(value):\n"
        "        verified = validate(value)\n"
        "        return verified\n", encoding="utf-8")
    (tmp_path / "tests" / "test_session.py").write_text(
        "from app.session import OAuthStateValidator\n\n"
        "def test_check():\n    assert OAuthStateValidator.check('ok')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PASSWORD=supersecretvalue\n", encoding="utf-8")
    return tmp_path


def test_complete_method_import_class_and_test_context(repo: Path) -> None:
    pack = ContextBuilder(GatewayConfig(repo)).build("OAuthStateValidator.check", top_k=8)
    assert pack.generation == 0 and len(pack.fingerprint) == 64
    assert "tests/test_session.py" in pack.related_tests
    session = [item for item in pack.excerpts if item.path == "app/session.py"]
    assert any("return verified" in item.text and "def check" in item.text for item in session)
    assert any("class OAuthStateValidator" in item.text for item in session)
    assert any("from .helper import validate" in item.text for item in session)
    assert all(item.content_hash for item in session)
    assert sum(item.end_line - item.start_line + 1 for item in session) < 30
    assert pack.metrics.estimated_selected_tokens < pack.metrics.estimated_raw_candidate_tokens
    assert pack.metrics.repository_files >= 4
    assert not any(item.path == ".env" for item in pack.excerpts)


def test_modes_budget_atomicity_and_warnings(repo: Path) -> None:
    builder = ContextBuilder(GatewayConfig(repo))
    safe = builder.build("OAuthStateValidator.check", mode="safe", max_context_tokens=1)
    assert any("return verified" in item.text for item in safe.excerpts)
    assert any(warning.startswith("BUDGET_EXCEEDED_FOR_REQUIRED_SYMBOL") for warning in safe.warnings)
    assert any(warning.startswith("CONTEXT_BUDGET_OMISSION") for warning in safe.warnings)
    aggressive = builder.build("OAuthStateValidator.check", mode=ContextMode.AGGRESSIVE, top_k=8)
    assert any("return verified" in item.text for item in aggressive.excerpts)
    assert "CONTEXT_REDUCED_AGGRESSIVE" in aggressive.warnings
    assert aggressive.metrics.estimated_selected_tokens <= builder.build("OAuthStateValidator.check", mode="safe", top_k=8).metrics.estimated_selected_tokens


def test_expansion_is_new_deduplicated_and_fingerprinted(repo: Path) -> None:
    builder = ContextBuilder(GatewayConfig(repo))
    original = builder.build("OAuthStateValidator.check", top_k=5)
    again = builder.build("OAuthStateValidator.check", top_k=5)
    assert original.fingerprint == again.fingerprint
    expanded = builder.expand(original, ExpansionRequest("full_file", "app/session.py"))
    assert expanded.generation == 1 and original.generation == 0
    assert expanded.fingerprint != original.fingerprint
    assert sum(item.complete_file for item in expanded.excerpts if item.path == "app/session.py") == 1
    assert expanded.metrics.duplicate_bytes_avoided > 0
    assert all(not item.complete_file for item in original.excerpts if item.path == "app/session.py")
    imports = builder.expand(original, ExpansionRequest("related_imports", "app/session.py"))
    assert any(item.path == "app/helper.py" and "def validate" in item.text for item in imports.excerpts)


def test_changed_source_refreshes_and_expansion_warns(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = ContextBuilder(GatewayConfig(repo))
    original = builder.build("OAuthStateValidator.check")
    source = repo / "app" / "session.py"
    source.write_text(source.read_text(encoding="utf-8").replace("return verified", "return not verified"), encoding="utf-8")
    expanded = builder.expand(original, ExpansionRequest("full_file", "app/session.py"))
    assert any(warning.startswith("SOURCE_CHANGED_DURING_SELECTION") for warning in expanded.warnings)
    assert any("return not verified" in item.text for item in expanded.excerpts)

    before = SourceReader.read
    changed = False

    def racing_read(self: SourceReader, path: str):
        nonlocal changed
        if path == "app/session.py" and not changed:
            changed = True
            source.write_text(source.read_text(encoding="utf-8").replace("return not verified", "return verified"), encoding="utf-8")
        return before(self, path)

    monkeypatch.setattr(SourceReader, "read", racing_read)
    refreshed = builder.build("OAuthStateValidator.check")
    assert changed and any("return verified" in item.text for item in refreshed.excerpts)


def test_source_reader_rejects_ignored_and_traversal(repo: Path, tmp_path: Path) -> None:
    config = GatewayConfig(repo)
    reader = SourceReader(config, RepositoryIndexer(config).index())
    with pytest.raises(UnsafeSourceError):
        reader.read(".env")
    with pytest.raises((UnsafeSourceError, ValueError)):
        reader.read("../outside.py")


def test_redacted_pack_and_json_export(repo: Path, tmp_path: Path) -> None:
    source = repo / "app" / "secrets.py"
    source.write_text("def get_password():\n    PASSWORD = 'supersecretvalue'\n    return PASSWORD\n", encoding="utf-8")
    pack = ContextBuilder(GatewayConfig(repo)).build("app/secrets.py")
    assert "REDACTIONS_APPLIED" in pack.warnings
    assert "supersecretvalue" not in format_context_pack(pack)
    destination = save_context_pack_json(pack, tmp_path / "pack.json")
    exported = destination.read_text(encoding="utf-8")
    assert "supersecretvalue" not in exported
    assert "MIDDLE_MAN_REDACTED_SECRET" in exported
    assert json.loads(exported)["metrics"]["files_selected"] >= 1


def test_local_quality_benchmarks_preserve_required_context() -> None:
    results = run_context_benchmarks()
    assert len(results) >= 2
    assert all(result.required_file_recall == 1.0 and result.required_symbol_recall == 1.0 for result in results)
    assert all(result.success for result in results)
    assert all(result.selected_estimated_tokens < result.raw_candidate_estimated_tokens for result in results)
