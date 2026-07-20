from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from aetnamem.decisions import ActorContext, ConsensusPolicy, DecisionEngine
from aetnamem.etd import generic_etd_template


def test_twenty_concurrent_voters_are_counted_once(tmp_path) -> None:
    path = tmp_path / "votes.db"
    setup = DecisionEngine(str(path))
    chair = ActorContext("org", "chair")
    case = setup.create_case(
        chair,
        title="Concurrent ballot",
        template=generic_etd_template(),
        content={"question": "Proceed?"},
        idempotency_key="case",
    )
    version = 1
    voters = [f"voter-{index:02d}" for index in range(20)]
    for principal in voters:
        setup.add_member(
            chair,
            case["id"],
            principal_id=principal,
            role="voter",
            expected_version=version,
            idempotency_key=f"member-{principal}",
        )
        version += 1
    recommendation = setup.create_artifact(
        chair,
        case["id"],
        kind="recommendation",
        content={"text": "Proceed", "direction": "for", "strength": "conditional"},
        idempotency_key="recommendation",
    )
    ballot = setup.open_ballot(
        chair,
        case["id"],
        target_revision_id=recommendation["revision_id"],
        choices=("yes", "no"),
        policy=ConsensusPolicy(quorum=0.5, threshold=0.5),
        idempotency_key="ballot",
    )
    setup.close()

    def vote(principal: str) -> str:
        engine = DecisionEngine(str(path))
        try:
            result = engine.cast_vote(
                ActorContext("org", principal),
                ballot["id"],
                choice="yes",
                idempotency_key=f"vote-{principal}",
            )
            return result["id"]
        finally:
            engine.close()

    with ThreadPoolExecutor(max_workers=20) as pool:
        ids = list(pool.map(vote, voters))
    assert len(set(ids)) == 20

    engine = DecisionEngine(str(path))
    outcome = engine.close_ballot(
        chair, ballot["id"], expected_version=1, idempotency_key="close"
    )
    assert outcome["participating"] == 20
    assert outcome["passed"] is True
    assert len(outcome["counted_vote_ids"]) == 20
    engine.close()

