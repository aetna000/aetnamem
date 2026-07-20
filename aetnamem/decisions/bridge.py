"""Explicit institutional authorization to Guarded Actions bridge."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aetnamem.actions import EvidenceRef, PreparedOperation, ResolvedAuthority
from aetnamem.decisions.engine import DecisionEngine
from aetnamem.decisions.models import DecisionNotFound, DecisionPolicyViolation


class DecisionAuthorityResolver:
    """Resolve one namespace's authorization grants at stage and commit."""

    def __init__(self, engine: DecisionEngine, namespace_id: str) -> None:
        self.engine = engine
        self.namespace_id = namespace_id

    def supports(self, ref: EvidenceRef) -> bool:
        return ref.kind == "decision_authorization"

    def validate(
        self,
        ref: EvidenceRef,
        *,
        subject_id: str,
        prepared_operation: PreparedOperation,
        phase: str,
    ) -> ResolvedAuthority:
        authorization = self.engine.store.get_authorization(self.namespace_id, ref.ref_id)
        if authorization is None:
            raise DecisionNotFound(ref.ref_id)
        if ref.digest != authorization["digest"]:
            raise DecisionPolicyViolation("authorization digest mismatch")
        if authorization["status"] != "active":
            raise DecisionPolicyViolation("authorization is not active")
        expires_at = authorization.get("expires_at")
        if expires_at and _parse_time(expires_at) <= datetime.now(timezone.utc):
            raise DecisionPolicyViolation("authorization has expired")
        plan = self.engine.store.get_revision(self.namespace_id, authorization["plan_revision_id"])
        if plan is None or plan["digest"] != authorization["plan_digest"]:
            raise DecisionPolicyViolation("authorized implementation plan is missing or changed")
        scope = authorization["scope"]
        _require_scope(scope, "subject_ids", subject_id)
        _require_scope(scope, "adapters", prepared_operation.adapter)
        _require_scope(scope, "operations", prepared_operation.operation)
        resources = scope.get("resources")
        if resources is not None:
            resource = prepared_operation.arguments.get("resource") or prepared_operation.arguments.get("path")
            if resource is None or not _allows(resources, str(resource)):
                raise DecisionPolicyViolation("operation resource is outside authorization scope")
        return ResolvedAuthority(
            ref_id=authorization["id"],
            digest=authorization["digest"],
            authority_kind="decision_authorization",
        )

    def evidence_refs(self, authorization_id: str) -> tuple[EvidenceRef, EvidenceRef]:
        authorization = self.engine.store.get_authorization(self.namespace_id, authorization_id)
        if authorization is None:
            raise DecisionNotFound(authorization_id)
        adoption = self.engine.store.get_adoption(self.namespace_id, authorization["adoption_id"])
        if adoption is None:
            raise DecisionNotFound(authorization["adoption_id"])
        return (
            EvidenceRef(
                kind="decision_adoption",
                ref_id=adoption["id"],
                digest=adoption["digest"],
                relation="informed_by",
                trust_tier="decision_record",
                attested=True,
            ),
            EvidenceRef(
                kind="decision_authorization",
                ref_id=authorization["id"],
                digest=authorization["digest"],
                relation="authorized_by",
                trust_tier="decision_authorization",
                attested=True,
            ),
        )

    def link_action(
        self, authorization_id: str, transaction_id: str, receipt_id: str | None = None
    ) -> None:
        authorization = self.engine.store.get_authorization(self.namespace_id, authorization_id)
        if authorization is None:
            raise DecisionNotFound(authorization_id)
        from aetnamem.store.sqlite import utc_now

        with self.engine.store.transaction():
            self.engine.store.execute(
                """
                INSERT INTO decision_action_links(
                  namespace_id, authorization_id, transaction_id, receipt_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(namespace_id, authorization_id, transaction_id)
                DO UPDATE SET receipt_id = excluded.receipt_id
                """,
                (self.namespace_id, authorization_id, transaction_id, receipt_id, utc_now()),
            )


def _require_scope(scope: dict[str, Any], key: str, value: str) -> None:
    allowed = scope.get(key)
    if not isinstance(allowed, list) or not _allows(allowed, value):
        raise DecisionPolicyViolation(f"{key} does not authorize {value}")


def _allows(values: list[Any], value: str) -> bool:
    return "*" in values or value in {str(item) for item in values}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DecisionPolicyViolation("authorization expiry lacks timezone")
    return parsed.astimezone(timezone.utc)
