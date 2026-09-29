"""Unrelated local-only fixtures for bounded context coverage."""

from __future__ import annotations

from textwrap import dedent

from middle_man.gateway.quality import QualityCase


def coverage_cases() -> tuple[QualityCase, ...]:
    filler = "".join(f"def archived_operation_{n}():\n    return {n}\n\n" for n in range(180))
    return (
        QualityCase(
            "auth-callback", "Fix callback state expiry validation and prove it with tests",
            (("app/__init__.py", ""),
             ("app/callback.py", dedent('''\
                 from app.state_validator import validate_state
                 from app.config import STATE_TTL

                 class CallbackController:
                     def handle_callback(self, token, now):
                         return validate_state(token, now, STATE_TTL)
                 ''') + filler),
             ("app/state_validator.py", "def validate_state(token, now, ttl):\n    return now - token.issued_at <= ttl\n"),
             ("app/config.py", "STATE_TTL = 300\n"),
             ("tests/test_callback.py", dedent('''\
                 from app.callback import CallbackController
                 from app.state_validator import validate_state

                 def test_callback_expiry():
                     assert validate_state(type('T', (), {'issued_at': 1})(), 2, 3)
                 ''')),
             ("app/callback_archive.py", "def old_callback(): return True\n"),
             ("app/reporting.py", "def report(): return 'unrelated'\n")),
            ("app/callback.py", "app/state_validator.py", "app/config.py", "tests/test_callback.py"),
            ("CallbackController.handle_callback", "validate_state", "STATE_TTL", "test_callback_expiry"),
            ("app/callback_archive.py", "app/reporting.py")),
        QualityCase(
            "queue-cancellation", "Explain queue cancellation scheduling policy and tests",
            (("app/__init__.py", ""),
             ("app/scheduler.py", dedent('''\
                 from app.queue_model import QueueItem
                 from app.cancellation_policy import may_cancel

                 class QueueScheduler:
                     def cancel(self, item: QueueItem):
                         if may_cancel(item):
                             item.cancelled = True
                 ''') + filler),
             ("app/queue_model.py", "class QueueItem:\n    def __init__(self):\n        self.cancelled = False\n"),
             ("app/cancellation_policy.py", "def may_cancel(item):\n    return not item.cancelled\n"),
             ("tests/test_cancellation.py", dedent('''\
                 from app.scheduler import QueueScheduler
                 from app.queue_model import QueueItem

                 def test_queue_cancellation():
                     item = QueueItem()
                     QueueScheduler().cancel(item)
                     assert item.cancelled
                 ''')),
             ("app/queue_report.py", "def cancellation_report(): return 1\n"),
             ("static/style.css", "body { color: blue; }\n")),
            ("app/scheduler.py", "app/queue_model.py", "app/cancellation_policy.py", "tests/test_cancellation.py"),
            ("QueueScheduler.cancel", "QueueItem", "may_cancel", "test_queue_cancellation"),
            ("app/queue_report.py", "static/style.css")),
        QualityCase(
            "upload-validation", "Fix file upload validation using configuration and tests",
            (("app/__init__.py", ""),
             ("app/upload_service.py", dedent('''\
                 from app.upload_validator import validate_upload
                 from app.config import ALLOWED_EXTENSIONS

                 class UploadService:
                     def upload(self, name, data):
                         validate_upload(name, ALLOWED_EXTENSIONS)
                         return data
                 ''') + filler),
             ("app/upload_validator.py", "def validate_upload(name, allowed):\n    return name.lower().endswith(allowed)\n"),
             ("app/config.py", "ALLOWED_EXTENSIONS = ('.txt', '.md')\n"),
             ("tests/test_upload_validation.py", dedent('''\
                 from app.upload_service import UploadService

                 def test_upload_validation():
                     assert UploadService().upload('a.txt', b'a') == b'a'
                 ''')),
             ("app/upload_history.py", "def upload_report(): return 0\n"),
             ("static/unrelated.css", "main { display: block; }\n")),
            ("app/upload_service.py", "app/upload_validator.py", "app/config.py", "tests/test_upload_validation.py"),
            ("UploadService.upload", "validate_upload", "ALLOWED_EXTENSIONS", "test_upload_validation"),
            ("app/upload_history.py", "static/unrelated.css")),
    )
