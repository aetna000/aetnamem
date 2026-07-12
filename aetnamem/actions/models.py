"""Stable data contracts for aetnamem Guarded Actions.

The model intentionally distinguishes evidence that *informed* an action from
authority that permits it. Untrusted content may be useful evidence, but it
must never become an authorization source merely because an agent cited it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import string
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex


class ActionMode(str, Enum):
    OFF = "off"
    OBSERVE = "observe"
    PREVIEW = "preview"
    ENFORCE = "enforce"


class EffectClass(str, Enum):
    READ_ONLY = "read_only"
    EXACT_TRANSACTIONAL = "exact_transactional"
    VERIFIED_COMPENSATABLE = "verified_compensatable"
    IRREVERSIBLE_STAGED = "irreversible_staged"
    OBSERVE_ONLY = "observe_only"
    UNKNOWN_BLOCKED = "unknown_blocked"


class TransactionState(str, Enum):
    DRAFT = "draft"
    STAGED = "staged"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ABORTED = "aborted"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    PARTIAL = "partial"
    UNCERTAIN = "uncertain"
    RECOVERY_REQUIRED = "recovery_required"


class OperationState(str, Enum):
    STAGED = "staged"
    EXECUTING = "executing"
    APPLIED = "applied"
    VERIFIED = "verified"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"


TERMINAL_TRANSACTION_STATES = frozenset(
    {
        TransactionState.COMMITTED,
        TransactionState.ABORTED,
        TransactionState.COMPENSATED,
        TransactionState.PARTIAL,
        TransactionState.UNCERTAIN,
        TransactionState.RECOVERY_REQUIRED,
    }
)


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    ref_id: str
    digest: str
    relation: str = "informed_by"
    trust_tier: str = "untrusted_content"
    attested: bool = False

    def __post_init__(self) -> None:
        if self.relation not in {"informed_by", "authorized_by"}:
            raise ValueError("evidence relation must be informed_by or authorized_by")
        if not self.kind or not self.ref_id or not self.digest:
            raise ValueError("evidence kind, ref_id, and digest are required")
        if len(self.digest) != 64 or any(
            character not in string.hexdigits for character in self.digest
        ):
            raise ValueError("evidence digest must be a 64-character SHA-256 hex value")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationProposal:
    key: str
    adapter: str
    operation: str
    arguments: dict[str, Any]
    evidence: tuple[EvidenceRef, ...] = ()
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.adapter or not self.operation:
            raise ValueError("operation key, adapter, and operation are required")


@dataclass(frozen=True)
class PreparedOperation:
    adapter: str
    operation: str
    arguments: dict[str, Any]
    preview: dict[str, Any]
    preconditions: dict[str, Any]
    effect_class: EffectClass
    sensitive_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["effect_class"] = self.effect_class.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PreparedOperation":
        return cls(
            adapter=str(value["adapter"]),
            operation=str(value["operation"]),
            arguments=dict(value.get("arguments") or {}),
            preview=dict(value.get("preview") or {}),
            preconditions=dict(value.get("preconditions") or {}),
            effect_class=EffectClass(value["effect_class"]),
            sensitive_fields=tuple(value.get("sensitive_fields") or ()),
        )


@dataclass(frozen=True)
class AdapterReceipt:
    provider_request_id: str | None
    result: dict[str, Any]
    observed_after: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AdapterReceipt":
        return cls(
            provider_request_id=value.get("provider_request_id"),
            result=dict(value.get("result") or {}),
            observed_after=dict(value.get("observed_after") or {}),
        )


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    observation: dict[str, Any]
    reason: str | None = None


@dataclass(frozen=True)
class WorldPatch:
    transaction_id: str
    subject_id: str
    mode: ActionMode
    state: TransactionState
    plan_version: int
    plan_hash: str
    operations: tuple[dict[str, Any], ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        value["state"] = self.state.value
        value["operations"] = list(self.operations)
        return value


@dataclass(frozen=True)
class ActionReceipt:
    transaction_id: str
    subject_id: str
    plan_hash: str
    terminal_state: str
    operation_receipts: tuple[dict[str, Any], ...]
    audit_event_id: str
    audit_event_hash: str
    created_at: str
    format: str = "aetna-action-receipt-v1"
    receipt_sha256: str = field(default="")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def signed(self) -> "ActionReceipt":
        body = self.to_dict()
        body.pop("receipt_sha256", None)
        return ActionReceipt(
            **{key: value for key, value in body.items() if key != "operation_receipts"},
            operation_receipts=tuple(body["operation_receipts"]),
            receipt_sha256=sha256_hex(canonical_json(body)),
        )


def digest_json(value: Any) -> str:
    return sha256_hex(canonical_json(value))
