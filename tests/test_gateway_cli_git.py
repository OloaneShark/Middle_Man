from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway import GatewayConfig, RepositoryIndexer


def test_cli_index_search_and_cache(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "auth.py").write_text("class OAuthStateError(Exception): pass\n", encoding="utf-8")
    main(["index", "--repo", str(tmp_path)])
    assert "Files discovered: 1" in capsys.readouterr().out
    main(["context", "find", "OAuthStateError", "--repo", str(tmp_path)])
    assert "auth.py" in capsys.readouterr().out
    main(["cache", "status", "--repo", str(tmp_path)])
    assert "1 valid file records" in capsys.readouterr().out
    main(["cache", "clear", "--repo", str(tmp_path)])
    assert "cache cleared" in capsys.readouterr().out
    assert (tmp_path / "auth.py").exists()
    main(["cache", "rebuild", "--repo", str(tmp_path)])
    assert "Reparsed: 1" in capsys.readouterr().out


def test_parse_policy_change_rebuilds(tmp_path: Path) -> None:
    (tmp_path / "big.py").write_text("def useful(): pass\n", encoding="utf-8")
    small = RepositoryIndexer(GatewayConfig(tmp_path, max_file_size_bytes=10)).index()
    assert small.get_file("big.py").parse_status == "oversized"
    large = RepositoryIndexer(GatewayConfig(tmp_path, max_file_size_bytes=100)).index()
    assert large.find_symbol("useful") and large.stats.files_reparsed == 1


def test_git_metadata_and_changed_path(tmp_path: Path) -> None:
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except OSError:
        pytest.skip("git unavailable")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    result = RepositoryIndexer(GatewayConfig(tmp_path)).index()
    assert result.identity.has_git
    assert result.identity.head is None
    assert "auth.py" in result.changed_paths


def test_cache_contains_no_source_copy(tmp_path: Path) -> None:
    marker = "unique_source_only_72745"
    (tmp_path / "a.py").write_text(f"def f():\n    return '{marker}'\n", encoding="utf-8")
    RepositoryIndexer(GatewayConfig(tmp_path)).index()
    data = (tmp_path / ".middle_man_cache" / "index.json").read_text(encoding="utf-8")
    assert marker not in data
    assert json.loads(data)["schema_version"] == 1
