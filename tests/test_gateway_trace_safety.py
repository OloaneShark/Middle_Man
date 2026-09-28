from __future__ import annotations

from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.secrets import SecretRedactor


def test_repeated_traceback_frames_are_not_collapsed() -> None:
    trace = ("Traceback (most recent call last):\n"
             "  File \"app.py\", line 10, in run\n"
             "  File \"app.py\", line 10, in run\n"
             "RuntimeError: failure\n")
    compacted = OutputCompactor().compact("log", trace, max_tokens=1)
    assert compacted.compacted_text.count('File "app.py", line 10') == 2
    assert "RuntimeError: failure" in compacted.compacted_text
    assert "BUDGET_EXCEEDED_FOR_REQUIRED_OUTPUT" in compacted.warnings


def test_short_environment_password_is_redacted() -> None:
    result = SecretRedactor().redact("PASSWORD=abc\ntoken_count = 3\n")
    assert "PASSWORD=abc" not in result.text
    assert "token_count = 3" in result.text
