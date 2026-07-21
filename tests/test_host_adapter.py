from __future__ import annotations

import pytest

from aetnamem import Memory
from aetnamem.core.canonical import sha256_hex


def test_capture_user_turn_runs_write_pipeline() -> None:
    memory = Memory(":memory:")
    result = memory.capture("u1", "user", "My favorite color is teal.", session_id="s1")
    assert result["kind"] == "remembered"
    assert result["records"][0]["status"] == "active"


def test_capture_assistant_turn_is_digest_only() -> None:
    memory = Memory(":memory:")
    secret_reply = "Sure — your door code is 4711."
    result = memory.capture("u1", "assistant", secret_reply, session_id="s1")
    assert result["kind"] == "logged"

    # No memory record, no episode: only a digest in the audit chain.
    inspected = memory.inspect("u1")
    assert inspected["records"] == []
    assert inspected["episodes"] == []
    [event] = inspected["audit_log"]
    assert event["event_type"] == "agent.response_shown"
    assert event["payload"]["response_sha256"] == sha256_hex(secret_reply)
    assert "4711" not in str(event["payload"])


def test_capture_tool_traffic_logs_digests() -> None:
    memory = Memory(":memory:")
    memory.capture("u1", "tool_call", '{"city":"Sydney"}', tool_name="weather.get")
    memory.capture("u1", "tool_result", "22C sunny", tool_name="weather.get")
    types = [e["event_type"] for e in memory.audit("u1")["audit_log"]]
    assert types == ["agent.tool_call", "agent.tool_result"]


def test_capture_rejects_unknown_role() -> None:
    memory = Memory(":memory:")
    with pytest.raises(ValueError):
        memory.capture("u1", "system", "nope")


def test_recall_block_is_bounded_and_audited() -> None:
    memory = Memory(":memory:")
    memory.remember("u1", "My favorite color is teal.", session_id="s1")
    memory.remember("u1", "My home city is Sydney.", session_id="s1")

    result = memory.build_recall_block("u1", "What is my favorite color?")
    assert result["count"] == 1
    assert "teal" in result["block"]
    assert result["block"].startswith("<relevant_memories>")
    assert result["block"].endswith("</relevant_memories>")

    [event] = [
        e
        for e in memory.audit("u1")["audit_log"]
        if e["event_type"] == "memory.context_injected"
    ]
    assert event["payload"]["record_ids"] == result["record_ids"]
    assert event["payload"]["block_sha256"] == sha256_hex(result["block"])


def test_recall_block_priors_alone_never_inject() -> None:
    memory = Memory(":memory:")
    memory.remember("u1", "My favorite color is teal.", session_id="s1")

    result = memory.build_recall_block("u1", "zzz completely unrelated query")
    assert result["block"] == ""
    assert result["count"] == 0


def test_recall_block_respects_char_budget() -> None:
    memory = Memory(":memory:")
    for index in range(5):
        memory.remember("u1", f"Remember that fact number {index} is about colors.")

    result = memory.build_recall_block(
        "u1", "Tell me about the colors facts", max_chars=140
    )
    assert 0 < result["count"] < 5
    assert len(result["block"]) <= 140 + len("<relevant_memories>\n\n</relevant_memories>")


def test_compact_prompt_references_preserve_full_audit_ids() -> None:
    memory = Memory(":memory:")
    [record] = memory.remember("u1", "My favorite color is teal.")["records"]

    result = memory.build_recall_block(
        "u1", "favorite color", reference_mode="compact"
    )
    assert f"[m:{record['id'].removeprefix('rec_')[:8]}]" in result["block"]
    assert record["id"] not in result["block"]

    injected = [
        event
        for event in memory.audit("u1")["audit_log"]
        if event["event_type"] == "memory.context_injected"
    ][-1]
    assert injected["payload"]["record_ids"] == [record["id"]]
    assert injected["payload"]["reference_mode"] == "compact"
    assert injected["payload"]["block_sha256"] == sha256_hex(result["block"])


def test_persona_reference_mode_none_omits_ids_but_audits_them() -> None:
    memory = Memory(":memory:")
    [record] = memory.remember("u1", "My favorite color is teal.")["records"]
    persona = memory.build_persona("u1", reference_mode="none")
    assert "teal" in persona["block"]
    assert record["id"] not in persona["block"]
    event = [
        item
        for item in memory.audit("u1")["audit_log"]
        if item["event_type"] == "memory.persona_built"
    ][-1]
    assert event["payload"]["record_ids"] == [record["id"]]
    assert event["payload"]["reference_mode"] == "none"


def test_prompt_reference_mode_is_validated() -> None:
    memory = Memory(":memory:")
    with pytest.raises(ValueError, match="reference_mode"):
        memory.build_recall_block("u1", "anything", reference_mode="invalid")


def test_consolidate_collapses_duplicates_and_repairs_keys() -> None:
    memory = Memory(":memory:")
    # Forge a pathological state directly at the store layer: two identical
    # actives and two actives sharing a fact_key (the write path prevents
    # this, consolidation must repair it anyway).
    for content, key in [
        ("User's favorite color is teal.", "favorite color"),
        ("User's favorite color is teal.", "favorite color"),
        ("User's home city is Sydney.", "home city"),
        ("User's home city is Berlin.", "home city"),
    ]:
        memory.store.insert_record(
            subject_id="u1",
            content=content,
            source_type="user_message",
            trust_tier="trusted_user",
            source_session_id="s1",
            source_turn_id=None,
            episode_id=None,
            confidence=0.9,
            scope="user_private",
            fact_key=key,
        )

    report = memory.consolidate("u1")
    active = memory.list("u1")

    assert len(active) == 2
    contents = " ".join(r["content"] for r in active)
    assert "teal" in contents and "Berlin" in contents
    assert len(report["duplicates_superseded"]) == 1
    assert len(report["fact_key_repaired"]) == 1
    assert report["active_after"] == 2

    types = [e["event_type"] for e in memory.audit("u1")["audit_log"]]
    assert "memory.consolidated" in types
    assert memory.audit("u1")["audit_chain_valid"] is True


def test_consolidate_is_idempotent() -> None:
    memory = Memory(":memory:")
    memory.remember("u1", "My favorite color is teal.")
    first = memory.consolidate("u1")
    second = memory.consolidate("u1")
    assert first["duplicates_superseded"] == second["duplicates_superseded"] == []
    assert len(memory.list("u1")) == 1
