"""Small local context-efficiency fixtures with required-source recall."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.context_models import ContextMode
from middle_man.gateway.indexer import RepositoryIndexer


@dataclass(frozen=True, slots=True)
class QualityCase:
    name: str
    query: str
    files: tuple[tuple[str, str], ...]
    required_files: tuple[str, ...]
    required_symbols: tuple[str, ...]
    irrelevant_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityResult:
    name: str
    required_file_recall: float
    required_symbol_recall: float
    irrelevant_files_included: int
    raw_candidate_estimated_tokens: int
    selected_estimated_tokens: int
    estimated_reduction_percent: float
    warnings: tuple[str, ...]
    success: bool


def quality_cases() -> tuple[QualityCase, ...]:
    filler = "".join(f"def unrelated_{number}():\n    return {number}\n\n" for number in range(250))
    return (
        QualityCase("oauth-indirect", "Fix OAuthStateValidator.validate_state",
                    (("app/__init__.py", ""),
                     ("app/session.py", "from .config import OAUTH_STATE_SALT\nfrom .helper import validate_state\n\nclass OAuthStateValidator:\n    def validate_state(self, supplied):\n        return validate_state(supplied, OAUTH_STATE_SALT)\n"),
                     ("app/config.py", "OAUTH_STATE_SALT = 'fixture-value'\n"),
                     ("app/helper.py", filler + "def validate_state(value, salt):\n    return value == salt\n"),
                     ("app/auth_old.py", "def obsolete_oauth():\n    return False\n"),
                     ("tests/test_session.py", "from app.session import OAuthStateValidator\n\ndef test_validate_state():\n    assert OAuthStateValidator().validate_state('fixture-value')\n"),
                     ("static/style.css", "body { color: red; }\n")),
                    ("app/session.py", "app/helper.py", "tests/test_session.py"),
                    ("OAuthStateValidator.validate_state", "validate_state", "test_validate_state"),
                    ("static/style.css", "app/auth_old.py")),
        QualityCase("large-function", "Fix critical_handler",
                    (("app/large.py", filler + "def critical_handler(value):\n    checked = value + 1\n    return checked\n"),
                     ("tests/test_large.py", "from app.large import critical_handler\ndef test_critical_handler():\n    assert critical_handler(1) == 2\n"),
                     ("app/irrelevant.py", "def renderer(): pass\n")),
                    ("app/large.py", "tests/test_large.py"),
                    ("critical_handler", "test_critical_handler"),
                    ("app/irrelevant.py",)),
    )


def run_context_benchmarks(*, mode: ContextMode | str = ContextMode.SAFE,
                           max_context_tokens: int = 8000,
                           cases: tuple[QualityCase, ...] | None = None) -> tuple[QualityResult, ...]:
    results = []
    for case in quality_cases() if cases is None else cases:
        with TemporaryDirectory(prefix="middle-man-quality-") as temporary:
            root = Path(temporary)
            for path, source in case.files:
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(source, encoding="utf-8")
            config = GatewayConfig(root)
            pack = ContextBuilder(config).build(case.query, mode=mode, max_context_tokens=max_context_tokens, top_k=10)
            index = RepositoryIndexer(config).index()
            selected = {item.path for item in pack.excerpts}
            file_recall = sum(path in selected for path in case.required_files) / len(case.required_files)
            symbol_recall = 0
            for name in case.required_symbols:
                found = any(item.path == symbol.path and item.start_line <= symbol.start_line
                            and item.end_line >= (symbol.end_line or symbol.start_line)
                            for symbol in index.find_symbol(name) for item in pack.excerpts)
                symbol_recall += found
            symbol_recall /= len(case.required_symbols)
            irrelevant = sum(path in selected for path in case.irrelevant_files)
            metrics = pack.metrics
            results.append(QualityResult(case.name, file_recall, symbol_recall, irrelevant,
                                         metrics.estimated_raw_candidate_tokens, metrics.estimated_selected_tokens,
                                         metrics.estimated_reduction_percent, pack.warnings,
                                         file_recall == 1.0 and symbol_recall == 1.0 and
                                         metrics.estimated_selected_tokens < metrics.estimated_raw_candidate_tokens))
    return tuple(results)
