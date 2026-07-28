#!/usr/bin/env python3
"""Guarded wrappers around AetnaMem's public memory CLI."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def aetnamem_command() -> list[str]:
    executable = shutil.which("aetnamem")
    return [executable] if executable else [sys.executable, "-m", "aetnamem.cli"]


def run_json(arguments: list[str]) -> Any:
    completed = subprocess.run(
        [*aetnamem_command(), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        if completed.stdout:
            print(completed.stdout, file=sys.stderr, end="")
        raise SystemExit(completed.returncode)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"AetnaMem returned non-JSON output: {exc}") from exc


def verify(db: str, subject: str) -> dict[str, Any]:
    result = run_json(["verify", db, "--subject", subject])
    if not result.get("valid"):
        raise SystemExit("AetnaMem audit verification failed after the operation")
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--db", default="~/.aetnamem/memories.db")
    root.add_argument("--subject", required=True)
    root.add_argument("--session")
    commands = root.add_subparsers(dest="operation", required=True)

    remember = commands.add_parser("remember")
    remember.add_argument("message")
    remember.add_argument(
        "--source-type",
        choices=("user_message", "webpage", "tool_output"),
        default="user_message",
    )

    find = commands.add_parser("find")
    find.add_argument("query")
    find.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="lexical")
    find.add_argument("--limit", type=int, default=20)

    listing = commands.add_parser("list")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--all", action="store_true")

    promote = commands.add_parser("promote")
    promote.add_argument("record_id")
    promote.add_argument("--confirm", action="store_true")

    forget = commands.add_parser("forget")
    forget.add_argument("--contains", required=True)
    forget.add_argument("--confirm", action="store_true")

    artifact = commands.add_parser("forget-artifact")
    artifact.add_argument("sha256")
    artifact.add_argument("--confirm", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    db = str(Path(args.db).expanduser())
    base = [db, args.subject]
    mutation = False

    if args.operation == "remember":
        command = ["remember", *base, args.message, "--source-type", args.source_type]
        if args.session:
            command.extend(["--session", args.session])
        mutation = True
    elif args.operation == "find":
        command = [
            "memories",
            db,
            "--subject",
            args.subject,
            "--query",
            args.query,
            "--mode",
            args.mode,
            "--limit",
            str(args.limit),
            "--format",
            "json",
        ]
    elif args.operation == "list":
        command = [
            "memories",
            db,
            "--subject",
            args.subject,
            "--limit",
            str(args.limit),
            "--format",
            "json",
        ]
        if args.all:
            command.append("--all")
    elif args.operation == "promote":
        if not args.confirm:
            raise SystemExit("promotion requires explicit --confirm")
        command = ["promote", *base, args.record_id]
        if args.session:
            command.extend(["--session", args.session])
        mutation = True
    elif args.operation == "forget":
        if not args.confirm:
            raise SystemExit("deletion requires explicit --confirm")
        command = ["forget", *base, "--contains", args.contains]
        if args.session:
            command.extend(["--session", args.session])
        mutation = True
    else:
        if not args.confirm:
            raise SystemExit("artifact deletion requires explicit --confirm")
        command = ["forget-artifact", *base, args.sha256]
        if args.session:
            command.extend(["--session", args.session])
        mutation = True

    result = run_json(command)
    envelope: dict[str, Any] = {"operation": args.operation, "result": result}
    if mutation:
        envelope["verification"] = verify(db, args.subject)
    print(json.dumps(envelope, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
