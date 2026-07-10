from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from aetnamem import Memory
from aetnamem.actions import (
    AdapterReceipt,
    ActionEngine,
    ActionStateError,
    ActionPolicyViolation,
    AdapterDriftError,
    ApprovalAuthority,
    EvidenceRef,
    FilesystemAdapter,
    OperationProposal,
    PreparedOperation,
    EffectClass,
    VerificationResult,
    verify_action,
)
from aetnamem.actions.adapters import ActionContext


SECRET = "approval-secret-that-is-at-least-32-bytes-long"


def authority_evidence() -> EvidenceRef:
    return EvidenceRef(
        kind="user_task",
        ref_id="task-1",
        digest="a" * 64,
        relation="authorized_by",
        trust_tier="trusted_user",
        attested=True,
    )


def build_engine(tmp_path: Path) -> tuple[Memory, ActionEngine, ApprovalAuthority]:
    memory = Memory(tmp_path / "mem.db")
    authority = ApprovalAuthority(SECRET)
    engine = ActionEngine(
        memory,
        adapters=[FilesystemAdapter(tmp_path)],
        approval_authority=authority,
    )
    return memory, engine, authority


def stage_write(engine: ActionEngine, content: str = "hello"):
    return engine.propose(
        "user-1",
        [
            OperationProposal(
                key="write",
                adapter="filesystem",
                operation="write_text",
                arguments={"path": "output.txt", "content": content},
                evidence=(authority_evidence(),),
            )
        ],
        actor_id="agent-1",
    )


def approve(engine: ActionEngine, authority: ApprovalAuthority, patch) -> None:
    engine.approve(
        authority.issue(
            transaction_id=patch.transaction_id,
            plan_hash=patch.plan_hash,
            approver="reviewer-1",
        )
    )


def test_untrusted_evidence_may_not_authorize(tmp_path: Path) -> None:
    memory, engine, _ = build_engine(tmp_path)
    untrusted = replace(
        authority_evidence(), trust_tier="untrusted_content", attested=True
    )
    with pytest.raises(ActionPolicyViolation, match="may inform but cannot authorize"):
        engine.propose(
            "user-1",
            [
                OperationProposal(
                    key="write",
                    adapter="filesystem",
                    operation="write_text",
                    arguments={"path": "output.txt", "content": "hostile"},
                    evidence=(untrusted,),
                )
            ],
            actor_id="agent-1",
        )
    assert engine.list() == []
    memory.close()


def test_evidence_digest_must_be_sha256_hex() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        EvidenceRef(kind="user_task", ref_id="task-1", digest="not-a-digest")


def test_exact_plan_approval_commit_and_receipt(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine, "super secret output")
    approve(engine, authority, patch)
    result = engine.commit(patch.transaction_id)

    assert (tmp_path / "output.txt").read_text() == "super secret output"
    assert result["transaction"]["state"] == "committed"
    assert result["receipt"]["format"] == "aetna-action-receipt-v1"
    assert verify_action(
        memory.store, patch.transaction_id, approval_authority=authority
    )["valid"] is True

    # Raw file content belongs only to the erasable payload plane.
    audit_dump = str(memory.audit("user-1")["audit_log"])
    assert "super secret output" not in audit_dump
    memory.close()


def test_wrong_plan_approval_is_rejected(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    wrong = authority.issue(
        transaction_id=patch.transaction_id,
        plan_hash="0" * 64,
        approver="reviewer-1",
    )
    with pytest.raises(ValueError, match="invalid"):
        engine.approve(wrong)
    assert engine.get(patch.transaction_id)["state"] == "awaiting_approval"
    memory.close()


def test_approval_nonce_cannot_be_replayed(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    approval = authority.issue(
        transaction_id=patch.transaction_id,
        plan_hash=patch.plan_hash,
        approver="reviewer-1",
    )
    engine.approve(approval)
    with pytest.raises(ActionStateError, match="not awaiting_approval"):
        engine.approve(approval)
    assert len(engine.get(patch.transaction_id)["approvals"]) == 1
    memory.close()


def test_world_state_change_invalidates_approved_patch(tmp_path: Path) -> None:
    target = tmp_path / "output.txt"
    target.write_text("before")
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine, "planned")
    approve(engine, authority, patch)
    target.write_text("concurrent change")

    result = engine.commit(patch.transaction_id)
    assert result["transaction"]["state"] == "aborted"
    assert target.read_text() == "concurrent change"
    assert verify_action(memory.store, patch.transaction_id)["valid"] is True
    memory.close()


def test_adapter_manifest_drift_invalidates_approval(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    approve(engine, authority, patch)
    original = engine.adapters["filesystem"].manifest
    engine.adapters["filesystem"].manifest = lambda: {**original(), "version": "2"}

    with pytest.raises(AdapterDriftError):
        engine.commit(patch.transaction_id)
    assert not (tmp_path / "output.txt").exists()
    memory.close()


def test_payload_purge_keeps_receipt_and_audit_verifiable(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    approve(engine, authority, patch)
    engine.commit(patch.transaction_id)

    purged = engine.purge_payloads(patch.transaction_id)
    assert purged["purged_count"] >= 2
    assert engine.get(patch.transaction_id, include_payloads=True)["operations"][0][
        "payloads"
    ] == {}
    assert verify_action(memory.store, patch.transaction_id)["valid"] is True
    memory.close()


def test_receipt_verifier_detects_operational_plan_tampering(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    approve(engine, authority, patch)
    engine.commit(patch.transaction_id)
    memory.store._conn.execute(
        "UPDATE action_operations SET operation = 'delete_file' WHERE transaction_id = ?",
        (patch.transaction_id,),
    )
    result = verify_action(memory.store, patch.transaction_id)
    assert result["valid"] is False
    assert "plan hash" in " ".join(result["failures"])
    memory.close()


def test_plan_mutation_after_approval_prevents_execution(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    approve(engine, authority, patch)
    memory.store._conn.execute(
        "UPDATE action_operations SET operation = 'delete_file' WHERE transaction_id = ?",
        (patch.transaction_id,),
    )
    with pytest.raises(ActionStateError, match="integrity verification failed"):
        engine.commit(patch.transaction_id)
    assert not (tmp_path / "output.txt").exists()
    memory.close()


class FailingAdapter:
    name = "failing"

    def manifest(self):
        return {"adapter": self.name, "version": "1", "operations": ["fail"]}

    def prepare(self, operation: str, arguments: dict, context: ActionContext):
        return PreparedOperation(
            adapter=self.name,
            operation=operation,
            arguments=arguments,
            preview={"will_fail": True},
            preconditions={},
            effect_class=EffectClass.IRREVERSIBLE_STAGED,
        )

    def revalidate(self, prepared):
        return VerificationResult(True, {})

    def execute(self, prepared, *, idempotency_key: str):
        raise RuntimeError("provider failed after request dispatch")

    def verify(self, prepared, receipt):
        raise AssertionError("no receipt expected")

    def compensate(self, prepared, receipt, *, idempotency_key: str):
        raise AssertionError("unknown effect cannot be compensated automatically")

    def verify_compensation(self, prepared, receipt):
        raise AssertionError("unknown effect cannot be verified automatically")


class NoopCompensationAdapter:
    name = "noop-compensation"

    def __init__(self) -> None:
        self.value = "before"

    def manifest(self):
        return {"adapter": self.name, "version": "1", "operations": ["set"]}

    def prepare(self, operation: str, arguments: dict, context: ActionContext):
        return PreparedOperation(
            adapter=self.name,
            operation=operation,
            arguments=arguments,
            preview={"after": arguments["value"]},
            preconditions={"before": self.value},
            effect_class=EffectClass.VERIFIED_COMPENSATABLE,
        )

    def revalidate(self, prepared):
        return VerificationResult(
            self.value == prepared.preconditions["before"], {"value": self.value}
        )

    def execute(self, prepared, *, idempotency_key: str):
        self.value = prepared.arguments["value"]
        return AdapterReceipt(idempotency_key, {}, {"value": self.value})

    def verify(self, prepared, receipt):
        return VerificationResult(
            self.value == prepared.preview["after"], {"value": self.value}
        )

    def compensate(self, prepared, receipt, *, idempotency_key: str):
        # Deliberately lies: returns success without restoring state.
        return AdapterReceipt(idempotency_key, {"claimed": True}, {"value": self.value})

    def verify_compensation(self, prepared, receipt):
        return VerificationResult(
            self.value == prepared.preconditions["before"], {"value": self.value}
        )


def test_later_uncertain_effect_compensates_verified_prior_effect(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "mem.db")
    authority = ApprovalAuthority(SECRET)
    engine = ActionEngine(
        memory,
        adapters=[FilesystemAdapter(tmp_path), FailingAdapter()],
        approval_authority=authority,
    )
    patch = engine.propose(
        "user-1",
        [
            OperationProposal(
                key="write",
                adapter="filesystem",
                operation="write_text",
                arguments={"path": "output.txt", "content": "temporary"},
                evidence=(authority_evidence(),),
            ),
            OperationProposal(
                key="fail",
                adapter="failing",
                operation="fail",
                arguments={},
                evidence=(authority_evidence(),),
                depends_on=("write",),
            ),
        ],
        actor_id="agent-1",
    )
    approve(engine, authority, patch)
    result = engine.commit(patch.transaction_id)

    assert result["transaction"]["state"] == "uncertain"
    assert result["transaction"]["operations"][0]["state"] == "compensated"
    assert result["transaction"]["operations"][1]["state"] == "uncertain"
    assert not (tmp_path / "output.txt").exists()
    assert verify_action(memory.store, patch.transaction_id)["valid"] is True
    memory.close()


def test_noop_compensator_is_detected(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "mem.db")
    authority = ApprovalAuthority(SECRET)
    noop = NoopCompensationAdapter()
    engine = ActionEngine(
        memory,
        adapters=[noop, FailingAdapter()],
        approval_authority=authority,
    )
    patch = engine.propose(
        "user-1",
        [
            OperationProposal(
                key="set",
                adapter=noop.name,
                operation="set",
                arguments={"value": "after"},
                evidence=(authority_evidence(),),
            ),
            OperationProposal(
                key="fail",
                adapter="failing",
                operation="fail",
                arguments={},
                evidence=(authority_evidence(),),
                depends_on=("set",),
            ),
        ],
        actor_id="agent-1",
    )
    approve(engine, authority, patch)
    result = engine.commit(patch.transaction_id)
    assert result["transaction"]["operations"][0]["state"] == "failed"
    assert noop.value == "after"
    assert any(
        event["event_type"] == "action.compensation_failed"
        for event in memory.audit("user-1")["audit_log"]
    )
    memory.close()


def test_standalone_action_verifier(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    approve(engine, authority, patch)
    engine.commit(patch.transaction_id)
    memory.close()
    key_file = tmp_path / "approval.key"
    key_file.write_text(SECRET)
    verifier = Path(__file__).resolve().parents[1] / "tools" / "verify_actions.py"
    result = subprocess.run(
        [
            sys.executable,
            str(verifier),
            str(tmp_path / "mem.db"),
            patch.transaction_id,
            "--approval-key-file",
            str(key_file),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("OK")


def test_interrupted_execution_is_fenced_for_recovery(tmp_path: Path) -> None:
    memory, engine, authority = build_engine(tmp_path)
    patch = stage_write(engine)
    approve(engine, authority, patch)
    transaction = engine.get(patch.transaction_id)
    operation_id = transaction["operations"][0]["id"]
    engine.store.set_transaction_state(patch.transaction_id, "committing")
    engine.store.set_operation_state(operation_id, "executing")

    result = engine.recover(patch.transaction_id)
    assert result["transaction"]["state"] == "recovery_required"
    assert result["transaction"]["operations"][0]["state"] == "uncertain"
    assert not (tmp_path / "output.txt").exists()
    assert verify_action(memory.store, patch.transaction_id)["valid"] is True
    memory.close()
