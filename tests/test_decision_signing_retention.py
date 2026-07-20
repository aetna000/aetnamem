from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64

import pytest

from aetnamem.decisions import (
    ActorContext,
    ConsensusPolicy,
    DecisionEngine,
    DecisionPolicyViolation,
    DecisionStateError,
    Ed25519Signer,
    AwsKmsSigner,
    AwsKmsVerifier,
    issue_principal_attestation,
)
from aetnamem.decisions.verify import verify_bundle
from aetnamem.etd import clinical_etd_template
from aetnamem.etd.playground import run_demo


def _attested(signer: Ed25519Signer, namespace: str, principal: str) -> ActorContext:
    assurance = "asymmetric_host_attested"
    attestation = issue_principal_attestation(
        signer,
        namespace_id=namespace,
        principal_id=principal,
        assurance=assurance,
    )
    return ActorContext(namespace, principal, assurance=assurance, attestation=attestation.to_dict())


def test_attestations_and_signed_decision_receipts_are_verified(tmp_path) -> None:
    signer = Ed25519Signer.generate(key_id="hospital-governance-2026")
    verifier = signer.verifier()
    engine = DecisionEngine(
        str(tmp_path / "signed.db"),
        receipt_signer=signer,
        attestation_verifier=verifier,
        require_attestations=True,
    )
    chair = _attested(signer, "hospital", "chair")
    case = engine.create_case(
        chair,
        title="Signed decision",
        template=clinical_etd_template(),
        content={"question": "Should the signed change proceed?"},
        idempotency_key="case",
    )
    recommendation = engine.create_artifact(
        chair,
        case["id"],
        kind="recommendation",
        content={"text": "Proceed", "direction": "for", "strength": "conditional"},
        idempotency_key="recommendation",
    )
    ballot = engine.open_ballot(
        chair,
        case["id"],
        target_revision_id=recommendation["revision_id"],
        choices=("yes", "no"),
        policy=ConsensusPolicy(quorum=1.0, threshold=1.0),
        idempotency_key="ballot",
    )
    engine.cast_vote(chair, ballot["id"], choice="yes", idempotency_key="vote")
    outcome = engine.close_ballot(chair, ballot["id"], expected_version=1, idempotency_key="close")
    assert outcome["signed_receipt"]["signature"]["algorithm"] == "Ed25519"
    bundle = engine.export_case(chair, case["id"])
    verified = verify_bundle(bundle, signature_verifier=verifier, require_signatures=True)
    assert verified["valid"] is True
    assert verified["signatures_verified"] == 1

    tampered = engine.export_case(chair, case["id"])
    tampered["signatures"][0]["signature"]["signature"] = base64.b64encode(b"invalid").decode()
    body = dict(tampered)
    body.pop("bundle_digest")
    from aetnamem.decisions.models import digest_json

    tampered["bundle_digest"] = digest_json(body)
    assert verify_bundle(tampered, signature_verifier=verifier, require_signatures=True)["valid"] is False
    engine.close()


def test_required_attestation_rejects_unsigned_or_wrong_principal(tmp_path) -> None:
    signer = Ed25519Signer.generate()
    engine = DecisionEngine(
        str(tmp_path / "required.db"),
        attestation_verifier=signer.verifier(),
        require_attestations=True,
    )
    with pytest.raises(DecisionPolicyViolation, match="required"):
        engine.create_case(
            ActorContext("hospital", "chair"),
            title="No attestation",
            template=clinical_etd_template(),
            content={},
            idempotency_key="missing",
        )
    valid_for_other = issue_principal_attestation(
        signer, namespace_id="hospital", principal_id="other", assurance="asymmetric_host_attested"
    )
    with pytest.raises(DecisionPolicyViolation, match="invalid"):
        engine.create_case(
            ActorContext(
                "hospital",
                "chair",
                assurance="asymmetric_host_attested",
                attestation=valid_for_other.to_dict(),
            ),
            title="Wrong principal",
            template=clinical_etd_template(),
            content={},
            idempotency_key="wrong",
        )
    engine.close()


def test_complete_etd_chain_signs_all_governance_receipts(tmp_path) -> None:
    signer = Ed25519Signer.generate(key_id="full-chain-key")
    engine = DecisionEngine(str(tmp_path / "full-chain.db"), receipt_signer=signer)
    result = run_demo(None, namespace_id="signed-playground", engine=engine)
    verified = verify_bundle(
        result["bundle"], signature_verifier=signer.verifier(), require_signatures=True
    )
    assert verified["valid"] is True
    assert verified["signatures_verified"] == 4
    assert {row["object_kind"] for row in result["bundle"]["signatures"]} == {
        "ballot_outcome", "adoption", "approval", "authorization"
    }
    engine.close()


def test_retention_purges_payloads_and_coi_with_signed_receipt(tmp_path) -> None:
    signer = Ed25519Signer.generate(key_id="retention-key")
    engine = DecisionEngine(str(tmp_path / "retention.db"), receipt_signer=signer)
    chair = ActorContext("hospital", "chair")
    case = engine.create_case(
        chair,
        title="Sensitive title",
        template=clinical_etd_template(),
        content={"question": "Sensitive clinical question"},
        idempotency_key="case",
    )
    conflict = engine.declare_conflict(
        chair,
        case["id"],
        scope="case",
        details={"employer": "Sensitive supplier"},
        idempotency_key="coi",
    )
    artifact = engine.create_artifact(
        chair,
        case["id"],
        kind="evidence_bundle",
        content={"private_notes": "Sensitive evidence payload"},
        idempotency_key="artifact",
    )
    engine.set_retention_policy(
        chair, case["id"], payload_days=0, coi_days=0, idempotency_key="retention"
    )
    receipt = engine.purge_due_payloads(
        chair,
        case["id"],
        as_of=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
        idempotency_key="purge",
    )
    assert {item["kind"] for item in receipt["items"]} >= {
        "case_title",
        "case_revision",
        "artifact_revision",
        "conflict",
    }
    assert receipt["signed_receipt"] is not None
    assert engine.get_case(chair, case["id"])["content"] == {}
    assert engine.store.get_revision("hospital", artifact["revision_id"])["content"] == {}
    coi = engine.store.one(
        "SELECT details_json, details_digest, purged_at FROM decision_conflicts WHERE namespace_id = ? AND id = ?",
        ("hospital", conflict["id"]),
    )
    assert coi["details_json"] == "{}" and coi["details_digest"] and coi["purged_at"]
    idempotency = engine.store.one(
        """SELECT response_json, purged_at FROM decision_idempotency
           WHERE namespace_id = ? AND principal_id = ? AND idempotency_key = ?""",
        ("hospital", "chair", "artifact"),
    )
    assert idempotency == {"response_json": "{}", "purged_at": receipt["created_at"]}
    with pytest.raises(DecisionStateError, match="response has been purged"):
        engine.create_artifact(
            chair,
            case["id"],
            kind="evidence_bundle",
            content={"private_notes": "Sensitive evidence payload"},
            idempotency_key="artifact",
        )
    bundle = engine.export_case(chair, case["id"])
    result = verify_bundle(bundle, signature_verifier=signer.verifier(), require_signatures=True)
    assert result["valid"] is True
    engine.close()


class _FakeKms:
    def __init__(self) -> None:
        self.last: dict[str, object] | None = None

    def sign(self, **kwargs):
        self.last = kwargs
        return {"KeyId": kwargs["KeyId"], "Signature": b"kms-signature"}

    def verify(self, **kwargs):
        self.last = kwargs
        return {"SignatureValid": kwargs["Signature"] == b"kms-signature"}


def test_aws_kms_adapter_uses_digest_mode_and_algorithm() -> None:
    client = _FakeKms()
    signer = AwsKmsSigner(client, key_id="arn:aws:kms:region:account:key/example")
    digest = "ab" * 32
    envelope = signer.sign_digest(digest)
    assert client.last["MessageType"] == "DIGEST"
    assert client.last["SigningAlgorithm"] == "RSASSA_PSS_SHA_256"
    assert AwsKmsVerifier(client).verify_digest(digest, envelope) is True
