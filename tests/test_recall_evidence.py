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


def test_context_injection_is_bound_to_exact_retrieval_id() -> None:
    memory = Memory(":memory:")
    record = memory.remember("u1", "My favorite vehicle is a blue car.")["records"][0]

    block = memory.build_recall_block(
        "u1", "Which vehicle do I like?", session_id="session-1", min_score=0.0
    )

    assert block["retrieval_id"].startswith("ret_")
    assert block["context_event_id"].startswith("aud_")
    context = memory.store.get_audit_event("u1", block["context_event_id"])
    assert context["payload"]["retrieval_id"] == block["retrieval_id"]
    assert context["payload"]["record_ids"] == [record["id"]]


def test_audit_query_combines_filters_and_paginates_without_overlap() -> None:
    memory = Memory(":memory:")
    first = memory.remember("u1", "My favorite color is teal.", session_id="s1")["records"][0]
    memory.remember("u1", "My favorite editor is Neovim.", session_id="s2")
    memory.build_recall_block("u1", "favorite color", session_id="s1", min_score=0.0)

    page_one = memory.store.query_audit_events("u1", limit=2, direction="asc")
    page_two = memory.store.query_audit_events(
        "u1", limit=2, direction="asc", cursor=page_one["next_cursor"]
    )
    assert page_one["matched_total"] >= 4
    assert page_one["has_more"] is True
    assert {row["event_id"] for row in page_one["events"]}.isdisjoint(
        {row["event_id"] for row in page_two["events"]}
    )
    record_events = memory.store.query_audit_events(
        "u1", record_id=first["id"], limit=100
    )["events"]
    assert any(row["event_type"] == "memory.context_injected" for row in record_events)
    assert all(
        row.get("record_id") == first["id"]
        or first["id"] in str(row.get("payload"))
        for row in record_events
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
