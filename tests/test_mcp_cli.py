from __future__ import annotations

import json
from pathlib import Path

import pytest

from middle_man.cli.main import main
from middle_man.gateway.tokens import HeuristicTokenEstimator


def test_optional_sdk_absence_does_not_break_other_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("middle_man.cli.mcp.find_spec", lambda name: None)
    with pytest.raises(SystemExit, match="MCP support is optional"):
        main(["mcp", "serve", "--repo", str(tmp_path)])
    main(["index", "--repo", str(tmp_path)])
    assert "indexed" in capsys.readouterr().out.lower()


def test_usage_command_and_small_agent_instructions(tmp_path: Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    main(["mcp", "usage", "--repo", str(tmp_path), "--json"])
    assert json.loads(capsys.readouterr().out)["total_calls"] == 0
    instructions = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    assert HeuristicTokenEstimator().estimate(instructions) < 250
    assert "native" in instructions.lower()
