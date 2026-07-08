from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from aetnamem import Memory
from aetnamem.core.canonical import canonical_json, sha256_hex

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


def test_recall_queries_are_digest_only_by_default() -> None:
    memory = Memory(":memory:")
    memory.remember("user-1", "My favorite color is teal.", session_id="s1")
    memory.recall("user-1", "What is my favorite color?", session_id="s2")

    [event] = memory.get_retrieval_log("user-1")
    assert event["query"] == ""
    assert event["query_sha256"] == sha256_hex("What is my favorite color?")


def test_retain_query_text_is_opt_in() -> None:
    memory = Memory(":memory:", retain_query_text=True)
    memory.remember("user-1", "My favorite color is teal.", session_id="s1")
    memory.recall("user-1", "What is my favorite color?", session_id="s2")

    [event] = memory.get_retrieval_log("user-1")
    assert event["query"] == "What is my favorite color?"


def test_forget_audit_event_carries_digest_not_selector_text() -> None:
    memory = Memory(":memory:")
    memory.remember(
        "user-1", "Remember that my backup email is a@b.com.", session_id="s1"
    )
    memory.forget("user-1", utterance="Forget my backup email.", session_id="s2")

    [forget_event] = [
        event
        for event in memory.audit("user-1")["audit_log"]
        if event["event_type"] == "memory.forget"
    ]
    payload_text = json.dumps(forget_event["payload"])
    assert "backup email" not in payload_text
    assert forget_event["payload"]["selector_sha256"] == sha256_hex("backup email")


def test_tombstoned_record_has_no_fact_key() -> None:
    memory = Memory(":memory:")
    memory.remember("user-1", "My backup email is a@b.com.", session_id="s1")
    memory.forget("user-1", utterance="Forget my backup email.", session_id="s2")

    [record] = memory.list("user-1", include_inactive=True)
    assert record["status"] == "tombstoned"
    assert record["fact_key"] is None
    assert record["content"] == ""


def test_deletion_receipt_binds_to_the_audit_chain() -> None:
    memory = Memory(":memory:")
    memory.remember("user-1", "My backup email is a@b.com.", session_id="s1")
    result = memory.forget(
        "user-1", utterance="Forget my backup email.", session_id="s2"
    )

    receipt = result["receipt"]
    assert receipt["format"] == "aetnamem-deletion-receipt-v1"
    assert receipt["purged_record_ids"] == result["record_ids"]
    assert receipt["purged_episode_ids"]

    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert receipt["receipt_sha256"] == sha256_hex(canonical_json(body))

    event = memory.store.get_audit_event("user-1", receipt["audit_event_id"])
    assert event is not None
    assert event["event_hash"] == receipt["audit_event_hash"]
    assert event["payload"]["purged_record_ids"] == receipt["purged_record_ids"]


def test_checkpoint_roundtrip_verifies(tmp_path: Path) -> None:
    sink = tmp_path / "checkpoints.jsonl"
    memory = Memory(tmp_path / "mem.db")
    memory.remember("user-1", "My favorite color is teal.", session_id="s1")

    document = memory.checkpoint(sink_path=sink)
    assert document["format"] == "aetnamem-checkpoint-v1"
    assert "user-1" in document["subjects"]

    memory.remember("user-1", "My home city is Sydney.", session_id="s2")
    result = memory.verify(checkpoints_path=sink)
    assert result["valid"] is True
    assert result["subjects"]["user-1"]["checkpoints_checked"] == 1


def test_checkpoint_detects_tail_truncation(tmp_path: Path) -> None:
    sink = tmp_path / "checkpoints.jsonl"
    memory = Memory(tmp_path / "mem.db")
    memory.remember("user-1", "My favorite color is teal.", session_id="s1")
    memory.remember("user-1", "My home city is Sydney.", session_id="s2")
    memory.checkpoint(sink_path=sink)

    # Adversarially delete the last audit event straight in SQLite.
    memory.store._conn.execute(
        "DELETE FROM audit_log WHERE sequence = (SELECT MAX(sequence) FROM audit_log)"
    )
    memory.store._conn.commit()

    # The chain alone still verifies — truncation is invisible to it...
    assert memory.verify()["valid"] is True
    # ...but the anchored checkpoint catches it.
    result = memory.verify(checkpoints_path=sink)
    assert result["valid"] is False
    assert any(
        "truncated" in failure["reason"]
        for failure in result["subjects"]["user-1"]["failures"]
    )


def test_standalone_verifier_agrees(tmp_path: Path) -> None:
    db_path = tmp_path / "mem.db"
    sink = tmp_path / "checkpoints.jsonl"
    memory = Memory(db_path)
    memory.remember("user-1", "My favorite color is teal.", session_id="s1")
    memory.recall("user-1", "What is my favorite color?", session_id="s1")
    memory.checkpoint(sink_path=sink)
    memory.close()

    intact = subprocess.run(
        [
            sys.executable,
            str(TOOLS_DIR / "verify_audit.py"),
            str(db_path),
            "--checkpoints",
            str(sink),
        ],
        capture_output=True,
        text=True,
    )
    assert intact.returncode == 0, intact.stdout + intact.stderr

    # Tamper with one payload and the standalone verifier must fail.
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE audit_log SET payload = '{\"forged\":true}' "
        "WHERE sequence = (SELECT MIN(sequence) FROM audit_log)"
    )
    conn.commit()
    conn.close()

    tampered = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "verify_audit.py"), str(db_path)],
        capture_output=True,
        text=True,
    )
    assert tampered.returncode == 1
    assert "FAIL" in tampered.stdout
