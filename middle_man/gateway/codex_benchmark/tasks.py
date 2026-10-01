"""Frozen benchmark tasks and independent committed starting snapshots."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent


@dataclass(frozen=True, slots=True)
class TaskSpec:
    id: str
    title: str
    prompt: str
    read_only: bool
    source: str
    required_facts: tuple[str, ...] = ()
    acceptance_test: str | None = None
    schema_version: int = 1
    source_ref: str | None = None


TASK_A_SOURCE_COMMIT = '284c4451ad9213f4f27f6d534eac8be2484c2f9a'


TASKS = (
    TaskSpec(
        "preemption", "KV preemption architecture",
        "Explain how KV preemption works in Middle_Man. Identify victim selection, memory release, "
        "recomputation, and the tests that prove already-generated output is retained. Do not modify files.",
        True, "repository-commit",
        ("LargestPrivateOwnerPolicy", "MemoryController", "RECOMPUTE", "output_generated", "test_phase_7_preemption"),
        source_ref=TASK_A_SOURCE_COMMIT,
    ),
    TaskSpec(
        "oauth-bug", "Expired OAuth state bug",
        "Fix the OAuth callback bug: expired state tokens are accepted. Preserve valid states, clock-skew handling, "
        "and single-use replay protection. Add or adjust tests. Run the test suite.",
        False, "oauth-fixture",
        acceptance_test=dedent('''\
            import unittest
            from app.auth import AuthService
            from app.state import StateStore
            from app.config import STATE_TTL_SECONDS

            class Acceptance(unittest.TestCase):
                def test_expired_rejected_at_store_boundary(self):
                    store = StateStore()
                    token = store.issue("alice", now=100)
                    self.assertIsNone(store.consume(token, now=100 + STATE_TTL_SECONDS + 1))

                def test_ttl_boundary_and_replay(self):
                    store = StateStore()
                    auth = AuthService(store)
                    token = auth.start("bob", now=20)
                    self.assertEqual(auth.callback(token, now=20 + STATE_TTL_SECONDS), "bob")
                    with self.assertRaises(ValueError):
                        auth.callback(token, now=20 + STATE_TTL_SECONDS)

                def test_future_clock_skew(self):
                    store = StateStore()
                    token = store.issue("carol", now=105)
                    self.assertEqual(store.consume(token, now=100), "carol")
                    future = store.issue("dave", now=200)
                    self.assertIsNone(store.consume(future, now=100))
            '''),
    ),
    TaskSpec(
        "upload-feature", "Configurable upload extensions",
        "Add a configurable, case-insensitive file-extension allowlist to the upload service. By default allow .txt "
        "and .md; reject empty or path-like names and disallowed extensions before storing. Extend the shared "
        "validation helper and configuration, preserve size-limit and duplicate behavior, and add tests. Run the test suite.",
        False, "upload-fixture",
        acceptance_test=dedent('''\
            import unittest
            from app.config import UploadConfig
            from app.uploads import UploadService

            class Acceptance(unittest.TestCase):
                def test_default_allowlist_case_insensitive(self):
                    service = UploadService()
                    service.upload("NOTES.TXT", b"ok")
                    service.upload("readme.md", b"fine")
                    self.assertEqual(service.get("NOTES.TXT"), b"ok")
                    with self.assertRaises(ValueError):
                        service.upload("script.exe", b"bad")

                def test_custom_allowlist(self):
                    service = UploadService(UploadConfig(allowed_extensions=(".csv",)))
                    service.upload("data.CSV", b"ok")
                    with self.assertRaises(ValueError):
                        service.upload("notes.txt", b"no")

                def test_names_and_failed_write(self):
                    service = UploadService()
                    for name in ("", "../escape.txt", "folder/file.txt", "folder\\\\file.txt", ".txt"):
                        with self.subTest(name=name), self.assertRaises(ValueError):
                            service.upload(name, b"x")
                    self.assertEqual(service.count(), 0)

                def test_existing_limits_and_duplicates(self):
                    service = UploadService(UploadConfig(max_bytes=2))
                    service.upload("a.txt", b"ab")
                    with self.assertRaises(ValueError):
                        service.upload("b.txt", b"abc")
                    with self.assertRaises(ValueError):
                        service.upload("a.txt", b"c")
                    self.assertEqual(service.count(), 1)
            '''),
    ),
    TaskSpec(
        "preemption-v2", "KV preemption architecture (structured v2)",
        "Explain how KV preemption works in Middle_Man. For victim selection, memory release/control, "
        "recomputation, output preservation, and the proving test, name the concrete implementation "
        "symbol, component, or test file used by this repository. Give a concise explanation. "
        "Do not modify files.",
        True, "repository-commit", schema_version=2, source_ref=TASK_A_SOURCE_COMMIT,
    ),
    TaskSpec(
        "preemption-v3", "KV preemption architecture (structured v3)",
        "Explain how KV preemption works in Middle_Man. For victim selection, memory release/control, "
        "recomputation, output preservation, and the proving test, name the concrete implementation "
        "symbol, component, or test file used by this repository. Give a concise explanation. "
        "Do not modify files.",
        True, "repository-commit", schema_version=3, source_ref=TASK_A_SOURCE_COMMIT,
    ),
    TaskSpec(
        "preemption-v4", "KV preemption architecture (explicit abstractions v4)",
        "Explain how KV preemption works in Middle_Man. For victim selection, memory release/control, "
        "recomputation, output preservation, and the proving test, name the concrete implementation "
        "symbol, component, or test file used by this repository. Give a concise explanation. "
        "Do not modify files. Give the policy implementation class choosing victims, controller component "
        "coordinating KV allocation and release, WorkKind enum member emitted by the scheduler for "
        "preempted requests, InferenceRequest generated-output field preserved across preemption, and "
        "proving test file. Explain their interaction and KV block release.",
        True, "repository-commit", schema_version=4, source_ref=TASK_A_SOURCE_COMMIT,
    ),
)


_FIXTURES: dict[str, dict[str, str]] = {
    "oauth-fixture": {
        "app/__init__.py": "",
        "app/config.py": "STATE_TTL_SECONDS = 300\nCLOCK_SKEW_SECONDS = 5\n",
        "app/state.py": dedent('''\
            from dataclasses import dataclass
            from app.config import CLOCK_SKEW_SECONDS, STATE_TTL_SECONDS

            @dataclass
            class StateRecord:
                user_id: str
                issued_at: int
                used: bool = False

            class StateStore:
                def __init__(self):
                    self._records = {}
                    self._sequence = 0

                def issue(self, user_id: str, now: int) -> str:
                    self._sequence += 1
                    token = f"state-{self._sequence}"
                    self._records[token] = StateRecord(user_id, now)
                    return token

                def consume(self, token: str, now: int) -> str | None:
                    record = self._records.get(token)
                    if record is None or record.used:
                        return None
                    if record.issued_at > now + CLOCK_SKEW_SECONDS:
                        return None
                    record.used = True
                    return record.user_id
            '''),
        "app/auth.py": dedent('''\
            from app.state import StateStore

            class AuthService:
                def __init__(self, states: StateStore):
                    self.states = states

                def start(self, user_id: str, now: int) -> str:
                    return self.states.issue(user_id, now)

                def callback(self, token: str, now: int) -> str:
                    user_id = self.states.consume(token, now)
                    if user_id is None:
                        raise ValueError("invalid or expired OAuth state")
                    return user_id
            '''),
        "app/database.py": "class UserDatabase:\n    def find(self, user_id):\n        return {'id': user_id}\n",
        "tests/test_auth.py": dedent('''\
            import unittest
            from app.auth import AuthService
            from app.state import StateStore

            class AuthTests(unittest.TestCase):
                def test_valid_callback_and_replay(self):
                    auth = AuthService(StateStore())
                    token = auth.start("alice", now=100)
                    self.assertEqual(auth.callback(token, now=110), "alice")
                    with self.assertRaises(ValueError):
                        auth.callback(token, now=111)

                def test_expired_callback(self):
                    auth = AuthService(StateStore())
                    token = auth.start("bob", now=100)
                    with self.assertRaises(ValueError):
                        auth.callback(token, now=500)
            '''),
        "tests/test_database.py": "import unittest\nfrom app.database import UserDatabase\n\nclass DatabaseTests(unittest.TestCase):\n    def test_find(self):\n        self.assertEqual(UserDatabase().find('a')['id'], 'a')\n",
        "static/unrelated.css": "body { color: #333; }\n",
    },
    "upload-fixture": {
        "app/__init__.py": "",
        "app/config.py": dedent('''\
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class UploadConfig:
                max_bytes: int = 1024
            '''),
        "app/rules.py": dedent('''\
            from app.config import UploadConfig

            def validate_size(data: bytes, config: UploadConfig) -> None:
                if len(data) > config.max_bytes:
                    raise ValueError("upload too large")
            '''),
        "app/uploads.py": dedent('''\
            from app.config import UploadConfig
            from app.rules import validate_size

            class UploadService:
                def __init__(self, config: UploadConfig | None = None):
                    self.config = config or UploadConfig()
                    self._files = {}

                def upload(self, name: str, data: bytes) -> None:
                    validate_size(data, self.config)
                    if name in self._files:
                        raise ValueError("duplicate upload")
                    self._files[name] = data

                def get(self, name: str) -> bytes:
                    return self._files[name]

                def count(self) -> int:
                    return len(self._files)
            '''),
        "tests/test_uploads.py": dedent('''\
            import unittest
            from app.config import UploadConfig
            from app.uploads import UploadService

            class UploadTests(unittest.TestCase):
                def test_size_and_duplicate(self):
                    service = UploadService(UploadConfig(max_bytes=2))
                    service.upload("a.txt", b"ab")
                    with self.assertRaises(ValueError):
                        service.upload("b.txt", b"abc")
                    with self.assertRaises(ValueError):
                        service.upload("a.txt", b"c")
            '''),
        "app/reporting.py": "def summarize_uploads(files):\n    return len(files)\n",
        "static/unrelated.css": "main { display: block; }\n",
    },
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def _write_fixture(task: TaskSpec, destination: Path) -> None:
    if task.source == "repository-commit":
        if not task.source_ref or len(task.source_ref) != 40 or any(ch not in "0123456789abcdef" for ch in task.source_ref):
            raise ValueError("benchmark repository source requires an exact commit SHA")
        root = Path(__file__).resolve().parents[3]
        commit = subprocess.run(["git", "-C", str(root), "cat-file", "-t", task.source_ref],
                                capture_output=True, text=True)
        if commit.returncode or commit.stdout.strip() != "commit":
            raise ValueError(f"benchmark source commit unavailable: {task.source_ref}")
        names = subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", "-z", "--name-only", task.source_ref])
        for raw in names.split(b"\0"):
            if not raw:
                continue
            relative = raw.decode("utf-8")
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or path.name.startswith(".env"):
                raise ValueError(f"unsafe tracked snapshot path: {relative}")
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(["git", "-C", str(root), "show", f"{task.source_ref}:{relative}"]))
    else:
        for relative, text in _FIXTURES[task.source].items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        (destination / ".gitignore").write_text(".middle_man_cache/\n__pycache__/\n*.pyc\n", encoding="utf-8")


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.name == "AGENTS.md" or relative.suffix in {".pyc", ".pyo"}:
            continue
        if {".git", ".middle_man_cache", "__pycache__", ".pytest_cache"}.intersection(relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()

def prepare_pair(task: TaskSpec, pair_root: Path, instructions: str | None) -> tuple[Path, Path, str]:
    source = pair_root / "source"
    source.mkdir(parents=True, exist_ok=False)
    _write_fixture(task, source)
    baseline, optimized = pair_root / "baseline", pair_root / "optimized"
    shutil.copytree(source, baseline)
    shutil.copytree(source, optimized)
    if (baseline / "AGENTS.md").exists():
        raise ValueError("source commit contains AGENTS.md; baseline cannot start clean without changing source")
    if instructions is not None:
        (optimized / "AGENTS.md").write_text(instructions, encoding="utf-8")
    baseline_hash = source_fingerprint(baseline)
    if baseline_hash != source_fingerprint(optimized):
        raise ValueError("baseline and optimized source snapshots differ")
    for root in (baseline, optimized):
        _git(root, "init", "-q")
        _git(root, "add", ".")
        _git(root, "-c", "user.name=Middle_Man Benchmark", "-c", "user.email=benchmark@example.invalid",
             "commit", "-q", "-m", "frozen benchmark start")
        if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("prepared benchmark snapshot is not Git-clean")
    return baseline, optimized, baseline_hash


def add_acceptance_tests(task: TaskSpec, root: Path) -> None:
    if task.acceptance_test is None:
        return
    destination = root / "tests" / "test_middleman_benchmark_acceptance.py"
    if destination.exists():
        raise ValueError("acceptance tests already present")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(task.acceptance_test, encoding="utf-8")
