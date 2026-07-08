from __future__ import annotations

import argparse
import json
import sys

from aetnamem.memory import Memory


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetnamem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Dump a subject's records, episodes, and audit trail"
    )
    inspect_parser.add_argument("path")
    inspect_parser.add_argument("subject_id")

    audit_parser = subparsers.add_parser(
        "audit", help="Dump a subject's audit log and verify the hash chain"
    )
    audit_parser.add_argument("path")
    audit_parser.add_argument("subject_id")

    checkpoint_parser = subparsers.add_parser(
        "checkpoint",
        help="Snapshot all audit-chain heads; anchor the output externally",
    )
    checkpoint_parser.add_argument("path")
    checkpoint_parser.add_argument(
        "sink", nargs="?", help="JSONL file to append the checkpoint to"
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify audit-chain integrity, optionally against checkpoints",
    )
    verify_parser.add_argument("path")
    verify_parser.add_argument("--subject", default=None)
    verify_parser.add_argument(
        "--checkpoints", default=None, help="JSONL checkpoint file to check against"
    )

    args = parser.parse_args()
    memory = Memory(args.path)

    if args.command == "inspect":
        print(json.dumps(memory.inspect(args.subject_id), indent=2, sort_keys=True))
    elif args.command == "audit":
        print(json.dumps(memory.audit(args.subject_id), indent=2, sort_keys=True))
    elif args.command == "checkpoint":
        document = memory.checkpoint(sink_path=args.sink)
        print(json.dumps(document, indent=2, sort_keys=True))
    elif args.command == "verify":
        result = memory.verify(
            args.subject, checkpoints_path=args.checkpoints
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        if not result["valid"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
