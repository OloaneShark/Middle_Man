"""Run one separately authorized, pinned Codex native-read smoke process."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from middle_man.experiments.codex_native_read_smoke import load_plan, run_smoke
from middle_man.experiments.codex_pair import record_and_render
from middle_man.gateway.codex_runner.infrastructure import discover_codex


PLAN = Path(__file__).resolve().parents[1] / "docs/codex_windows_native_read_smoke_plan.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--confirm-external-service", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_external_service:
        parser.error("one external Codex process requires separate authorization and confirmation")
    snapshot = args.snapshot.resolve()
    receipt = args.receipt.resolve()
    if receipt.is_relative_to(snapshot) or receipt.exists():
        parser.error("receipt must be a new path outside the pinned source snapshot")
    load_plan(PLAN)
    observation = run_smoke(snapshot, PLAN, discover_codex(), confirm_external_service=True)
    rendering = record_and_render(observation, receipt, sys.stdout)
    if rendering != "RENDERED":
        print(rendering, file=sys.stderr)
    return 0 if observation.receipt["smoke_evaluation"]["passed"] and rendering == "RENDERED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
