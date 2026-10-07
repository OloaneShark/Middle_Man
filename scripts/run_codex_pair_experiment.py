"""One confirmed arm of a preregistered read-only Codex experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from middle_man.experiments.codex_pair import SourcePin, record_and_render, run_arm
from middle_man.gateway.codex_runner.infrastructure import discover_codex
from middle_man.gateway.locator_shadow import load_shadow_corpus


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--arm", choices=("BASELINE", "MIDDLE_MAN"), required=True)
    parser.add_argument("--call-number", type=int)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--confirm-external-service", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_external_service:
        parser.error("external inference requires --confirm-external-service")
    snapshot = args.snapshot.resolve()
    receipt = args.receipt.resolve()
    if receipt.is_relative_to(snapshot) or receipt.exists():
        parser.error("receipt must be a new path outside the source snapshot")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if "schedule" in plan:
        schedule = plan["schedule"]
        if args.call_number is None or not 1 <= args.call_number <= len(schedule):
            parser.error("scheduled experiments require a valid --call-number")
        current = schedule[args.call_number - 1]
        if current["call"] != args.call_number or current["arm"] != args.arm:
            parser.error("arm differs from the locked schedule")
        if receipt.name != f"call-{args.call_number}.json":
            parser.error("scheduled receipt must be named call-N.json")
        for earlier in schedule[:args.call_number - 1]:
            previous = receipt.parent / f"call-{earlier['call']}.json"
            if not previous.is_file():
                parser.error("previous scheduled receipt is missing")
            completed = json.loads(previous.read_text(encoding="ascii"))
            if (completed.get("status") != "SUCCESS" or completed.get("arm") != earlier["arm"]
                    or completed.get("output_rendering") != "RENDERED"
                    or completed.get("task_sha256") != plan["task"]["task_sha256"]
                    or completed.get("source_commit") != plan["source"]["commit"]
                    or completed.get("source_tree") != plan["source"]["tree"]
                    or completed.get("cli_version") != plan["execution"]["expected_codex_cli_version"]
                    or completed.get("repository", {}).get("unchanged") is not True
                    or completed.get("metrics", {}).get("external_tool_activity_count") != 0
                    or completed.get("metrics", {}).get("mcp_call_count") != 0):
                parser.error("previous scheduled arm was not runtime-valid")
    tasks = {item["task_id"]: item for item in load_shadow_corpus(
        ROOT / "tests/fixtures/locator_shadow_corpus.json")["tasks"]}
    task = tasks[args.task_id]["task"]
    task_hash = hashlib.sha256(task.encode("utf-8")).hexdigest()
    spec = plan.get("task") or next(
        item for item in plan["tasks"] if item["task_id"] == args.task_id)
    if spec["task_sha256"] != task_hash:
        raise RuntimeError("task differs from the preregistered fixture")
    source = plan["source"]
    execution = plan["execution"]
    observation = run_arm(
        snapshot, task, arm=args.arm,
        pin=SourcePin(source["commit"], source["tree"], source["content_fingerprint"]),
        cli=discover_codex(), expected_cli_version=execution["expected_codex_cli_version"],
        timeout=execution["timeout_seconds"], model=execution["model"],
        effort=execution["reasoning_effort"])
    rendering = record_and_render(observation, receipt, sys.stdout)
    if rendering != "RENDERED":
        print(rendering, file=sys.stderr)
    return 0 if observation.receipt["status"] == "SUCCESS" and rendering == "RENDERED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
