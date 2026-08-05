"""Stable and run-specific digests for control-plane evidence.

Callers construct the stable projection explicitly.  This is deliberate:
receipt formats have different volatile fields, and recursively dropping a
generic set of names can silently weaken a future evidence format.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from aetnamem.core.canonical import canonical_json, sha256_hex


ZERO_SHA256 = "0" * 64


def seal_report(
    body: Mapping[str, Any], *, stable_evidence: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a report carrying stable-state and complete-run digests."""

    if "report_sha256" in body or "evidence_sha256" in body:
        raise ValueError("report body must not contain precomputed digests")
    stable = deepcopy(dict(stable_evidence))
    evidence_sha256 = sha256_hex(canonical_json(stable))
    report = {**deepcopy(dict(body)), "evidence_sha256": evidence_sha256}
    report_sha256 = sha256_hex(canonical_json(report))
    return {**report, "report_sha256": report_sha256}


def verify_report(
    report: Mapping[str, Any], *, stable_evidence: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify both digests using the format-specific stable projection."""

    body = deepcopy(dict(report))
    reported_report = str(body.pop("report_sha256", ""))
    reported_evidence = str(body.pop("evidence_sha256", ""))
    expected_evidence = sha256_hex(canonical_json(dict(stable_evidence)))
    expected_report = sha256_hex(
        canonical_json({**body, "evidence_sha256": reported_evidence})
    )
    errors: list[str] = []
    if reported_evidence != expected_evidence:
        errors.append("evidence_sha256 mismatch")
    if reported_report != expected_report:
        errors.append("report_sha256 mismatch")
    return {
        "valid": not errors,
        "evidence_sha256": reported_evidence,
        "report_sha256": reported_report,
        "errors": errors,
    }


def evidence_entry_sha256(
    *,
    previous_sha256: str,
    migration_id: str,
    kind: str,
    sequence: int,
    body_sha256: str,
) -> str:
    """Bind one stored evidence body to its chain identity and position."""

    return sha256_hex(
        canonical_json(
            {
                "prev_sha256": previous_sha256,
                "migration_id": migration_id,
                "kind": kind,
                "sequence": sequence,
                "body_sha256": body_sha256,
            }
        )
    )
