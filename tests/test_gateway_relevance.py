from __future__ import annotations

from pathlib import Path

from middle_man.gateway import ContextQuery, GatewayConfig, RelevanceEngine, RepositoryIndexer


def repository(tmp_path: Path) -> tuple[GatewayConfig, RelevanceEngine]:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "auth.py").write_text(
        "from .database import connect\nclass OAuthStateError(Exception): pass\n"
        "class AuthService:\n    def validate_state(self): return connect()\n", encoding="utf-8")
    (root / "app" / "database.py").write_text("def connect(): pass\n", encoding="utf-8")
    (root / "app" / "service.py").write_text("from .auth import AuthService\ndef run(): return AuthService()\n", encoding="utf-8")
    (root / "tests" / "test_auth.py").write_text("from app.auth import AuthService\ndef test_validate_state(): pass\n", encoding="utf-8")
    (root / "app" / "unrelated.py").write_text("def render(): pass\n", encoding="utf-8")
    config = GatewayConfig(root)
    return config, RelevanceEngine(RepositoryIndexer(config).index(), config)


def test_exact_path_symbol_case_and_snake_case(tmp_path: Path) -> None:
    _, engine = repository(tmp_path)
    assert engine.find("app/auth.py")[0].path == "app/auth.py"
    assert engine.find(ContextQuery("", paths=("app/auth.py",)))[0].path == "app/auth.py"
    assert engine.find("OAuthStateError")[0].path == "app/auth.py"
    assert engine.find("AuthService.validate_state")[0].path == "app/auth.py"
    assert engine.find("validate_state")[0].path == "app/auth.py"
    assert engine.find("auth login")[0].path == "app/auth.py"


def test_graph_neighbors_tests_changes_and_trace(tmp_path: Path) -> None:
    _, engine = repository(tmp_path)
    result = engine.find("OAuthStateError", top_k=20)
    by_path = {candidate.path: candidate for candidate in result}
    assert "app/database.py" in by_path
    assert "app/service.py" in by_path
    assert "tests/test_auth.py" in by_path
    assert by_path["app/database.py"].role == "RELATED"
    assert any("tests relevant file" in reason for reason in by_path["tests/test_auth.py"].reasons)
    changed = engine.find(ContextQuery("auth", changed_files=("app/auth.py",)))
    assert "relevant changed file" in changed[0].reasons
    assert engine.find(ContextQuery("failed", error_text='File "app/auth.py", line 3, in validate_state\nOAuthStateError'))[0].path == "app/auth.py"
    assert any("trace path" in reason for reason in engine.find(ContextQuery("failed", error_text="app/auth.py"))[0].reasons)


def test_limits_threshold_order_explanations_and_irrelevance(tmp_path: Path) -> None:
    _, engine = repository(tmp_path)
    result = engine.find("auth", top_k=2)
    assert len(result) == 2
    assert all(item.reasons and item.score > 0 for item in result)
    assert not engine.find("auth", minimum_score=10_000)
    assert not engine.find("completelyunknownterm")
    assert "app/unrelated.py" not in {item.path for item in engine.find("auth", top_k=50)}
    first = engine.find("auth", top_k=50)
    assert first == engine.find("auth", top_k=50)
    assert first == tuple(sorted(first, key=lambda item: (-item.score, item.path)))
