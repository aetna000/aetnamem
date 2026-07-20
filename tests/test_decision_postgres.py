from __future__ import annotations

import multiprocessing
import os
import uuid
import hashlib
import json

import pytest

from aetnamem.decisions import ActorContext, ConsensusPolicy, DecisionEngine, PostgresDecisionStore
from aetnamem.etd import clinical_etd_template
from aetnamem.etd.playground import run_demo
from aetnamem.decisions.verify import verify_bundle


DSN = os.environ.get("AETNAMEM_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set AETNAMEM_TEST_POSTGRES_DSN for PostgreSQL contract tests")


def _cast_vote(dsn: str, namespace: str, ballot_id: str, principal: str, queue) -> None:
    try:
        engine = DecisionEngine.postgres(dsn)
        result = engine.cast_vote(
            ActorContext(namespace, principal),
            ballot_id,
            choice="yes",
            idempotency_key=f"vote-{principal}",
        )
        engine.close()
        queue.put(("ok", result["id"]))
    except Exception as exc:  # pragma: no cover - returned to parent for assertion
        queue.put(("error", repr(exc)))


def _race_command(dsn: str, namespace: str, ballot_id: str, command: str, ready, start, queue) -> None:
    engine = DecisionEngine.postgres(dsn)
    ready.put(command)
    start.wait(10)
    try:
        if command == "vote":
            result = engine.cast_vote(
                ActorContext(namespace, "voter"),
                ballot_id,
                choice="yes",
                idempotency_key="race-vote",
            )
        else:
            result = engine.close_ballot(
                ActorContext(namespace, "chair"),
                ballot_id,
                expected_version=1,
                idempotency_key="race-close",
            )
        queue.put((command, "ok", result))
    except Exception as exc:  # pragma: no cover - asserted by parent
        queue.put((command, "error", type(exc).__name__))
    finally:
        engine.close()


def test_postgres_repository_contract_and_multi_process_voting() -> None:
    assert DSN is not None
    namespace = f"postgres-{uuid.uuid4().hex}"
    engine = DecisionEngine.postgres(DSN)
    chair = ActorContext(namespace, "chair")
    case = engine.create_case(
        chair,
        title="PostgreSQL panel",
        template=clinical_etd_template(),
        content={"question": "Can multiple workers vote safely?"},
        idempotency_key="case",
    )
    voters = [f"voter-{index}" for index in range(8)]
    for index, voter in enumerate(voters, start=1):
        engine.add_member(
            chair,
            case["id"],
            principal_id=voter,
            role="voter",
            expected_version=index,
            idempotency_key=f"member-{voter}",
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
        policy=ConsensusPolicy(quorum=0.8, threshold=1.0),
        idempotency_key="ballot",
    )
    engine.close()

    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_cast_vote, args=(DSN, namespace, ballot["id"], voter, queue))
        for voter in voters
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    results = [queue.get(timeout=5) for _ in processes]
    assert all(status == "ok" for status, _ in results), results

    engine = DecisionEngine.postgres(DSN)
    visible = engine.get_ballot(chair, ballot["id"])
    assert len(visible["votes"]) == len(voters)
    outcome = engine.close_ballot(
        chair, ballot["id"], expected_version=1, idempotency_key="close"
    )
    assert outcome["passed"] is True
    assert outcome["participating"] == len(voters)
    events = engine.list_events(chair, case["id"])
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences) and len(sequences) == len(set(sequences))
    previous = None
    for event in events:
        assert event["prev_hash"] == previous
        preimage = {
            key: event[key]
            for key in (
                "event_id", "subject_id", "event_type", "created_at", "actor",
                "session_id", "turn_id", "record_id", "payload", "prev_hash",
            )
        }
        expected = hashlib.sha256(
            json.dumps(preimage, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert event["event_hash"] == expected
        previous = event["event_hash"]
    engine.close()


def test_postgres_vote_close_race_is_atomic_across_processes() -> None:
    assert DSN is not None
    namespace = f"race-{uuid.uuid4().hex}"
    engine = DecisionEngine.postgres(DSN)
    chair = ActorContext(namespace, "chair")
    case = engine.create_case(
        chair,
        title="Vote close race",
        template=clinical_etd_template(),
        content={"question": "Race?"},
        idempotency_key="case",
    )
    engine.add_member(
        chair,
        case["id"],
        principal_id="voter",
        role="voter",
        expected_version=1,
        idempotency_key="member",
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
        policy=ConsensusPolicy(quorum=0.0),
        idempotency_key="ballot",
    )
    engine.close()

    context = multiprocessing.get_context("spawn")
    ready, queue = context.Queue(), context.Queue()
    start = context.Event()
    processes = [
        context.Process(
            target=_race_command,
            args=(DSN, namespace, ballot["id"], command, ready, start, queue),
        )
        for command in ("vote", "close")
    ]
    for process in processes:
        process.start()
    assert {ready.get(timeout=10), ready.get(timeout=10)} == {"vote", "close"}
    start.set()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    results = {command: (status, payload) for command, status, payload in (queue.get(timeout=5), queue.get(timeout=5))}
    assert results["close"][0] == "ok"
    if results["vote"][0] == "ok":
        assert results["vote"][1]["id"] in results["close"][1]["counted_vote_ids"]
    else:
        assert results["vote"] == ("error", "DecisionStateError")


def test_complete_etd_playground_contract_runs_on_postgres() -> None:
    assert DSN is not None
    namespace = f"playground-{uuid.uuid4().hex}"
    engine = DecisionEngine.postgres(DSN)
    result = run_demo(None, namespace_id=namespace, engine=engine)
    assert verify_bundle(result["bundle"])["valid"] is True
    assert result["authorization_id"]
    engine.close()


def test_postgres_repository_accepts_and_restores_pooled_connection() -> None:
    assert DSN is not None
    import psycopg

    connection = psycopg.connect(DSN)
    original_row_factory = connection.row_factory
    repository = PostgresDecisionStore(connection=connection)
    assert connection.autocommit is True
    engine = DecisionEngine(repository)
    namespace = f"pool-{uuid.uuid4().hex}"
    case = engine.create_case(
        ActorContext(namespace, "chair"),
        title="Pool contract",
        template=clinical_etd_template(),
        content={},
        idempotency_key="case",
    )
    assert case["id"]
    engine.close()
    assert connection.closed is False
    repository.close()
    assert connection.autocommit is False
    assert connection.row_factory is original_row_factory
    connection.close()
