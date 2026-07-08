from __future__ import annotations

import argparse
import json

from aetnamem.memory import Memory


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetnamem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("path")
    inspect_parser.add_argument("subject_id")

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("path")
    audit_parser.add_argument("subject_id")

    args = parser.parse_args()
    memory = Memory(args.path)

    if args.command == "inspect":
        print(json.dumps(memory.inspect(args.subject_id), indent=2, sort_keys=True))
    elif args.command == "audit":
        print(json.dumps(memory.audit(args.subject_id), indent=2, sort_keys=True))
