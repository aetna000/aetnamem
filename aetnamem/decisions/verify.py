"""Offline verification for exported decision bundles.

Structural verification uses the Python standard library and documented v1
preimages. Optional Ed25519 verification uses the ``signing`` extra. The
verifier does not instantiate the decision engine or trust its transitions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aetnamem.decisions.signing import (
    DecisionSignatureVerifier,
    Ed25519Verifier,
    SignatureEnvelope,
    receipt_digest,
)


def verify_bundle(
    bundle: dict[str, Any],
    *,
    signature_verifier: DecisionSignatureVerifier | None = None,
    require_signatures: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    body = dict(bundle)
    claimed_bundle = body.pop("bundle_digest", None)
    if claimed_bundle != _digest(body):
        failures.append("bundle digest mismatch")

    template = bundle.get("template") or {}
    if bundle.get("case", {}).get("template_digest") != _digest(template):
        failures.append("template digest mismatch")
    purged: dict[tuple[str, str], str] = {}
    for receipt in bundle.get("purge_receipts", []):
        body = {
            "format": "aetnamem-decision-purge-receipt-v1",
            "receipt_id": receipt["id"],
            "case_id": receipt["case_id"],
            "categories": receipt["categories"],
            "cutoffs": receipt["cutoffs"],
            "items": receipt["items"],
            "purged_by": receipt["purged_by"],
            "created_at": receipt["created_at"],
        }
        if receipt["digest"] != _digest(body):
            failures.append(f"purge receipt digest mismatch: {receipt['id']}")
        for item in receipt["items"]:
            purged[(item["kind"], item["id"])] = item["prior_digest"]

    case = bundle.get("case") or {}
    if case.get("content_purged_at"):
        purged_case_digest = next(
            (value for (kind, _), value in purged.items() if kind == "case_revision"), None
        )
        if purged_case_digest is None:
            failures.append("case revision is purged without a purge receipt")
        elif purged_case_digest != case.get("case_digest"):
            failures.append("case revision purge receipt mismatch")

    revisions = {row["id"]: row for row in bundle.get("revisions", [])}
    for revision in revisions.values():
        if revision.get("purged_at"):
            if purged.get(("artifact_revision", revision["id"])) != revision["digest"]:
                failures.append(f"artifact purge receipt mismatch: {revision['id']}")
        else:
            expected = _digest(
                {
                    "format": "aetnamem-decision-artifact-v1",
                    "artifact_id": revision["artifact_id"],
                    "revision": revision["revision"],
                    "kind": revision["kind"],
                    "content": revision["content"],
                    "author": revision["author"],
                }
            )
            if revision["digest"] != expected:
                failures.append(f"artifact revision digest mismatch: {revision['id']}")
        for link in revision.get("links", []):
            source = revisions.get(link["source_revision_id"])
            if source is None or source["digest"] != link["source_digest"]:
                failures.append(f"artifact link mismatch: {revision['id']}")

    outcomes: dict[str, dict[str, Any]] = {}
    for ballot in bundle.get("ballots", []):
        if ballot["policy_digest"] != _digest(ballot["policy"]):
            failures.append(f"ballot policy digest mismatch: {ballot['id']}")
        for vote in ballot.get("votes", []):
            if vote.get("purged_at"):
                if purged.get(("vote", vote["id"])) != vote["commitment"]:
                    failures.append(f"vote purge receipt mismatch: {vote['id']}")
                continue
            rationale = vote.get("rationale") or {}
            expected = _digest(
                {
                    "format": "aetnamem-decision-vote-v1",
                    "ballot_id": ballot["id"],
                    "principal_id": vote["principal_id"],
                    "revision": vote["revision"],
                    "choice": vote["choice"],
                    "rationale": rationale.get("text", ""),
                    "salt": vote["salt"],
                }
            )
            if expected != vote["commitment"]:
                failures.append(f"vote commitment mismatch: {vote['id']}")
        outcome_row = ballot.get("outcome")
        if outcome_row:
            outcome = dict(outcome_row["outcome"])
            claimed = outcome.pop("digest", None)
            if claimed != _digest(outcome) or outcome_row["digest"] != claimed:
                failures.append(f"ballot outcome digest mismatch: {outcome_row['id']}")
            outcomes[outcome_row["id"]] = outcome_row

    adoptions: dict[str, dict[str, Any]] = {}
    for adoption in bundle.get("adoptions", []):
        outcome = outcomes.get(adoption["outcome_id"])
        expected = _digest(
            {
                "format": "aetnamem-decision-adoption-v1",
                "adoption_id": adoption["id"],
                "case_id": adoption["case_id"],
                "target_revision_id": adoption["target_revision_id"],
                "target_digest": adoption["target_digest"],
                "outcome_id": adoption["outcome_id"],
                "outcome_digest": outcome["digest"] if outcome else None,
                "adopted_by": adoption["adopted_by"],
            }
        )
        if outcome is None or adoption["digest"] != expected:
            failures.append(f"adoption digest mismatch: {adoption['id']}")
        adoptions[adoption["id"]] = adoption

    approvals: dict[str, dict[str, Any]] = {}
    for approval in bundle.get("approvals", []):
        if approval.get("purged_at"):
            if purged.get(("approval", approval["id"])) != approval["digest"]:
                failures.append(f"approval purge receipt mismatch: {approval['id']}")
            approvals[approval["id"]] = approval
            continue
        expected = _digest(
            {
                "format": "aetnamem-decision-approval-v1",
                "approval_id": approval["id"],
                "case_id": approval["case_id"],
                "target_revision_id": approval["target_revision_id"],
                "target_digest": approval["target_digest"],
                "principal_id": approval["principal_id"],
                "decision": approval["decision"],
                "rationale_digest": _digest((approval.get("rationale") or {}).get("text", "")),
            }
        )
        if approval["digest"] != expected:
            failures.append(f"approval digest mismatch: {approval['id']}")
        approvals[approval["id"]] = approval

    for authorization in bundle.get("authorizations", []):
        adoption = adoptions.get(authorization["adoption_id"])
        approval_rows = [approvals.get(item) for item in authorization["approval_ids"]]
        expected = _digest(
            {
                "format": "aetnamem-decision-authorization-v1",
                "authorization_id": authorization["id"],
                "case_id": authorization["case_id"],
                "plan_revision_id": authorization["plan_revision_id"],
                "plan_digest": authorization["plan_digest"],
                "adoption_id": authorization["adoption_id"],
                "adoption_digest": adoption["digest"] if adoption else None,
                "approval_digests": sorted(row["digest"] for row in approval_rows if row),
                "scope": authorization["scope"],
                "expires_at": authorization["expires_at"],
                "granted_by": authorization["granted_by"],
            }
        )
        if any(row is None for row in approval_rows) or adoption is None or authorization["digest"] != expected:
            failures.append(f"authorization digest mismatch: {authorization['id']}")

    expected_objects: dict[tuple[str, str], str] = {}
    expected_objects.update({("ballot_outcome", key): row["digest"] for key, row in outcomes.items()})
    expected_objects.update({("adoption", key): row["digest"] for key, row in adoptions.items()})
    expected_objects.update({("approval", key): row["digest"] for key, row in approvals.items()})
    expected_objects.update(
        {("authorization", row["id"]): row["digest"] for row in bundle.get("authorizations", [])}
    )
    expected_objects.update({("purge", row["id"]): row["digest"] for row in bundle.get("purge_receipts", [])})
    signatures = bundle.get("signatures", [])
    checked = 0
    for record in signatures:
        actual_digest = expected_objects.get((record["object_kind"], record["object_id"]))
        if actual_digest != record["object_digest"]:
            failures.append(f"signed receipt object mismatch: {record['id']}")
            continue
        expected_receipt = receipt_digest(record["object_kind"], record["object_id"], record["object_digest"])
        if record["receipt_digest"] != expected_receipt:
            failures.append(f"signed receipt digest mismatch: {record['id']}")
            continue
        try:
            envelope = SignatureEnvelope.from_dict(record["signature"])
        except (KeyError, TypeError, ValueError):
            failures.append(f"malformed signature envelope: {record['id']}")
            continue
        if envelope.signed_digest != expected_receipt:
            failures.append(f"signature preimage mismatch: {record['id']}")
        elif signature_verifier is not None:
            checked += 1
            if not signature_verifier.verify_digest(expected_receipt, envelope):
                failures.append(f"signature verification failed: {record['id']}")
    if require_signatures and not signatures:
        failures.append("bundle contains no signed decision receipts")
    if require_signatures and signature_verifier is None:
        failures.append("signature verification was required but no public keys were supplied")

    return {
        "valid": not failures,
        "failures": failures,
        "format": bundle.get("format"),
        "signatures_present": len(signatures),
        "signatures_verified": checked,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aetnamem-etd-verify")
    parser.add_argument("bundle")
    parser.add_argument(
        "--public-key",
        action="append",
        default=[],
        metavar="KEY_ID=PEM_PATH",
        help="Ed25519 public key used to verify signed receipts (repeatable)",
    )
    parser.add_argument("--require-signatures", action="store_true")
    args = parser.parse_args(argv)
    keys: dict[str, bytes] = {}
    for value in args.public_key:
        if "=" not in value:
            parser.error("--public-key must use KEY_ID=PEM_PATH")
        key_id, path = value.split("=", 1)
        keys[key_id] = Path(path).read_bytes()
    verifier = Ed25519Verifier.from_public_pems(keys) if keys else None
    result = verify_bundle(
        json.loads(Path(args.bundle).read_text("utf-8")),
        signature_verifier=verifier,
        require_signatures=args.require_signatures,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["valid"] else 1)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()
