"""Independent semantic checks for guarded-action plans and receipts."""

from __future__ import annotations

from typing import Any

from aetnamem.actions.approval import Approval, ApprovalAuthority
from aetnamem.actions.models import digest_json
from aetnamem.actions.store import ActionStore
from aetnamem.store.sqlite import SQLiteStore


def verify_action(
    store: SQLiteStore,
    transaction_id: str,
    *,
    approval_authority: ApprovalAuthority | None = None,
) -> dict[str, Any]:
    actions = ActionStore(store)
    transaction = actions.get_transaction(transaction_id)
    if transaction is None:
        return {"valid": False, "failures": ["transaction not found"]}
    failures: list[str] = []
    if not store.verify_audit_chain(transaction["subject_id"]):
        failures.append("subject audit chain is invalid")
    if _recompute_plan_hash(transaction) != transaction["plan_hash"]:
        failures.append("persisted action plan does not match its plan hash")

    for approval_row in transaction["approvals"]:
        if approval_row["plan_hash"] != transaction["plan_hash"]:
            failures.append("approval plan hash does not match transaction")
        approval_document = {
            "transaction_id": transaction_id,
            "plan_hash": approval_row["plan_hash"],
            "approver": approval_row["approver_principal"],
            "issued_at": approval_row["issued_at"],
            "expires_at": approval_row["expires_at"],
            "nonce": approval_row["nonce"],
            "signature": approval_row["signature"],
            "format": "aetna-action-approval-v1",
        }
        if digest_json(approval_document) != approval_row["approval_digest"]:
            failures.append("approval digest is invalid")
        if approval_authority is not None:
            approval = Approval(
                transaction_id=transaction_id,
                plan_hash=approval_row["plan_hash"],
                approver=approval_row["approver_principal"],
                issued_at=approval_row["issued_at"],
                expires_at=approval_row["expires_at"],
                nonce=approval_row["nonce"],
                signature=approval_row["signature"],
            )
            # Verify signature/scope at issue time. Historical verification
            # must not fail simply because a once-valid approval has expired.
            from datetime import datetime

            if not approval_authority.verify(
                approval,
                transaction_id=transaction_id,
                plan_hash=transaction["plan_hash"],
                at=datetime.fromisoformat(approval.issued_at),
            ):
                failures.append("approval signature is invalid")

    for receipt in transaction["receipts"]:
        body = dict(receipt)
        claimed = body.pop("receipt_sha256", None)
        if claimed != digest_json(body):
            failures.append("action receipt digest is invalid")
            continue
        event = store.get_audit_event(transaction["subject_id"], receipt["audit_event_id"])
        if event is None or event["event_hash"] != receipt["audit_event_hash"]:
            failures.append("action receipt is not bound to its audit event")
        elif (
            event["payload"].get("transaction_id") != transaction_id
            or event["payload"].get("plan_hash") != receipt["plan_hash"]
            or event["payload"].get("terminal_state") != receipt["terminal_state"]
            or event["payload"].get("operations_digest")
            != digest_json(receipt["operation_receipts"])
        ):
            failures.append("action receipt content does not match its audit event")
        if receipt["plan_hash"] != transaction["plan_hash"]:
            failures.append("action receipt plan hash does not match transaction")
        if receipt["terminal_state"] != transaction["state"]:
            failures.append("action receipt terminal state does not match transaction")

    terminal = {
        "committed", "aborted", "compensated", "partial", "uncertain",
        "recovery_required",
    }
    if transaction["state"] in terminal and not transaction["receipts"]:
        failures.append("terminal transaction has no receipt")
    return {
        "valid": not failures,
        "transaction_id": transaction_id,
        "state": transaction["state"],
        "plan_hash": transaction["plan_hash"],
        "failures": failures,
    }


def _recompute_plan_hash(transaction: dict[str, Any]) -> str:
    operations: list[dict[str, Any]] = []
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
                "depends_on": sorted(operation["depends_on"]),
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
