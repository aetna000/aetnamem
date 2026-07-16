from __future__ import annotations

from aetnamem import Memory
from aetnamem.core.canonical import canonical_json, sha256_hex


def test_recall_evidence_digest_binds_row_identity_parameters_and_scores() -> None:
    memory = Memory(":memory:")
    record = memory.remember("u1", "My favorite color is teal.")["records"][0]

    memory.recall("u1", "What is my favorite color?", limit=1, min_score=0.2)

    [retrieval] = memory.get_retrieval_log("u1")
    [audit] = [
        event
        for event in memory.audit("u1")["audit_log"]
        if event["event_type"] == "memory.recall"
    ]
    preimage = {
        "format": "aetnamem-retrieval-evidence-v2",
        "retrieval_id": retrieval["id"],
        "subject_id": retrieval["subject_id"],
        "session_id": retrieval["session_id"],
        "query": retrieval["query"],
        "query_sha256": retrieval["query_sha256"],
        "candidates": retrieval["candidates"],
        "returned_ids": retrieval["returned_ids"],
        "raw": retrieval["raw"],
    }
    assert audit["payload"]["retrieval_sha256"] == sha256_hex(
        canonical_json(preimage)
    )
    assert retrieval["raw"]["replay"] == {
        "use_graph": False,
        "limit": 1,
        "min_score": 0.2,
        "candidate_cap": 200,
        "ranker_version": "record-rank-v1",
        "record_weights": {"text": 0.75, "trust": 0.15, "recency": 0.1},
        "fusion_version": None,
        "rrf_rank_constant": 60.0,
        "graph_rrf_weight": 2.0,
        "candidate_log_window": 50,
    }

    [candidate] = retrieval["candidates"]
    assert candidate["record_id"] == record["id"]
    assert candidate["base_score"] == round(
        0.75 * candidate["text_score"]
        + 0.15 * candidate["trust_score"]
        + 0.10 * candidate["recency_score"],
        6,
    )


def test_every_returned_result_is_logged_when_limit_exceeds_diagnostic_window() -> None:
    memory = Memory(":memory:")
    for index in range(60):
        memory.remember(
            "u1", f"My synthetic setting {index} is synthetic-value-{index}."
        )

    returned = memory.recall("u1", "synthetic setting", limit=60)

    [retrieval] = memory.get_retrieval_log("u1")
    assert len(returned) == 60
    assert len(retrieval["candidates"]) == 60
    assert [candidate["rank"] for candidate in retrieval["candidates"]] == list(
        range(1, 61)
    )
    assert {candidate["record_id"] for candidate in retrieval["candidates"]} == {
        record["id"] for record in returned
    }


def test_record_admission_binds_lifecycle_metadata() -> None:
    memory = Memory(":memory:")
    record = memory.remember("u1", "My favorite color is teal.")["records"][0]

    [admission] = [
        event
        for event in memory.audit("u1")["audit_log"]
        if event["event_type"] == "memory.record_created"
    ]
    payload = admission["payload"]
    assert payload["content_sha256"] == sha256_hex(record["content"])
    assert payload["source_type"] == record["source_type"]
    assert payload["trust_tier"] == record["trust_tier"]
    assert payload["confidence"] == record["confidence"]
    assert payload["scope"] == record["scope"]
