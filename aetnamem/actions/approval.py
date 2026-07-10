"""Exact-plan approval tokens for guarded actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex


@dataclass(frozen=True)
class Approval:
    transaction_id: str
    plan_hash: str
    approver: str
    issued_at: str
    expires_at: str
    nonce: str
    signature: str
    format: str = "aetna-action-approval-v1"

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("signature")
        return value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Approval":
        return cls(**value)

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


class ApprovalAuthority:
    """HMAC authority held by the reviewer side of the deployment boundary.

    The key must not be exposed to the agent-facing MCP process. HMAC provides
    an authenticated local deployment primitive without adding dependencies;
    asymmetric/KMS-backed signers can implement the same issue/verify surface.
    """

    def __init__(self, secret: bytes | str) -> None:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if len(secret) < 32:
            raise ValueError("approval secret must contain at least 32 bytes")
        self._secret = secret

    def issue(
        self,
        *,
        transaction_id: str,
        plan_hash: str,
        approver: str,
        ttl_seconds: int = 900,
        now: datetime | None = None,
    ) -> Approval:
        if ttl_seconds <= 0:
            raise ValueError("approval ttl_seconds must be positive")
        issued = now or datetime.now(timezone.utc)
        unsigned = Approval(
            transaction_id=transaction_id,
            plan_hash=plan_hash,
            approver=approver,
            issued_at=issued.isoformat(),
            expires_at=(issued + timedelta(seconds=ttl_seconds)).isoformat(),
            nonce=secrets.token_hex(16),
            signature="",
        )
        signature = hmac.new(
            self._secret,
            canonical_json(unsigned.payload()).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return Approval(**{**unsigned.to_dict(), "signature": signature})

    def verify(
        self,
        approval: Approval,
        *,
        transaction_id: str,
        plan_hash: str,
        at: datetime | None = None,
    ) -> bool:
        if approval.transaction_id != transaction_id or approval.plan_hash != plan_hash:
            return False
        expected = hmac.new(
            self._secret,
            canonical_json(approval.payload()).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, approval.signature):
            return False
        moment = at or datetime.now(timezone.utc)
        try:
            issued = datetime.fromisoformat(approval.issued_at)
            expires = datetime.fromisoformat(approval.expires_at)
        except ValueError:
            return False
        return issued <= moment <= expires
