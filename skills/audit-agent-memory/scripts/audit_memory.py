#!/usr/bin/env python3
"""Verified search, trace, and export for an AetnaMem investigator."""

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
    root.add_argument("--db", default="~/.aetnamem/memories.db")
    root.add_argument("--subject", required=True)
    root.add_argument("--actor", required=True, help="Authenticated or asserted investigator ID")
    commands = root.add_subparsers(dest="operation", required=True)

    search = commands.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument(
        "--scope",
        choices=("all", "memories", "media", "episodes", "retrievals", "events", "runs", "actions"),
        default="all",
    )
    search.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="lexical")
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--output")

    trace = commands.add_parser("trace")
    trace.add_argument("query", nargs="?", default="")
    trace.add_argument("--record")
    trace.add_argument("--run")
    trace.add_argument("--session")
    trace.add_argument("--event-type")
    trace.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="lexical")
    trace.add_argument("--limit", type=int, default=200)
    trace.add_argument("--output")

    verification = commands.add_parser("verify")
    verification.add_argument("--output")
    return root


def write_report(payload: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        destination = Path(output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main() -> None:
    args = parser().parse_args()
    db = str(Path(args.db).expanduser())
    verification = run_json(["verify", db, "--subject", args.subject])
    if not verification.get("valid"):
        write_report({"operation": "verify", "verification": verification}, args.output)
        raise SystemExit("AetnaMem audit verification failed")

    if args.operation == "verify":
        write_report({"operation": "verify", "verification": verification}, args.output)
        return

    command = [
        args.operation,
        db,
        args.query,
        "--subject",
        args.subject,
        "--mode",
        args.mode,
        "--limit",
        str(args.limit),
        "--audit-access",
        "--access-actor",
        args.actor,
        "--format",
        "json",
    ]
    if args.operation == "search":
        command.extend(["--scope", args.scope])
    else:
        for flag, value in (
            ("--record", args.record),
            ("--run", args.run),
            ("--session", args.session),
            ("--event-type", args.event_type),
        ):
            if value:
                command.extend([flag, value])

    result = run_json(command)
    write_report(
        {
            "operation": args.operation,
            "investigator_actor": args.actor,
            "verification": verification,
            "result": result,
        },
        args.output,
    )


if __name__ == "__main__":
    main()
