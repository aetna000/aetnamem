from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.decisions.signing import (
    DecisionSigner,
    DecisionSignatureVerifier,
    SignatureEnvelope,
)


RECEIPT_FORMAT = "aetnamem-memory-impact-outcome-v1"


@dataclass(frozen=True)
class OutcomeAttestation:
    payload: dict[str, Any]
    signature: SignatureEnvelope

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.payload,
            "receipt_sha256": self.digest,
            "signature": self.signature.to_dict(),
        }


def issue_outcome_attestation(
    signer: DecisionSigner, payload: dict[str, Any]
) -> OutcomeAttestation:
    normalized = dict(payload)
    normalized["format"] = RECEIPT_FORMAT
    required = {
        "experiment_id",
        "block_id",
        "task_id",
        "run_id",
        "arm_id",
        "schedule_sha256",
        "protocol_sha256",
        "memory_snapshot_sha256",
        "metrology_sha256",
        "manifest_sha256",
        "stable_sha256",
        "dynamic_sha256",
        "output_sha256",
        "workspace_sha256",
        "verifier_sha256",
        "success",
        "metrics",
    }
    missing = sorted(required - normalized.keys())
    if missing:
        raise ValueError(f"outcome attestation missing: {', '.join(missing)}")
    digest = sha256_hex(canonical_json(normalized))
    return OutcomeAttestation(normalized, signer.sign_digest(digest))


def verify_outcome_attestation(
    value: dict[str, Any], verifier: DecisionSignatureVerifier
) -> bool:
    if value.get("format") != RECEIPT_FORMAT:
        return False
    signature_value = value.get("signature")
    if not isinstance(signature_value, dict):
        return False
    payload = {
        key: item
        for key, item in value.items()
        if key not in {"receipt_sha256", "signature"}
    }
    digest = sha256_hex(canonical_json(payload))
    if value.get("receipt_sha256") != digest:
        return False
    return verifier.verify_digest(
        digest, SignatureEnvelope.from_dict(signature_value)
    )


def write_attestation(path: str | Path, receipt: OutcomeAttestation) -> None:
    Path(path).write_text(
        json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
