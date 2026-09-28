"""CLI presentation for Project Memory and Session Handoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from middle_man.gateway.compact import OutputCompactor
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.handoff import HandoffService, context_reference_from_json, format_handoff, handoff_view_dict
from middle_man.gateway.project_memory import ProjectMemoryService, format_project_memory


def _repo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=Path.cwd())


def add_state_commands(subparsers: argparse._SubParsersAction) -> None:
    memory = subparsers.add_parser("memory", help="manage factual local Project Memory")
    memory_actions = memory.add_subparsers(dest="memory_action", required=True)
    for name in ("show", "refresh", "status"):
        _repo(memory_actions.add_parser(name))
    decisions = memory_actions.add_parser("decision")
    decision_actions = decisions.add_subparsers(dest="note_action", required=True)
    add_decision = decision_actions.add_parser("add")
    add_decision.add_argument("text")
    add_decision.add_argument("--category")
    add_decision.add_argument("--supersedes")
    _repo(add_decision)
    _repo(decision_actions.add_parser("list"))
    remove_decision = decision_actions.add_parser("remove")
    remove_decision.add_argument("id")
    _repo(remove_decision)
    issues = memory_actions.add_parser("issue")
    issue_actions = issues.add_subparsers(dest="note_action", required=True)
    add_issue = issue_actions.add_parser("add")
    add_issue.add_argument("text")
    add_issue.add_argument("--category")
    _repo(add_issue)
    _repo(issue_actions.add_parser("list"))
    resolve_issue = issue_actions.add_parser("resolve")
    resolve_issue.add_argument("id")
    _repo(resolve_issue)

    handoff = subparsers.add_parser("handoff", help="create and inspect factual session handoffs")
    handoff_actions = handoff.add_subparsers(dest="handoff_action", required=True)
    create = handoff_actions.add_parser("create")
    create.add_argument("--task", required=True)
    create.add_argument("--context-pack", type=Path)
    create.add_argument("--pytest-output", type=Path)
    create.add_argument("--pytest-stdin", action="store_true")
    create.add_argument("--tool-output", type=Path)
    create.add_argument("--issue", action="append", default=[])
    create.add_argument("--next-step", action="append", default=[])
    _repo(create)
    latest = handoff_actions.add_parser("latest")
    latest.add_argument("--json", action="store_true")
    _repo(latest)
    show = handoff_actions.add_parser("show")
    show.add_argument("id")
    show.add_argument("--json", action="store_true")
    _repo(show)
    _repo(handoff_actions.add_parser("list"))


def run_state(args: argparse.Namespace) -> None:
    config = GatewayConfig(args.repo)
    if args.command == "memory":
        service = ProjectMemoryService(config)
        if args.memory_action == "refresh":
            memory = service.refresh()
        elif args.memory_action in {"show", "status"}:
            memory = service.load() or service.refresh()
        elif args.memory_action == "decision":
            if args.note_action == "add":
                memory = service.add_decision(args.text, category=args.category, supersedes=args.supersedes)
            elif args.note_action == "remove":
                memory = service.remove_decision(args.id)
            else:
                memory = service.load() or service.refresh()
            if args.note_action == "list":
                print("DECISIONS (user supplied)")
                for note in memory.decisions:
                    print(f"{note.id}  {note.text}" + (f" [{note.category}]" if note.category else ""))
                return
        else:
            if args.note_action == "add":
                memory = service.add_issue(args.text, category=args.category)
            elif args.note_action == "resolve":
                memory = service.resolve_issue(args.id)
            else:
                memory = service.load() or service.refresh()
            if args.note_action == "list":
                print("KNOWN ISSUES (user supplied)")
                for note in memory.issues:
                    print(f"{note.id}  {'resolved' if note.resolved else 'open'}  {note.text}")
                return
        if args.memory_action == "status":
            print(f"Project Memory: {memory.repository_name}  branch: {memory.branch or '(none)'}  HEAD: {memory.head or '(none)'}")
            print(f"Components: {memory.metrics.component_count}  Decisions: {memory.metrics.decision_count}  Issues: {memory.metrics.issue_count}")
            print(f"Size: {memory.metrics.serialized_bytes} bytes / ~{memory.metrics.estimated_tokens} tokens")
            print(f"Fingerprint: {memory.fingerprint}")
        else:
            print(format_project_memory(memory), end="")
        return

    service = HandoffService(config)
    if args.handoff_action == "create":
        if args.pytest_output and args.pytest_stdin:
            raise ValueError("use either --pytest-output or --pytest-stdin")
        context = None
        if args.context_pack:
            data = json.loads(args.context_pack.read_text(encoding="utf-8"))
            context = context_reference_from_json(data, config)
        compactor = OutputCompactor()
        results = []
        if args.pytest_output:
            results.append(compactor.compact("pytest", args.pytest_output.read_text(encoding="utf-8"), max_tokens=1200))
        if args.pytest_stdin:
            results.append(compactor.compact("pytest", sys.stdin.read(), max_tokens=1200))
        if args.tool_output:
            results.append(compactor.compact("log", args.tool_output.read_text(encoding="utf-8"), max_tokens=1200))
        handoff = service.create(args.task, context=context, tool_results=tuple(results),
                                 issues=tuple(args.issue), next_steps=tuple(args.next_step))
        print(format_handoff(service.view(handoff)), end="")
    elif args.handoff_action == "list":
        print("MIDDLE_MAN SESSION HANDOFFS")
        for handoff in service.list():
            view = service.view(handoff)
            print(f"{handoff.fingerprint[:12]}  {handoff.created_at}  {handoff.branch or '(none)'}  "
                  f"{'stale' if view.is_stale else 'current'}  {handoff.task}")
    else:
        handoff = service.latest() if args.handoff_action == "latest" else service.load(args.id)
        view = service.view(handoff)
        print(json.dumps(handoff_view_dict(view), indent=2, ensure_ascii=False) if args.json else format_handoff(view), end="\n" if args.json else "")
