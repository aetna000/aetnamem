#!/usr/bin/env python3
"""Safe, explicit wrapper around AetnaMem Safe Switch commands."""

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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--state", help="Advanced: explicit Safe Switch state path")
    commands = root.add_subparsers(dest="operation", required=True)

    start = commands.add_parser("start")
    start.add_argument("--host", choices=("auto", "openclaw", "hermes"), default="auto")

    commands.add_parser("status")
    commands.add_parser("candidates")

    preview = commands.add_parser("preview")
    preview.add_argument("--query")

    for name in ("approve", "reject"):
        review = commands.add_parser(name)
        review.add_argument("candidate_ids", nargs="+")
        review.add_argument("--confirm", action="store_true")

    canary = commands.add_parser("canary")
    canary.add_argument("--turns", type=int, required=True)
    canary.add_argument("--confirm", action="store_true")

    for name in ("activate", "rollback", "off"):
        transition = commands.add_parser(name)
        transition.add_argument("--confirm", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    command = ["trial", args.operation]
    if args.state:
        command.extend(["--state", str(Path(args.state).expanduser())])

    if args.operation == "start":
        command.extend(["--host", args.host])
    elif args.operation == "preview":
        if args.query:
            command.extend(["--query", args.query])
    elif args.operation in {"approve", "reject"}:
        if not args.confirm:
            raise SystemExit(f"{args.operation} requires explicit --confirm")
        command.extend(args.candidate_ids)
    elif args.operation == "canary":
        if not args.confirm:
            raise SystemExit("canary requires explicit --confirm")
        if args.turns < 1:
            raise SystemExit("--turns must be at least 1")
        command.extend(["--turns", str(args.turns), "--yes"])
    elif args.operation in {"activate", "rollback", "off"}:
        if not args.confirm:
            raise SystemExit(f"{args.operation} requires explicit --confirm")
        if args.operation != "off":
            command.append("--yes")

    result = run_json(command)
    print(json.dumps({"operation": args.operation, "result": result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
