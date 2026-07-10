from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from aetnamem import Memory
from aetnamem.actions import TransactionJournalImporter


def make_source_journal(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE transactions (
          txn_id TEXT PRIMARY KEY, state TEXT, created_at TEXT, updated_at TEXT,
          replayed_from TEXT, dry_run INTEGER, client_id TEXT
        );
        CREATE TABLE effects (
          txn_id TEXT, idx INTEGER, effect_id TEXT, tool TEXT, resource TEXT,
          reversible INTEGER, status TEXT, args TEXT, snapshot TEXT, result TEXT,
          read_keys TEXT, write_keys TEXT, actor TEXT, ts TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("txn-1", "COMMITTED", "2026-01-01", "2026-01-01", None, 0, "secret-client"),
    )
    conn.execute(
        "INSERT INTO effects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "txn-1", 0, "effect-1", "send_email", "http", 0, "APPLIED",
            json.dumps({"body": "private legacy payload"}),
            json.dumps({"token": "private snapshot"}),
            json.dumps({"provider": "private result"}),
            "[]", "[]", "claimed-admin", "2026-01-01",
        ),
    )
    conn.commit()
    conn.close()


def test_source_import_is_digest_only_and_idempotent(tmp_path: Path) -> None:
    journal_path = tmp_path / "source-journal.db"
    make_source_journal(journal_path)
    memory = Memory(tmp_path / "aetna.db")
    importer = TransactionJournalImporter(memory)

    first = importer.import_journal(
        journal_path,
        subject_id="user-1",
        source_id="production-ledger",
    )
    second = importer.import_journal(
        journal_path,
        subject_id="user-1",
        source_id="production-ledger",
    )

    assert len(first["imported"]) == 1
    assert second["imported"] == []
    assert second["skipped_transaction_ids"] == ["txn-1"]
    audit = memory.audit("user-1")
    [event] = audit["audit_log"]
    assert event["event_type"] == "action.source_imported"
    assert event["payload"]["evidence_status"] == "unverified_operational_journal"
    dumped = json.dumps(audit)
    assert "private legacy payload" not in dumped
    assert "private snapshot" not in dumped
    assert "private result" not in dumped
    assert "secret-client" not in dumped
    assert "claimed-admin" not in dumped
    assert audit["audit_chain_valid"] is True
    memory.close()
