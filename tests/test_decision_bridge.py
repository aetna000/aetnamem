from __future__ import annotations

from pathlib import Path

import pytest

from aetnamem import Memory
from aetnamem.actions import (
    ActionEngine,
    ApprovalAuthority,
    FilesystemAdapter,
    GuardPolicy,
    OperationProposal,
)
from aetnamem.decisions import ActorContext, DecisionAuthorityResolver, DecisionEngine
from aetnamem.decisions.models import DecisionPolicyViolation
from aetnamem.etd.playground import run_demo


SECRET = "decision-approval-secret-at-least-32-bytes"


def test_decision_authority_is_resolved_at_stage_and_commit(tmp_path: Path) -> None:
    db = tmp_path / "shared.db"
    demo = run_demo(db, namespace_id="hospital")
    decision = DecisionEngine(str(db))
    resolver = DecisionAuthorityResolver(decision, "hospital")
    refs = resolver.evidence_refs(str(demo["authorization_id"]))

    memory = Memory(db)
    signer = ApprovalAuthority(SECRET)
    actions = ActionEngine(
        memory,
        adapters=[FilesystemAdapter(tmp_path)],
        approval_authority=signer,
        policy=GuardPolicy(
            trusted_authority_tiers=("trusted_user", "user_confirmed", "decision_authorization")
        ),
        authority_resolver=resolver,
    )
    proposal = lambda content: OperationProposal(
        key="write",
        adapter="filesystem",
        operation="write_text",
        arguments={"path": "approved-change.md", "content": content},
        evidence=refs,
    )
    first = actions.propose("hospital-change", [proposal("approved")], actor_id="agent")
    actions.approve(
        signer.issue(
            transaction_id=first.transaction_id,
            plan_hash=first.plan_hash,
            approver="operations-reviewer",
        )
    )
    receipt = actions.commit(first.transaction_id)
    resolver.link_action(str(demo["authorization_id"]), first.transaction_id, receipt["receipt"]["receipt_sha256"])
    assert (tmp_path / "approved-change.md").read_text() == "approved"

    second = actions.propose("hospital-change", [proposal("must not run")], actor_id="agent")
    actions.approve(
        signer.issue(
            transaction_id=second.transaction_id,
            plan_hash=second.plan_hash,
            approver="operations-reviewer",
        )
    )
    decision.revoke_authorization(
        ActorContext("hospital", "dr-chair"),
        str(demo["authorization_id"]),
        reason="Pilot paused",
        idempotency_key="revoke-for-test",
    )
    with pytest.raises(DecisionPolicyViolation, match="not active"):
        actions.commit(second.transaction_id)
    assert (tmp_path / "approved-change.md").read_text() == "approved"
    memory.close()
    decision.close()

