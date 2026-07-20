"""Provider-neutral asymmetric signatures for decision identities and receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import secrets
from typing import Any, Protocol

from aetnamem.core.canonical import canonical_json, sha256_hex


@dataclass(frozen=True)
class SignatureEnvelope:
    key_id: str
    algorithm: str
    signature: str
    signed_digest: str
    issued_at: str
    format: str = "aetnamem-signature-v1"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SignatureEnvelope":
        return cls(
            key_id=str(value["key_id"]),
            algorithm=str(value["algorithm"]),
            signature=str(value["signature"]),
            signed_digest=str(value["signed_digest"]),
            issued_at=str(value["issued_at"]),
            format=str(value.get("format", "aetnamem-signature-v1")),
        )


class DecisionSigner(Protocol):
    key_id: str
    algorithm: str

    def sign_digest(self, digest: str) -> SignatureEnvelope: ...


class DecisionSignatureVerifier(Protocol):
    def verify_digest(self, digest: str, signature: SignatureEnvelope) -> bool: ...


class Ed25519Signer:
    """Local asymmetric signer suitable for tests, on-prem HSM bridges, and key files."""

    algorithm = "Ed25519"

    def __init__(self, private_key: Any, *, key_id: str) -> None:
        self._private_key = private_key
        self.key_id = key_id

    @classmethod
    def generate(cls, *, key_id: str = "local-ed25519") -> "Ed25519Signer":
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError as exc:  # pragma: no cover - dependency-path guard
            raise RuntimeError("Ed25519 support requires a complete 'pip install aetnamem'") from exc
        return cls(Ed25519PrivateKey.generate(), key_id=key_id)

    @classmethod
    def from_private_pem(
        cls, pem: bytes, *, key_id: str, password: bytes | None = None
    ) -> "Ed25519Signer":
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PEM signing requires a complete 'pip install aetnamem'") from exc
        key = load_pem_private_key(pem, password=password)
        return cls(key, key_id=key_id)

    def sign_digest(self, digest: str) -> SignatureEnvelope:
        raw = _digest_bytes(digest)
        return SignatureEnvelope(
            key_id=self.key_id,
            algorithm=self.algorithm,
            signature=base64.b64encode(self._private_key.sign(raw)).decode("ascii"),
            signed_digest=digest,
            issued_at=_now(),
        )

    def verifier(self) -> "Ed25519Verifier":
        return Ed25519Verifier({self.key_id: self._private_key.public_key()})

    def public_key_pem(self) -> bytes:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        return self._private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


class Ed25519Verifier:
    def __init__(self, public_keys: dict[str, Any]) -> None:
        self._public_keys = dict(public_keys)

    @classmethod
    def from_public_pems(cls, public_keys: dict[str, bytes]) -> "Ed25519Verifier":
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PEM verification requires a complete 'pip install aetnamem'") from exc
        return cls({key_id: load_pem_public_key(pem) for key_id, pem in public_keys.items()})

    def verify_digest(self, digest: str, signature: SignatureEnvelope) -> bool:
        if signature.algorithm != "Ed25519" or signature.signed_digest != digest:
            return False
        key = self._public_keys.get(signature.key_id)
        if key is None:
            return False
        try:
            key.verify(base64.b64decode(signature.signature, validate=True), _digest_bytes(digest))
            return True
        except Exception:
            return False


class AwsKmsSigner:
    """AWS KMS asymmetric signer using an injected boto3-compatible KMS client."""

    def __init__(
        self,
        kms_client: Any,
        *,
        key_id: str,
        signing_algorithm: str = "RSASSA_PSS_SHA_256",
    ) -> None:
        supported = {"RSASSA_PSS_SHA_256", "RSASSA_PKCS1_V1_5_SHA_256", "ECDSA_SHA_256"}
        if signing_algorithm not in supported:
            raise ValueError("KMS signing algorithm must use SHA-256 for decision digests")
        self._client = kms_client
        self.key_id = key_id
        self.algorithm = signing_algorithm

    def sign_digest(self, digest: str) -> SignatureEnvelope:
        response = self._client.sign(
            KeyId=self.key_id,
            Message=_digest_bytes(digest),
            MessageType="DIGEST",
            SigningAlgorithm=self.algorithm,
        )
        return SignatureEnvelope(
            key_id=str(response.get("KeyId", self.key_id)),
            algorithm=self.algorithm,
            signature=base64.b64encode(bytes(response["Signature"])).decode("ascii"),
            signed_digest=digest,
            issued_at=_now(),
        )


class AwsKmsVerifier:
    """Verification through AWS KMS, useful when public-key distribution is host-managed."""

    def __init__(self, kms_client: Any) -> None:
        self._client = kms_client

    def verify_digest(self, digest: str, signature: SignatureEnvelope) -> bool:
        if signature.signed_digest != digest:
            return False
        try:
            response = self._client.verify(
                KeyId=signature.key_id,
                Message=_digest_bytes(digest),
                MessageType="DIGEST",
                Signature=base64.b64decode(signature.signature, validate=True),
                SigningAlgorithm=signature.algorithm,
            )
            return bool(response.get("SignatureValid"))
        except Exception:
            return False


@dataclass(frozen=True)
class PrincipalAttestation:
    namespace_id: str
    principal_id: str
    assurance: str
    issued_at: str
    expires_at: str
    nonce: str
    signature: SignatureEnvelope
    format: str = "aetnamem-principal-attestation-v1"

    def payload(self) -> dict[str, str]:
        return {
            "format": self.format,
            "namespace_id": self.namespace_id,
            "principal_id": self.principal_id,
            "assurance": self.assurance,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.payload()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "signature": self.signature.to_dict()}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PrincipalAttestation":
        return cls(
            namespace_id=str(value["namespace_id"]),
            principal_id=str(value["principal_id"]),
            assurance=str(value["assurance"]),
            issued_at=str(value["issued_at"]),
            expires_at=str(value["expires_at"]),
            nonce=str(value["nonce"]),
            signature=SignatureEnvelope.from_dict(value["signature"]),
            format=str(value.get("format", "aetnamem-principal-attestation-v1")),
        )


def issue_principal_attestation(
    signer: DecisionSigner,
    *,
    namespace_id: str,
    principal_id: str,
    assurance: str = "asymmetric_host_attested",
    ttl_seconds: int = 900,
    now: datetime | None = None,
) -> PrincipalAttestation:
    if ttl_seconds <= 0:
        raise ValueError("attestation ttl_seconds must be positive")
    issued = now or datetime.now(timezone.utc)
    payload = {
        "format": "aetnamem-principal-attestation-v1",
        "namespace_id": namespace_id,
        "principal_id": principal_id,
        "assurance": assurance,
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(seconds=ttl_seconds)).isoformat(),
        "nonce": secrets.token_hex(16),
    }
    digest = sha256_hex(canonical_json(payload))
    return PrincipalAttestation(**payload, signature=signer.sign_digest(digest))


def verify_principal_attestation(
    attestation: PrincipalAttestation,
    verifier: DecisionSignatureVerifier,
    *,
    namespace_id: str,
    principal_id: str,
    assurance: str,
    at: datetime | None = None,
) -> bool:
    if (
        attestation.namespace_id != namespace_id
        or attestation.principal_id != principal_id
        or attestation.assurance != assurance
    ):
        return False
    try:
        issued = datetime.fromisoformat(attestation.issued_at)
        expires = datetime.fromisoformat(attestation.expires_at)
    except ValueError:
        return False
    if issued.tzinfo is None or expires.tzinfo is None:
        return False
    moment = at or datetime.now(timezone.utc)
    return issued <= moment <= expires and verifier.verify_digest(attestation.digest, attestation.signature)


def receipt_digest(kind: str, object_id: str, digest: str) -> str:
    return sha256_hex(
        canonical_json(
            {
                "format": "aetnamem-decision-receipt-v1",
                "kind": kind,
                "object_id": object_id,
                "object_digest": digest,
            }
        )
    )


def _digest_bytes(digest: str) -> bytes:
    if len(digest) != 64:
        raise ValueError("signed digest must be a SHA-256 hexadecimal digest")
    try:
        return bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError("signed digest must be hexadecimal") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
