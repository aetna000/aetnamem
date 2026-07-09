from __future__ import annotations

from aetnamem import Memory


def _seeded() -> Memory:
    memory = Memory(":memory:")
    memory.remember("u1", "My preferred airport is SFO.", session_id="s1")
    memory.remember(
        "u1",
        "Remember that my travel itineraries should be private by default.",
        session_id="s1",
    )
    memory.remember("u1", "My favorite color is teal.", session_id="s2")
    return memory


def test_persona_groups_keyed_facts_first_with_provenance() -> None:
    memory = _seeded()
    persona = memory.build_persona("u1")

    assert persona["count"] == 3
    lines = persona["block"].splitlines()
    assert lines[0] == "<user_persona>"
    assert lines[-1] == "</user_persona>"
    # keyed slots (favorite color, preferred airport) before unkeyed facts
    assert "favorite color" in lines[1] or "preferred airport" in lines[1]
    assert "itineraries" in lines[3]
    # every line carries the source record id
    active_ids = {record["id"] for record in memory.list("u1")}
    assert set(persona["record_ids"]) == active_ids
    for line in lines[1:-1]:
        assert line.startswith("- [rec_")

    [event] = [
        e
        for e in memory.audit("u1")["audit_log"]
        if e["event_type"] == "memory.persona_built"
    ]
    assert event["payload"]["record_ids"] == persona["record_ids"]


def test_persona_reflects_supersession_and_deletion_immediately() -> None:
    memory = _seeded()
    memory.remember("u1", "Actually, use OAK as my preferred airport going forward.")
    memory.forget("u1", utterance="Forget my favorite color.")

    block = memory.build_persona("u1")["block"]
    assert "OAK" in block
    assert "SFO" not in block
    assert "teal" not in block


def test_persona_respects_char_budget() -> None:
    memory = _seeded()
    persona = memory.build_persona("u1", max_chars=80)
    assert 0 < persona["count"] < 3


def test_scenes_group_by_session_with_provenance() -> None:
    memory = _seeded()
    scenes = memory.scenes("u1")

    assert [scene["session_id"] for scene in scenes] == ["s2", "s1"]
    s1 = next(scene for scene in scenes if scene["session_id"] == "s1")
    assert len(s1["episode_ids"]) == 2
    assert len(s1["record_ids"]) == 2
    s2 = next(scene for scene in scenes if scene["session_id"] == "s2")
    assert len(s2["record_ids"]) == 1


def test_propose_facts_land_quarantined_with_evidence() -> None:
    memory = _seeded()
    episode_id = memory.inspect("u1")["episodes"][0]["id"]

    result = memory.propose_facts(
        "u1",
        [
            {
                "content": "User travels for work roughly monthly.",
                "fact_key": "travel frequency",
                "confidence": 0.6,
                "evidence": [episode_id],
            }
        ],
        proposer="llm-batch-1",
    )

    [record] = result["quarantined"]
    assert record["status"] == "quarantined"
    assert record["trust_tier"] == "derived"
    assert record["raw"]["evidence"] == [episode_id]
    assert record["raw"]["proposer"] == "llm-batch-1"

    # Invisible to recall and persona until promoted.
    assert all(
        "monthly" not in r["content"]
        for r in memory.recall("u1", "How often does the user travel?")
    )
    assert "monthly" not in memory.build_persona("u1")["block"]

    promoted = memory.promote("u1", record["id"])
    assert promoted["status"] == "active"
    assert "monthly" in memory.build_persona("u1")["block"]
    assert memory.audit("u1")["audit_chain_valid"] is True


def test_propose_facts_rejects_missing_or_unknown_evidence() -> None:
    memory = _seeded()

    result = memory.propose_facts(
        "u1",
        [
            {"content": "No evidence at all."},
            {"content": "Fabricated evidence.", "evidence": ["ep_doesnotexist"]},
            {"content": "", "evidence": ["whatever"]},
        ],
    )

    assert result["quarantined"] == []
    assert len(result["rejected"]) == 3
    assert memory.list("u1", include_inactive=True) == memory.list(
        "u1", include_inactive=True
    )


def test_propose_facts_dedupes_against_existing_records() -> None:
    memory = _seeded()
    episode_id = memory.inspect("u1")["episodes"][0]["id"]

    result = memory.propose_facts(
        "u1",
        [
            {
                "content": "User's favorite color is teal.",
                "evidence": [episode_id],
            }
        ],
    )
    assert result["quarantined"] == []
    assert len(result["duplicate_ids"]) == 1
