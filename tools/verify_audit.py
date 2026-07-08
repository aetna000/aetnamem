#!/usr/bin/env python3
"""Standalone aetnamem audit verifier.

Deliberately imports nothing from aetnamem: it is an independent
implementation of docs/audit-log-spec.md using only the Python standard
library, so an auditor can check a database without trusting the engine's
own code. Exit code 0 means every checked chain (and checkpoint) verified.

Usage:
    python tools/verify_audit.py memories.db [--subject SUBJECT]
                                             [--checkpoints checkpoints.jsonl]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def event_hash(event: dict) -> str:
    preimage = {
        "event_id": event["event_id"],
        "subject_id": event["subject_id"],
        "event_type": event["event_type"],
        "created_at": event["created_at"],
        "actor": event["actor"],
        "session_id": event["session_id"],
        "turn_id": event["turn_id"],
        "record_id": event["record_id"],
        "payload": json.loads(event["payload"]),
        "prev_hash": event["prev_hash"],
    }
    return sha256_hex(canonical_json(preimage))


def verify_chain(conn: sqlite3.Connection, subject_id: str) -> list[str]:
    failures: list[str] = []
    previous_hash = None
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE subject_id = ? ORDER BY sequence ASC",
        (subject_id,),
    ).fetchall()
    for row in rows:
        event = dict(row)
        if event["prev_hash"] != previous_hash:
            failures.append(
                f"sequence {event['sequence']}: prev_hash does not chain"
            )
        expected = event_hash({**event, "prev_hash": previous_hash})
        if event["event_hash"] != expected:
            failures.append(
                f"sequence {event['sequence']}: event_hash mismatch"
            )
        previous_hash = event["event_hash"]
    return failures


def verify_checkpoints(
    conn: sqlite3.Connection, subject_ids: list[str], checkpoints_path: str
) -> dict[str, list[str]]:
    failures: dict[str, list[str]] = {sid: [] for sid in subject_ids}
    with open(checkpoints_path, "r", encoding="utf-8") as handle:
        documents = [json.loads(line) for line in handle if line.strip()]
    for document in documents:
        body = dict(document)
        claimed = body.pop("checkpoint_sha256", None)
        label = document.get("created_at", "?")
        if sha256_hex(canonical_json(body)) != claimed:
            for sid in failures:
                failures[sid].append(f"checkpoint {label}: digest mismatch")
            continue
        for sid, pinned in document.get("subjects", {}).items():
            if sid not in failures:
                continue
            row = conn.execute(
                "SELECT event_hash FROM audit_log WHERE subject_id = ? AND sequence = ?",
                (sid, pinned["sequence"]),
            ).fetchone()
            if row is None:
                failures[sid].append(
                    f"checkpoint {label}: pinned sequence {pinned['sequence']} "
                    "missing (tail truncated?)"
                )
            elif row["event_hash"] != pinned["event_hash"]:
                failures[sid].append(
                    f"checkpoint {label}: hash mismatch at sequence "
                    f"{pinned['sequence']}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--subject", default=None)
    parser.add_argument("--checkpoints", default=None)
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    if args.subject:
        subject_ids = [args.subject]
    else:
        subject_ids = [
            row["subject_id"]
            for row in conn.execute(
                "SELECT DISTINCT subject_id FROM audit_log ORDER BY subject_id"
            )
        ]

    all_failures: dict[str, list[str]] = {
        sid: verify_chain(conn, sid) for sid in subject_ids
    }
    if args.checkpoints:
        for sid, extra in verify_checkpoints(
            conn, subject_ids, args.checkpoints
        ).items():
            all_failures[sid].extend(extra)

    ok = True
    for sid in subject_ids:
        failures = all_failures[sid]
        if failures:
            ok = False
            print(f"FAIL {sid}")
            for failure in failures:
                print(f"  - {failure}")
        else:
            print(f"OK   {sid}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
