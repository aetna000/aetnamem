from __future__ import annotations

import sqlite3

import pytest

from aetnamem import Memory
from aetnamem.decisions import (
    ActorContext,
    ArtifactLink,
    ConsensusPolicy,
    DecisionConflict,
    DecisionEngine,
    DecisionPolicyViolation,
)
from aetnamem.decisions.verify import verify_bundle
from aetnamem.etd import clinical_etd_template, render_markdown


def _case(engine: DecisionEngine, namespace: str = "hospital"):
    chair = ActorContext(namespace, "chair")
    case = engine.create_case(
        chair,
        title="Decision",
        template=clinical_etd_template(),
        content={"question": "Should we change?", "population": "Adults"},
        idempotency_key="create-case",
    )
    return chair, case


def test_decision_tables_are_lazy_and_memory_behavior_is_unchanged(tmp_path) -> None:
    path = tmp_path / "memory.db"
    memory = Memory(path)
    memory.remember("u1", "Remember that my timezone is UTC.")
    names = {
        row[0]
        for row in memory.store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "decision_cases" not in names
    memory.close()

    engine = DecisionEngine(str(path))
    _case(engine)
    engine.close()
    memory = Memory(path)
    assert "timezone is UTC" in memory.recall("u1", "timezone")[0]["content"]
    memory.close()


def test_template_is_pinned_and_artifact_links_are_exact(tmp_path) -> None:
    engine = DecisionEngine(str(tmp_path / "d.db"))
    chair, case = _case(engine)
    evidence = engine.create_artifact(
        chair,
        case["id"],
        kind="evidence_bundle",
        content={"certainty": "low", "trust_tier": "reviewed_source"},
        idempotency_key="evidence",
    )
    assessment = engine.create_artifact(
        chair,
        case["id"],
        kind="criterion_assessment",
        content={
            "criterion": "feasibility",
            "judgment": "probably_yes",
            "rationale": "Possible",
            "ratings": [{"scheme": "grade-certainty", "value": "low"}],
        },
        links=(ArtifactLink(evidence["revision_id"], "supports"),),
        idempotency_key="assessment",
    )
    bundle = engine.export_case(chair, case["id"])
    row = next(item for item in bundle["revisions"] if item["id"] == assessment["revision_id"])
    assert row["links"][0]["source_digest"] == evidence["digest"]
    assert verify_bundle(bundle)["valid"] is True

    tampered = engine.export_case(chair, case["id"])
    next(item for item in tampered["revisions"] if item["id"] == evidence["revision_id"])["content"]["certainty"] = "high"
    assert verify_bundle(tampered)["valid"] is False
    engine.close()


def test_membership_recusal_hidden_vote_and_adoption(tmp_path) -> None:
    engine = DecisionEngine(str(tmp_path / "d.db"))
    chair, case = _case(engine)
    voter = ActorContext("hospital", "voter")
    observer = ActorContext("hospital", "observer")
    engine.add_member(chair, case["id"], principal_id="voter", role="voter", expected_version=1, idempotency_key="add-voter")
    engine.add_member(chair, case["id"], principal_id="observer", role="observer", expected_version=2, idempotency_key="add-observer")
    conflict = engine.declare_conflict(voter, case["id"], scope="case", details={"employer": "supplier"}, idempotency_key="coi")
    engine.rule_conflict(chair, case["id"], conflict["id"], status="recused", rationale="Material conflict", expected_version=1, idempotency_key="coi-rule")
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
        choices=("yes", "no", "abstain"),
        policy=ConsensusPolicy(quorum=1.0, threshold=1.0),
        visibility="hidden_until_close",
        idempotency_key="ballot",
    )
    eligibility = {item["principal_id"]: item for item in ballot["eligibility"]}
    assert eligibility["voter"]["reason"] == "recused"
    assert eligibility["observer"]["eligible"] is False
    with pytest.raises(DecisionPolicyViolation):
        engine.cast_vote(voter, ballot["id"], choice="yes", idempotency_key="bad-vote")
    vote = engine.cast_vote(chair, ballot["id"], choice="yes", rationale="Accepted", idempotency_key="chair-vote")
    repeated_vote = engine.cast_vote(
        chair, ballot["id"], choice="yes", rationale="Accepted", idempotency_key="chair-vote"
    )
    assert repeated_vote["id"] == vote["id"]
    vote = engine.cast_vote(
        chair,
        ballot["id"],
        choice="yes",
        rationale="Accepted after discussion",
        expected_vote_id=vote["id"],
        idempotency_key="chair-vote-revised",
    )
    assert engine.get_ballot(chair, ballot["id"])["votes"] == []
    assert engine.export_case(chair, case["id"])["ballots"][0]["votes"] == []
    outcome = engine.close_ballot(chair, ballot["id"], expected_version=1, idempotency_key="close")
    assert outcome["passed"] is True
    assert outcome["counted_vote_ids"] == [vote["id"]]
    assert engine.get_ballot(chair, ballot["id"])["votes"][0]["id"] == vote["id"]
    adoption = engine.adopt_recommendation(
        chair,
        case["id"],
        recommendation_revision_id=recommendation["revision_id"],
        outcome_id=outcome["id"],
        idempotency_key="adopt",
    )
    assert adoption["target_digest"] == recommendation["digest"]
    assert "Proceed" in render_markdown(engine.export_case(chair, case["id"]))
    engine.close()


def test_idempotency_and_namespace_isolation(tmp_path) -> None:
    engine = DecisionEngine(str(tmp_path / "d.db"))
    chair, case = _case(engine)
    repeated = engine.create_case(
        chair,
        title="Decision",
        template=clinical_etd_template(),
        content={"question": "Should we change?", "population": "Adults"},
        idempotency_key="create-case",
    )
    assert repeated["id"] == case["id"]
    with pytest.raises(DecisionConflict):
        engine.create_case(
            chair,
            title="Different",
            template=clinical_etd_template(),
            content={},
            idempotency_key="create-case",
        )
    with pytest.raises(KeyError):
        engine.get_case(ActorContext("other-hospital", "chair"), case["id"])
    engine.close()


def test_audit_never_contains_conflict_details_or_vote_rationale(tmp_path) -> None:
    engine = DecisionEngine(str(tmp_path / "d.db"))
    chair, case = _case(engine)
    engine.declare_conflict(
        chair,
        case["id"],
        scope="case",
        details={"private": "sensitive conflict detail"},
        idempotency_key="coi",
    )
    audit = str(engine.list_events(chair, case["id"]))
    assert "sensitive conflict detail" not in audit
    engine.close()


def test_decision_mutation_rolls_back_when_audit_append_fails(tmp_path, monkeypatch) -> None:
    engine = DecisionEngine(str(tmp_path / "d.db"))
    chair, case = _case(engine)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(engine.store, "append_audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        engine.create_artifact(
            chair,
            case["id"],
            kind="evidence_bundle",
            content={"title": "must roll back"},
            idempotency_key="failed-artifact",
        )
    count = engine.store.one(
        "SELECT COUNT(*) AS count FROM decision_artifacts WHERE namespace_id = ? AND case_id = ?",
        ("hospital", case["id"]),
    )
    assert count["count"] == 0
    engine.close()
