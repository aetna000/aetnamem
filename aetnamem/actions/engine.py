"""Causal transaction coordinator for aetnamem Guarded Actions."""

from __future__ import annotations

from datetime import datetime, timezone
import traceback
from typing import Any, Iterable
import uuid

from aetnamem.actions.adapters import ActionAdapter, ActionContext
from aetnamem.actions.approval import Approval, ApprovalAuthority
from aetnamem.actions.authority import AuthorityResolver
from aetnamem.actions.models import (
    ActionMode,
    ActionReceipt,
    AdapterReceipt,
    EvidenceRef,
    OperationProposal,
    OperationState,
    PreparedOperation,
    TransactionState,
    WorldPatch,
    digest_json,
)
from aetnamem.actions.policy import GuardPolicy
from aetnamem.actions.store import ActionStore
from aetnamem.memory import Memory
from aetnamem.store.sqlite import utc_now


class ActionStateError(RuntimeError):
    pass


class AdapterDriftError(RuntimeError):
    pass


class ActionEngine:
    """Durable, provider-neutral guarded-action coordinator.

    Database transactions bracket ledger transitions only. They are committed
    before any adapter call, so a slow or failed external system never holds a
    SQLite lock. A crash/exception after an execution intent is durable is
    represented as ``uncertain`` rather than being blindly retried.
    """

    def __init__(
        self,
        memory: Memory,
        *,
        adapters: Iterable[ActionAdapter] = (),
        mode: ActionMode | str = ActionMode.ENFORCE,
        approval_authority: ApprovalAuthority | None = None,
        policy: GuardPolicy | None = None,
        authority_resolver: AuthorityResolver | None = None,
    ) -> None:
        self.memory = memory
        self.store = ActionStore(memory.store)
        self.mode = ActionMode(mode)
        self.approval_authority = approval_authority
        self.policy = policy or GuardPolicy()
        self.authority_resolver = authority_resolver
        self.adapters = {adapter.name: adapter for adapter in adapters}

    def propose(
        self,
        subject_id: str,
        operations: list[OperationProposal],
        *,
        actor_id: str,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        mode: ActionMode | str | None = None,
    ) -> WorldPatch:
        selected_mode = ActionMode(mode or self.mode)
        if selected_mode is ActionMode.OFF:
            raise ValueError("guarded actions are disabled in off mode")
        if not operations:
            raise ValueError("an action proposal requires at least one operation")
        keys = [item.key for item in operations]
        if len(keys) != len(set(keys)):
            raise ValueError("operation keys must be unique within a proposal")
        _validate_dependency_graph(operations)
        operations = _topological_order(operations)

        transaction_id = _new_id("act")
        operation_ids = {proposal.key: _new_id("op") for proposal in operations}
        prepared_rows: list[dict[str, Any]] = []
        dependencies: list[tuple[str, str]] = []
        evidence_rows: list[dict[str, Any]] = []
        payloads: list[dict[str, Any]] = []
        plan_operations: list[dict[str, Any]] = []

        for ordinal, proposal in enumerate(operations):
            adapter = self._adapter(proposal.adapter)
            operation_id = operation_ids[proposal.key]
            context = ActionContext(
                transaction_id=transaction_id,
                operation_id=operation_id,
                subject_id=subject_id,
                actor_id=actor_id,
            )
            prepared = adapter.prepare(proposal.operation, proposal.arguments, context)
            if prepared.adapter != proposal.adapter or prepared.operation != proposal.operation:
                raise ValueError("adapter returned a mismatched prepared operation")
            self.policy.validate_operation(prepared, proposal.evidence, selected_mode)
            self._resolve_authorities(
                proposal.evidence,
                subject_id=subject_id,
                prepared=prepared,
                phase="stage",
            )
            manifest_digest = digest_json(adapter.manifest())
            prepared_payload = prepared.to_dict()
            arguments_digest = digest_json(prepared.arguments)
            preview_digest = digest_json(prepared.preview)
            precondition_digest = digest_json(prepared.preconditions)
            idempotency_key = digest_json(
                {
                    "transaction_id": transaction_id,
                    "operation_id": operation_id,
                    "adapter": prepared.adapter,
                    "operation": prepared.operation,
                    "arguments_digest": arguments_digest,
                }
            )
            dependency_ids = sorted(operation_ids[key] for key in proposal.depends_on)
            evidence_for_plan: list[dict[str, Any]] = []
            for evidence in proposal.evidence:
                evidence_id = _new_id("evi")
                item = {
                    "id": evidence_id,
                    "operation_id": operation_id,
                    **evidence.to_dict(),
                }
                evidence_rows.append(item)
                evidence_for_plan.append(
                    {
                        "kind": evidence.kind,
                        "ref_id": evidence.ref_id,
                        "digest": evidence.digest,
                        "relation": evidence.relation,
                        "trust_tier": evidence.trust_tier,
                        "attested": evidence.attested,
                    }
                )
            evidence_for_plan.sort(
                key=lambda item: (
                    item["relation"], item["kind"], item["ref_id"], item["digest"]
                )
            )
            for dependency_id in dependency_ids:
                dependencies.append((operation_id, dependency_id))

            prepared_rows.append(
                {
                    "id": operation_id,
                    "key": proposal.key,
                    "ordinal": ordinal,
                    "adapter": prepared.adapter,
                    "operation": prepared.operation,
                    "effect_class": prepared.effect_class.value,
                    "state": OperationState.STAGED.value,
                    "idempotency_key": idempotency_key,
                    "arguments_digest": arguments_digest,
                    "preview_digest": preview_digest,
                    "precondition_digest": precondition_digest,
                    "manifest_digest": manifest_digest,
                }
            )
            payloads.append(
                {
                    "transaction_id": transaction_id,
                    "operation_id": operation_id,
                    "kind": "prepared",
                    "payload": prepared_payload,
                    "digest": digest_json(prepared_payload),
                }
            )
            plan_operations.append(
                {
                    "id": operation_id,
                    "key": proposal.key,
                    "ordinal": ordinal,
                    "adapter": prepared.adapter,
                    "operation": prepared.operation,
                    "effect_class": prepared.effect_class.value,
                    "arguments_digest": arguments_digest,
                    "preview_digest": preview_digest,
                    "precondition_digest": precondition_digest,
                    "manifest_digest": manifest_digest,
                    "depends_on": dependency_ids,
                    "evidence": evidence_for_plan,
                }
            )

        plan_hash = digest_json(
            {
                "format": "aetna-world-patch-v1",
                "transaction_id": transaction_id,
                "subject_id": subject_id,
                "actor_id": actor_id,
                "mode": selected_mode.value,
                "plan_version": 1,
                "policy_hash": self.policy.digest,
                "operations": plan_operations,
            }
        )
        state = (
            TransactionState.AWAITING_APPROVAL
            if selected_mode is ActionMode.ENFORCE
            else TransactionState.STAGED
        )
        created_at = utc_now()
        transaction = {
            "id": transaction_id,
            "subject_id": subject_id,
            "session_id": session_id,
            "turn_id": _turn_id(turn_id),
            "actor_id": actor_id,
            "mode": selected_mode.value,
            "state": state.value,
            "plan_version": 1,
            "plan_hash": plan_hash,
            "policy_hash": self.policy.digest,
            "created_at": created_at,
        }
        with self.memory.store.transaction():
            self.store.create_plan(
                transaction, prepared_rows, dependencies, evidence_rows, payloads
            )
            self.memory.store.append_audit_event(
                subject_id=subject_id,
                event_type="action.proposed",
                actor=actor_id,
                session_id=session_id,
                turn_id=_turn_id(turn_id),
                payload={
                    "transaction_id": transaction_id,
                    "format": "aetna-world-patch-v1",
                    "mode": selected_mode.value,
                    "state": state.value,
                    "plan_hash": plan_hash,
                    "policy_hash": self.policy.digest,
                    "operations": [
                        {
                            key: item[key]
                            for key in (
                                "id", "key", "ordinal", "adapter", "operation",
                                "effect_class", "arguments_digest", "preview_digest",
                                "precondition_digest", "manifest_digest", "depends_on",
                            )
                        }
                        for item in plan_operations
                    ],
                    "evidence": [
                        {
                            key: item[key]
                            for key in (
                                "id", "operation_id", "kind", "ref_id", "digest",
                                "relation", "trust_tier", "attested",
                            )
                        }
                        for item in evidence_rows
                    ],
                },
            )
        return WorldPatch(
            transaction_id=transaction_id,
            subject_id=subject_id,
            mode=selected_mode,
            state=state,
            plan_version=1,
            plan_hash=plan_hash,
            operations=tuple(plan_operations),
            created_at=created_at,
        )

    def get(self, transaction_id: str, *, include_payloads: bool = False) -> dict[str, Any]:
        transaction = self.store.get_transaction(
            transaction_id, include_payloads=include_payloads
        )
        if transaction is None:
            raise KeyError(transaction_id)
        return transaction

    def list(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_transactions(subject_id)

    def approve(self, approval: Approval) -> dict[str, Any]:
        if self.approval_authority is None:
            raise RuntimeError("an ApprovalAuthority is required to approve actions")
        transaction = self.get(approval.transaction_id)
        if transaction["state"] != TransactionState.AWAITING_APPROVAL.value:
            raise ActionStateError(
                f"transaction is {transaction['state']}, not awaiting_approval"
            )
        if not self.approval_authority.verify(
            approval,
            transaction_id=transaction["id"],
            plan_hash=transaction["plan_hash"],
        ):
            raise ValueError("approval signature, scope, plan hash, or expiry is invalid")
        approval_value = {**approval.to_dict(), "digest": approval.digest}
        with self.memory.store.transaction():
            approval_id = self.store.record_approval(transaction["id"], approval_value)
            self.store.set_transaction_state(
                transaction["id"],
                TransactionState.APPROVED.value,
                expected=(TransactionState.AWAITING_APPROVAL.value,),
            )
            self.memory.store.append_audit_event(
                subject_id=transaction["subject_id"],
                event_type="action.approved",
                actor=approval.approver,
                session_id=transaction["session_id"],
                turn_id=transaction["turn_id"],
                payload={
                    "transaction_id": transaction["id"],
                    "approval_id": approval_id,
                    "plan_hash": transaction["plan_hash"],
                    "approval_digest": approval.digest,
                    "approver": approval.approver,
                    "expires_at": approval.expires_at,
                },
            )
        return self.get(transaction["id"])

    def commit(self, transaction_id: str) -> dict[str, Any]:
        transaction = self.get(transaction_id, include_payloads=True)
        if transaction["mode"] != ActionMode.ENFORCE.value:
            raise ActionStateError("observe and preview plans cannot execute")
        if transaction["state"] != TransactionState.APPROVED.value:
            raise ActionStateError(f"transaction is {transaction['state']}, not approved")
        # Recompute the persisted WorldPatch and approval digests before any
        # effect. This detects operational-table mutation even when an attacker
        # leaves the transaction's claimed plan_hash untouched.
        from aetnamem.actions.verifier import verify_action

        integrity = verify_action(
            self.memory.store,
            transaction_id,
            approval_authority=self.approval_authority,
        )
        if not integrity["valid"]:
            raise ActionStateError(
                "action integrity verification failed: "
                + "; ".join(integrity["failures"])
            )
        self._verify_recorded_approval(transaction)
        self._verify_resolved_authorities(transaction)
        self._verify_manifests(transaction)

        # Revalidate the complete approved patch before the first effect.
        for operation in transaction["operations"]:
            adapter, prepared = self._prepared(operation)
            result = adapter.revalidate(prepared)
            if not result.verified:
                return self._abort_for_precondition(transaction, operation, result.reason)

        with self.memory.store.transaction():
            self.store.set_transaction_state(
                transaction_id,
                TransactionState.COMMITTING.value,
                expected=(TransactionState.APPROVED.value,),
            )
            self._event(transaction, "action.committing", {"plan_hash": transaction["plan_hash"]})

        applied: list[dict[str, Any]] = []
        for operation in transaction["operations"]:
            adapter, prepared = self._prepared(operation)
            current = adapter.revalidate(prepared)
            if not current.verified:
                final_state = self._compensate_applied(transaction, applied)
                self.store.set_transaction_state(
                    transaction_id,
                    final_state.value,
                    error_code="precondition_changed",
                    error_digest=digest_json(current.observation),
                )
                self._event(
                    transaction,
                    "action.precondition_failed",
                    {
                        "operation_id": operation["id"],
                        "reason_digest": digest_json(current.reason or "changed"),
                        "observation_digest": digest_json(current.observation),
                        "terminal_state": final_state.value,
                    },
                )
                return self._finish(transaction_id, final_state)

            attempt_id, attempt_number = self.store.start_attempt(
                operation["id"], "execute", operation["idempotency_key"]
            )
            with self.memory.store.transaction():
                self.store.set_operation_state(
                    operation["id"], OperationState.EXECUTING.value
                )
                self._event(
                    transaction,
                    "action.effect_executing",
                    {
                        "operation_id": operation["id"],
                        "attempt": attempt_number,
                        "idempotency_key": operation["idempotency_key"],
                    },
                )

            # No database transaction is open across this external boundary.
            try:
                receipt = adapter.execute(
                    prepared, idempotency_key=operation["idempotency_key"]
                )
            except BaseException as exc:
                error_digest = _error_digest(exc)
                self.store.finish_attempt(
                    attempt_id,
                    "uncertain",
                    error_code=type(exc).__name__,
                    error_digest=error_digest,
                )
                with self.memory.store.transaction():
                    self.store.set_operation_state(
                        operation["id"], OperationState.UNCERTAIN.value
                    )
                    self._event(
                        transaction,
                        "action.effect_uncertain",
                        {
                            "operation_id": operation["id"],
                            "attempt": attempt_number,
                            "error_type": type(exc).__name__,
                            "error_digest": error_digest,
                        },
                    )
                self._compensate_applied(transaction, applied)
                with self.memory.store.transaction():
                    self.store.set_transaction_state(
                        transaction_id,
                        TransactionState.UNCERTAIN.value,
                        error_code="execution_raised",
                        error_digest=error_digest,
                    )
                    self._event(
                        transaction,
                        "action.transaction_uncertain",
                        {
                            "operation_id": operation["id"],
                            "error_digest": error_digest,
                        },
                    )
                return self._finish(transaction_id, TransactionState.UNCERTAIN)

            receipt_value = receipt.to_dict()
            receipt_digest = digest_json(receipt_value)
            verification = adapter.verify(prepared, receipt)
            with self.memory.store.transaction():
                self.store.finish_attempt(
                    attempt_id,
                    "verified" if verification.verified else "uncertain",
                    provider_request_id=receipt.provider_request_id,
                )
                self.store.put_payload(
                    transaction_id=transaction_id,
                    operation_id=operation["id"],
                    kind="execution_receipt",
                    payload=receipt_value,
                    digest=receipt_digest,
                )
                self.store.set_operation_state(
                    operation["id"],
                    OperationState.VERIFIED.value
                    if verification.verified
                    else OperationState.UNCERTAIN.value,
                    result_digest=receipt_digest,
                )
                self._event(
                    transaction,
                    "action.effect_verified"
                    if verification.verified
                    else "action.effect_uncertain",
                    {
                        "operation_id": operation["id"],
                        "attempt": attempt_number,
                        "result_digest": receipt_digest,
                        "observation_digest": digest_json(verification.observation),
                        "verified": verification.verified,
                    },
                )
            if not verification.verified:
                self._compensate_applied(transaction, applied)
                with self.memory.store.transaction():
                    self.store.set_transaction_state(
                        transaction_id,
                        TransactionState.UNCERTAIN.value,
                        error_code="postcondition_unverified",
                        error_digest=digest_json(verification.observation),
                    )
                    self._event(
                        transaction,
                        "action.transaction_uncertain",
                        {
                            "operation_id": operation["id"],
                            "observation_digest": digest_json(
                                verification.observation
                            ),
                        },
                    )
                return self._finish(transaction_id, TransactionState.UNCERTAIN)
            operation["payloads"]["execution_receipt"] = receipt_value
            applied.append(operation)

        with self.memory.store.transaction():
            self.store.set_transaction_state(
                transaction_id,
                TransactionState.COMMITTED.value,
                expected=(TransactionState.COMMITTING.value,),
            )
            self._event(
                transaction,
                "action.committed",
                {
                    "plan_hash": transaction["plan_hash"],
                    "operation_ids": [item["id"] for item in applied],
                },
            )
        return self._finish(transaction_id, TransactionState.COMMITTED)

    def abort(self, transaction_id: str, *, actor: str = "user") -> dict[str, Any]:
        transaction = self.get(transaction_id)
        allowed = {
            TransactionState.STAGED.value,
            TransactionState.AWAITING_APPROVAL.value,
            TransactionState.APPROVED.value,
        }
        if transaction["state"] not in allowed:
            raise ActionStateError(f"transaction {transaction_id} cannot abort from {transaction['state']}")
        with self.memory.store.transaction():
            self.store.set_transaction_state(
                transaction_id, TransactionState.ABORTED.value, expected=allowed
            )
            self._event(
                transaction,
                "action.aborted",
                {"plan_hash": transaction["plan_hash"], "aborted_by": actor},
                actor=actor,
            )
        return self._finish(transaction_id, TransactionState.ABORTED)

    def recover(
        self, transaction_id: str, *, actor: str = "operator"
    ) -> dict[str, Any]:
        """Fence an interrupted execution for provider-specific recovery.

        Generic code cannot decide whether an external call completed before a
        process died. Any in-flight operation is therefore marked uncertain
        and the transaction becomes ``recovery_required``. A future provider
        can resolve it using an idempotency lookup or authoritative state read;
        aetnamem never performs a blind retry here.
        """
        transaction = self.get(transaction_id)
        if transaction["state"] not in {
            TransactionState.COMMITTING.value,
            TransactionState.COMPENSATING.value,
        }:
            raise ActionStateError(
                f"transaction {transaction_id} does not require interrupted-run recovery"
            )
        uncertain_ids: list[str] = []
        with self.memory.store.transaction():
            for operation in transaction["operations"]:
                if operation["state"] in {
                    OperationState.EXECUTING.value,
                    OperationState.COMPENSATING.value,
                }:
                    self.store.set_operation_state(
                        operation["id"], OperationState.UNCERTAIN.value
                    )
                    uncertain_ids.append(operation["id"])
            self.store.set_transaction_state(
                transaction_id,
                TransactionState.RECOVERY_REQUIRED.value,
                error_code="interrupted_external_boundary",
                error_digest=digest_json(uncertain_ids),
            )
            self._event(
                transaction,
                "action.recovery_required",
                {
                    "uncertain_operation_ids": uncertain_ids,
                    "reason": "interrupted_external_boundary",
                },
                actor=actor,
            )
        return self._finish(transaction_id, TransactionState.RECOVERY_REQUIRED)

    def purge_payloads(self, transaction_id: str, *, actor: str = "user") -> dict[str, Any]:
        transaction = self.get(transaction_id)
        with self.memory.store.transaction():
            count = self.store.purge_payloads(transaction_id)
            event_id = self._event(
                transaction,
                "action.payloads_purged",
                {"purged_count": count, "plan_hash": transaction["plan_hash"]},
                actor=actor,
            )
        return {"transaction_id": transaction_id, "purged_count": count, "audit_event_id": event_id}

    def _verify_recorded_approval(self, transaction: dict[str, Any]) -> None:
        if self.approval_authority is None:
            raise RuntimeError("an ApprovalAuthority is required to commit actions")
        approvals = transaction["approvals"]
        if not approvals:
            raise ActionStateError("transaction has no recorded approval")
        row = approvals[-1]
        approval = Approval(
            transaction_id=transaction["id"],
            plan_hash=row["plan_hash"],
            approver=row["approver_principal"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            nonce=row["nonce"],
            signature=row["signature"],
        )
        if not self.approval_authority.verify(
            approval,
            transaction_id=transaction["id"],
            plan_hash=transaction["plan_hash"],
        ):
            raise ValueError("recorded approval is invalid or expired")

    def _resolve_authorities(
        self,
        evidence: Iterable[EvidenceRef],
        *,
        subject_id: str,
        prepared: PreparedOperation,
        phase: str,
    ) -> None:
        if self.authority_resolver is None:
            return
        for ref in evidence:
            if ref.relation != "authorized_by" or not self.authority_resolver.supports(ref):
                continue
            resolved = self.authority_resolver.validate(
                ref,
                subject_id=subject_id,
                prepared_operation=prepared,
                phase=phase,
            )
            if not resolved.valid or resolved.digest != ref.digest or resolved.ref_id != ref.ref_id:
                raise ActionStateError("resolved action authority does not match its evidence reference")

    def _verify_resolved_authorities(self, transaction: dict[str, Any]) -> None:
        if self.authority_resolver is None:
            return
        for operation in transaction["operations"]:
            _, prepared = self._prepared(operation)
            refs = tuple(
                EvidenceRef(
                    kind=item["evidence_kind"],
                    ref_id=item["ref_id"],
                    digest=item["digest"],
                    relation=item["relation"],
                    trust_tier=item["trust_tier"],
                    attested=bool(item["attested"]),
                )
                for item in operation["evidence"]
            )
            self._resolve_authorities(
                refs,
                subject_id=transaction["subject_id"],
                prepared=prepared,
                phase="commit",
            )

    def _verify_manifests(self, transaction: dict[str, Any]) -> None:
        for operation in transaction["operations"]:
            current = digest_json(self._adapter(operation["adapter"]).manifest())
            if current != operation["manifest_digest"]:
                raise AdapterDriftError(
                    f"adapter manifest changed after approval: {operation['adapter']}"
                )

    def _prepared(self, operation: dict[str, Any]) -> tuple[ActionAdapter, PreparedOperation]:
        payload = operation.get("payloads", {}).get("prepared")
        if payload is None:
            raise RuntimeError(f"prepared payload was purged for {operation['id']}")
        return self._adapter(operation["adapter"]), PreparedOperation.from_dict(payload)

    def _adapter(self, name: str) -> ActionAdapter:
        try:
            return self.adapters[name]
        except KeyError as exc:
            raise KeyError(f"no guarded-action adapter registered as {name!r}") from exc

    def _abort_for_precondition(
        self,
        transaction: dict[str, Any],
        operation: dict[str, Any],
        reason: str | None,
    ) -> dict[str, Any]:
        with self.memory.store.transaction():
            self.store.set_transaction_state(
                transaction["id"],
                TransactionState.ABORTED.value,
                expected=(TransactionState.APPROVED.value,),
                error_code="precondition_changed",
                error_digest=digest_json(reason or "changed"),
            )
            self._event(
                transaction,
                "action.precondition_failed",
                {
                    "operation_id": operation["id"],
                    "reason_digest": digest_json(reason or "changed"),
                    "terminal_state": TransactionState.ABORTED.value,
                },
            )
        return self._finish(transaction["id"], TransactionState.ABORTED)

    def _compensate_applied(
        self, transaction: dict[str, Any], applied: list[dict[str, Any]]
    ) -> TransactionState:
        if not applied:
            return TransactionState.COMPENSATED
        failures = False
        with self.memory.store.transaction():
            self.store.set_transaction_state(
                transaction["id"], TransactionState.COMPENSATING.value
            )
            self._event(
                transaction,
                "action.compensating",
                {"operation_ids": [item["id"] for item in reversed(applied)]},
            )
        for operation in reversed(applied):
            adapter, prepared = self._prepared(operation)
            receipt = AdapterReceipt.from_dict(operation["payloads"]["execution_receipt"])
            compensation_key = operation["idempotency_key"] + ":compensate"
            attempt_id, attempt_number = self.store.start_attempt(
                operation["id"], "compensate", compensation_key
            )
            self.store.set_operation_state(
                operation["id"], OperationState.COMPENSATING.value
            )
            try:
                compensation = adapter.compensate(
                    prepared, receipt, idempotency_key=compensation_key
                )
                verification = adapter.verify_compensation(prepared, compensation)
                if not verification.verified:
                    raise RuntimeError(verification.reason or "compensation unverified")
            except BaseException as exc:
                failures = True
                error_digest = _error_digest(exc)
                self.store.finish_attempt(
                    attempt_id,
                    "failed",
                    error_code=type(exc).__name__,
                    error_digest=error_digest,
                )
                self.store.set_operation_state(
                    operation["id"], OperationState.FAILED.value
                )
                self._event(
                    transaction,
                    "action.compensation_failed",
                    {
                        "operation_id": operation["id"],
                        "attempt": attempt_number,
                        "error_type": type(exc).__name__,
                        "error_digest": error_digest,
                    },
                )
                continue
            value = compensation.to_dict()
            digest = digest_json(value)
            with self.memory.store.transaction():
                self.store.finish_attempt(
                    attempt_id,
                    "verified",
                    provider_request_id=compensation.provider_request_id,
                )
                self.store.put_payload(
                    transaction_id=transaction["id"],
                    operation_id=operation["id"],
                    kind="compensation_receipt",
                    payload=value,
                    digest=digest,
                )
                self.store.set_operation_state(
                    operation["id"],
                    OperationState.COMPENSATED.value,
                    compensation_digest=digest,
                )
                self._event(
                    transaction,
                    "action.compensation_verified",
                    {
                        "operation_id": operation["id"],
                        "attempt": attempt_number,
                        "compensation_digest": digest,
                        "observation_digest": digest_json(verification.observation),
                    },
                )
        return TransactionState.PARTIAL if failures else TransactionState.COMPENSATED

    def _finish(
        self, transaction_id: str, terminal_state: TransactionState
    ) -> dict[str, Any]:
        existing = self.store.list_receipts(transaction_id)
        if existing:
            return {"transaction": self.get(transaction_id), "receipt": existing[-1]}
        transaction = self.get(transaction_id)
        if transaction["state"] != terminal_state.value:
            raise ActionStateError(
                f"cannot issue {terminal_state.value} receipt for transaction in "
                f"state {transaction['state']}"
            )
        operations = [
            {
                "operation_id": item["id"],
                "adapter": item["adapter"],
                "operation": item["operation"],
                "state": item["state"],
                "result_digest": item["result_digest"],
                "compensation_digest": item["compensation_digest"],
            }
            for item in transaction["operations"]
        ]
        with self.memory.store.transaction():
            event_id = self._event(
                transaction,
                "action.receipt_issued",
                {
                    "plan_hash": transaction["plan_hash"],
                    "terminal_state": terminal_state.value,
                    "operations_digest": digest_json(operations),
                },
            )
            event = self.memory.store.get_audit_event(
                transaction["subject_id"], event_id
            )
            if event is None:
                raise RuntimeError("receipt audit event disappeared")
            receipt = ActionReceipt(
                transaction_id=transaction_id,
                subject_id=transaction["subject_id"],
                plan_hash=transaction["plan_hash"],
                terminal_state=terminal_state.value,
                operation_receipts=tuple(operations),
                audit_event_id=event_id,
                audit_event_hash=event["event_hash"],
                created_at=event["created_at"],
            ).signed()
            value = receipt.to_dict()
            self.store.store_receipt(transaction_id, value)
        return {"transaction": self.get(transaction_id), "receipt": value}

    def _event(
        self,
        transaction: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str | None = None,
    ) -> str:
        return self.memory.store.append_audit_event(
            subject_id=transaction["subject_id"],
            event_type=event_type,
            actor=actor or transaction["actor_id"],
            session_id=transaction.get("session_id"),
            turn_id=transaction.get("turn_id"),
            payload={"transaction_id": transaction["id"], **payload},
        )


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _turn_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    return f"t{value}" if isinstance(value, int) else str(value)


def _error_digest(exc: BaseException) -> str:
    return digest_json(
        {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exception_only(type(exc), exc),
        }
    )


def _validate_dependency_graph(operations: list[OperationProposal]) -> None:
    graph = {item.key: set(item.depends_on) for item in operations}
    keys = set(graph)
    unknown = sorted({dep for deps in graph.values() for dep in deps if dep not in keys})
    if unknown:
        raise ValueError(f"unknown operation dependencies: {unknown}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise ValueError("operation dependency graph contains a cycle")
        visiting.add(key)
        for dependency in graph[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def _topological_order(
    operations: list[OperationProposal],
) -> list[OperationProposal]:
    """Stable dependency order, retaining caller order where unconstrained."""
    remaining = list(operations)
    emitted: set[str] = set()
    ordered: list[OperationProposal] = []
    while remaining:
        progressed = False
        for operation in list(remaining):
            if set(operation.depends_on) <= emitted:
                ordered.append(operation)
                emitted.add(operation.key)
                remaining.remove(operation)
                progressed = True
        if not progressed:  # cycle is normally reported by validation above
            raise ValueError("operation dependency graph cannot be ordered")
    return ordered
