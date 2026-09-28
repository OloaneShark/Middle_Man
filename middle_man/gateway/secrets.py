"""Conservative, line-preserving sanitization of outgoing source and logs."""

from __future__ import annotations

import re
from dataclasses import dataclass

MARKER = "[MIDDLE_MAN_REDACTED_SECRET]"
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]* )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9 ]* )?PRIVATE KEY-----")
_BEARER = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9._~+/-]{12,}=*)")
_CREDENTIAL_URL = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s/@:]+):([^\s/@]+)@")
_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w])([\"']?(?:(?:[A-Za-z][A-Za-z0-9]*[_-])*)(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?access[_-]?key|token|password|passwd|db[_-]?password|database[_-]?password|jwt[_-]?secret|session[_-]?secret)[\"']?\s*[:=]\s*)([\"'])([^\r\n]*?)(\2)"
)
_ENV_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w])((?:(?:[A-Z][A-Z0-9]*_)*)(?:API_KEY|SECRET_KEY|CLIENT_SECRET|ACCESS_TOKEN|AUTH_TOKEN|SECRET_ACCESS_KEY|PASSWORD|PASSWD|DB_PASSWORD|DATABASE_PASSWORD|JWT_SECRET|SESSION_SECRET|TOKEN)\s*=\s*)([^\s\"']+)"
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    categories: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.categories)


class SecretRedactor:
    def redact(self, text: str) -> RedactionResult:
        categories: list[str] = []

        def private_key(match: re.Match[str]) -> str:
            categories.append("private key")
            return MARKER + "\n" * match.group(0).count("\n")

        text = _PRIVATE_KEY.sub(private_key, text)

        def credential(match: re.Match[str]) -> str:
            categories.append("credential URL")
            return match.group(1) + MARKER + "@"

        text = _CREDENTIAL_URL.sub(credential, text)

        def bearer(match: re.Match[str]) -> str:
            categories.append("bearer token")
            return match.group(1) + MARKER

        text = _BEARER.sub(bearer, text)

        def assigned(match: re.Match[str]) -> str:
            value = match.group(3)
            if not value or value == MARKER or value.startswith(("${", "{{")):
                return match.group(0)
            categories.append("assigned secret")
            return match.group(1) + match.group(2) + MARKER + match.group(4)

        text = _ASSIGNMENT.sub(assigned, text)

        def environment(match: re.Match[str]) -> str:
            if match.group(2) == MARKER:
                return match.group(0)
            categories.append("environment secret")
            return match.group(1) + MARKER

        text = _ENV_ASSIGNMENT.sub(environment, text)
        return RedactionResult(text, tuple(categories))
