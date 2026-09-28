from __future__ import annotations

from pathlib import Path

from middle_man.gateway import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.relevance import ContextQuery
from middle_man.gateway.secrets import MARKER, SecretRedactor


def test_prefixed_environment_secrets_and_benign_identifiers() -> None:
    raw = ("OPENAI_API_KEY=sk-very-secret-value\n"
           "GITHUB_TOKEN='ghp-secret-value'\n"
           "AWS_SECRET_ACCESS_KEY=really-secret-value\n"
           "token_count = 10\npassword_hash = hash_password(user_input)\n")
    result = SecretRedactor().redact(raw)
    for secret in ("sk-very-secret-value", "ghp-secret-value", "really-secret-value"):
        assert secret not in result.text
    assert result.text.count(MARKER) == 3
    assert "token_count = 10" in result.text
    assert "password_hash = hash_password(user_input)" in result.text


def test_unrelated_git_change_does_not_change_pack_fingerprint(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def validate(): return True\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("def render(): return False\n", encoding="utf-8")
    builder = ContextBuilder(GatewayConfig(tmp_path, git_enabled=False))
    first = builder.build(ContextQuery("validate", changed_files=("auth.py",)))
    second = builder.build(ContextQuery("validate", changed_files=("auth.py", "unrelated.py")))
    assert first.fingerprint == second.fingerprint
    (tmp_path / "auth.py").write_text("def validate(): return False\n", encoding="utf-8")
    third = builder.build(ContextQuery("validate", changed_files=("auth.py",)))
    assert third.fingerprint != first.fingerprint
