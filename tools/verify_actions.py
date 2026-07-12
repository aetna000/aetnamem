#!/usr/bin/env python3
"""Standalone aetnamem Guarded Actions verifier (stdlib only).

This program deliberately imports nothing from ``aetnamem``. It verifies the
subject audit chain, recomputes the WorldPatch plan hash, checks approval scope
and optional HMAC signatures, and validates terminal receipt bindings.

Usage:
    python tools/verify_actions.py memories.db act_...
    python tools/verify_actions.py memories.db act_... --approval-key-file reviewer.key
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys

from verify_audit import canonical_json, sha256_hex, verify_chain


def digest_json(value) -> str:
    return sha256_hex(canonical_json(value))


def load_transaction(conn: sqlite3.Connection, transaction_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM action_transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if row is None:
        return None
    transaction = dict(row)
    operations = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM action_operations WHERE transaction_id = ? ORDER BY ordinal",
            (transaction_id,),
        )
    ]
    for operation in operations:
        operation["depends_on"] = sorted(
            item["depends_on_operation_id"]
            for item in conn.execute(
                "SELECT depends_on_operation_id FROM action_dependencies WHERE operation_id = ?",
                (operation["id"],),
            )
        )
        evidence = [
            dict(item)
            for item in conn.execute(
                "SELECT * FROM action_evidence WHERE operation_id = ?",
                (operation["id"],),
            )
        ]
        operation["evidence"] = evidence
    transaction["operations"] = operations
    transaction["approvals"] = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM action_approvals WHERE transaction_id = ? ORDER BY created_at",
            (transaction_id,),
        )
    ]
    transaction["receipts"] = [
        json.loads(item["receipt_json"])
        for item in conn.execute(
            "SELECT receipt_json FROM action_receipts WHERE transaction_id = ? ORDER BY created_at",
            (transaction_id,),
        )
    ]
    return transaction


def plan_hash(transaction: dict) -> str:
    operations = []
    for operation in transaction["operations"]:
        evidence = [
            {
                "kind": item["evidence_kind"],
                "ref_id": item["ref_id"],
                "digest": item["digest"],
                "relation": item["relation"],
                "trust_tier": item["trust_tier"],
                "attested": bool(item["attested"]),
            }
            for item in operation["evidence"]
        ]
        evidence.sort(
            key=lambda item: (
                item["relation"], item["kind"], item["ref_id"], item["digest"]
            )
        )
        operations.append(
            {
                "id": operation["id"],
                "key": operation["operation_key"],
                "ordinal": operation["ordinal"],
                "adapter": operation["adapter"],
                "operation": operation["operation"],
                "effect_class": operation["effect_class"],
                "arguments_digest": operation["arguments_digest"],
                "preview_digest": operation["preview_digest"],
                "precondition_digest": operation["precondition_digest"],
                "manifest_digest": operation["manifest_digest"],
                "depends_on": operation["depends_on"],
                "evidence": evidence,
            }
        )
    return digest_json(
        {
            "format": "aetna-world-patch-v1",
            "transaction_id": transaction["id"],
            "subject_id": transaction["subject_id"],
            "actor_id": transaction["actor_id"],
            "mode": transaction["mode"],
            "plan_version": transaction["plan_version"],
            "policy_hash": transaction["policy_hash"],
            "operations": operations,
        }
    )


def verify(
    conn: sqlite3.Connection,
    transaction_id: str,
    approval_secret: bytes | None = None,
) -> list[str]:
    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        return ["transaction not found"]
    failures = verify_chain(conn, transaction["subject_id"])
    if plan_hash(transaction) != transaction["plan_hash"]:
        failures.append("persisted action plan does not match its plan hash")

    proposed = False
    for row in conn.execute(
        "SELECT payload FROM audit_log WHERE subject_id = ? AND event_type = 'action.proposed'",
        (transaction["subject_id"],),
    ):
        payload = json.loads(row["payload"])
        if payload.get("transaction_id") == transaction_id:
            proposed = payload.get("plan_hash") == transaction["plan_hash"]
            break
    if not proposed:
        failures.append("no matching action.proposed audit event")

    for approval in transaction["approvals"]:
        if approval["plan_hash"] != transaction["plan_hash"]:
            failures.append("approval does not bind the transaction plan hash")
        approval_document = {
            "transaction_id": transaction_id,
            "plan_hash": approval["plan_hash"],
            "approver": approval["approver_principal"],
            "issued_at": approval["issued_at"],
            "expires_at": approval["expires_at"],
            "nonce": approval["nonce"],
            "signature": approval["signature"],
            "format": "aetna-action-approval-v1",
        }
        if digest_json(approval_document) != approval["approval_digest"]:
            failures.append("approval digest is invalid")
        if approval_secret is not None:
            payload = {
                "transaction_id": transaction_id,
                "plan_hash": approval["plan_hash"],
                "approver": approval["approver_principal"],
                "issued_at": approval["issued_at"],
                "expires_at": approval["expires_at"],
                "nonce": approval["nonce"],
                "format": "aetna-action-approval-v1",
            }
            expected = hmac.new(
                approval_secret,
                canonical_json(payload).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, approval["signature"]):
                failures.append("approval signature is invalid")

    terminal = {
        "committed", "aborted", "compensated", "partial", "uncertain",
        "recovery_required",
    }
    if transaction["state"] in terminal and not transaction["receipts"]:
        failures.append("terminal transaction has no receipt")
    for receipt in transaction["receipts"]:
        body = dict(receipt)
        claimed = body.pop("receipt_sha256", None)
        if claimed != digest_json(body):
            failures.append("action receipt digest is invalid")
            continue
        event = conn.execute(
            "SELECT event_hash, payload FROM audit_log WHERE subject_id = ? AND event_id = ?",
            (transaction["subject_id"], receipt["audit_event_id"]),
        ).fetchone()
        if event is None or event["event_hash"] != receipt["audit_event_hash"]:
            failures.append("action receipt is not bound to its audit event")
        else:
            payload = json.loads(event["payload"])
            if (
                payload.get("transaction_id") != transaction_id
                or payload.get("plan_hash") != receipt["plan_hash"]
                or payload.get("terminal_state") != receipt["terminal_state"]
                or payload.get("operations_digest")
                != digest_json(receipt["operation_receipts"])
            ):
                failures.append("action receipt content does not match its audit event")
        if receipt["plan_hash"] != transaction["plan_hash"]:
            failures.append("receipt plan hash does not match transaction")
        if receipt["terminal_state"] != transaction["state"]:
            failures.append("receipt terminal state does not match transaction")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("transaction_id")
    parser.add_argument("--approval-key-file", default=None)
    args = parser.parse_args()

    secret = None
    if args.approval_key_file:
        secret = Path(args.approval_key_file).read_bytes().strip()
        if len(secret) < 32:
            parser.error("approval key must contain at least 32 bytes")
    conn = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    failures = verify(conn, args.transaction_id, secret)
    if failures:
        print(f"FAIL {args.transaction_id}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"OK   {args.transaction_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
