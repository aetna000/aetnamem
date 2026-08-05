from __future__ import annotations

from pathlib import Path

from aetnamem.control.evidence import seal_report, verify_report
from aetnamem.control.store import ControlStore, SCHEMA_VERSION


def _store(tmp_path: Path, name: str = "evidence.db") -> tuple[ControlStore, str]:
    store = ControlStore(tmp_path / name)
    migration_id = f"migration-{name}"
    store.create_migration(migration_id, "openclaw", "local-user")
    return store, migration_id


def test_report_and_evidence_digests_have_separate_stability() -> None:
    stable = {"checks": [{"name": "mirror", "status": "pass"}]}
    first = seal_report(
        {
            "format": "aetnamem-control-verification-v1",
            "started_at": "2026-08-03T00:00:00Z",
            "ended_at": "2026-08-03T00:00:01Z",
            **stable,
        },
        stable_evidence=stable,
    )
    second = seal_report(
        {
            "format": "aetnamem-control-verification-v1",
            "started_at": "2026-08-03T00:01:00Z",
            "ended_at": "2026-08-03T00:01:02Z",
            **stable,
        },
        stable_evidence=stable,
    )
    assert first["evidence_sha256"] == second["evidence_sha256"]
    assert first["report_sha256"] != second["report_sha256"]
    assert verify_report(first, stable_evidence=stable)["valid"] is True


def test_v1_control_store_migrates_without_losing_rows(tmp_path: Path) -> None:
    path = tmp_path / "control.db"
    store = ControlStore(path)
    store.create_migration("migration-1", "openclaw", "subject-1")
    store.close()

    # Recreate the exact observable v1 condition: legacy tables and data,
    # schema version 1, with no evidence table yet.
    import sqlite3

    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE evidence")
    connection.execute(
        "UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'"
    )
    connection.commit()
    connection.close()

    migrated = ControlStore(path)
    try:
        version = migrated._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()["value"]
        assert int(version) == SCHEMA_VERSION
        migration = migrated._conn.execute(
            "SELECT subject_id FROM migrations WHERE migration_id = 'migration-1'"
        ).fetchone()
        assert migration["subject_id"] == "subject-1"
        row = migrated.append_evidence(
            "migration-1",
            kind="verification",
            body={"format": "aetnamem-control-verification-v1", "valid": True},
        )
        assert row["sequence"] == 1
    finally:
        migrated.close()


def test_evidence_chains_are_scoped_and_detect_body_tampering(tmp_path: Path) -> None:
    store, first_migration = _store(tmp_path)
    second_migration = "migration-2"
    store.create_migration(second_migration, "openclaw", "subject-2")
    try:
        first = store.append_evidence(
            first_migration,
            kind="verification",
            body={"format": "aetnamem-control-verification-v1", "valid": True},
        )
        second = store.append_evidence(
            first_migration,
            kind="verification",
            body={"format": "aetnamem-control-verification-v1", "valid": False},
        )
        other = store.append_evidence(
            second_migration,
            kind="verification",
            body={"format": "aetnamem-control-verification-v1", "valid": True},
        )
        assert first["sequence"] == other["sequence"] == 1
        assert second["sequence"] == 2
        assert store.verify_evidence_chain(
            first_migration, kind="verification"
        )["valid"] is True

        store._conn.execute(
            "UPDATE evidence SET body_json = ? WHERE id = ?",
            ('{"format":"aetnamem-control-verification-v1","valid":"tampered"}', first["id"]),
        )
        store._conn.commit()
        result = store.verify_evidence_chain(first_migration, kind="verification")
        assert result["valid"] is False
        assert any("body digest mismatch" in item for item in result["errors"])
    finally:
        store.close()


def test_evidence_chain_detects_reordering_and_cross_migration_splice(
    tmp_path: Path,
) -> None:
    store, migration_id = _store(tmp_path)
    other_migration = "migration-other"
    store.create_migration(other_migration, "openclaw", "other")
    try:
        first = store.append_evidence(
            migration_id,
            kind="restore",
            body={"format": "aetnamem-restore-receipt-v1", "step": 1},
        )
        second = store.append_evidence(
            migration_id,
            kind="restore",
            body={"format": "aetnamem-restore-receipt-v1", "step": 2},
        )
        foreign = store.append_evidence(
            other_migration,
            kind="restore",
            body={"format": "aetnamem-restore-receipt-v1", "step": 9},
        )

        # Swap the stored bodies without recomputing their bound entries.
        store._conn.execute(
            "UPDATE evidence SET body_json = ? WHERE id = ?",
            (store._conn.execute("SELECT body_json FROM evidence WHERE id = ?", (second["id"],)).fetchone()[0], first["id"]),
        )
        store._conn.commit()
        assert store.verify_evidence_chain(migration_id, kind="restore")["valid"] is False

        # Rebuild a clean database, then splice a foreign migration identity
        # into a locally ordered row. Identity binding must detect it.
    finally:
        store.close()

    splice, local_migration = _store(tmp_path, "splice.db")
    foreign_migration = "foreign"
    splice.create_migration(foreign_migration, "openclaw", "foreign")
    try:
        local = splice.append_evidence(
            local_migration,
            kind="restore",
            body={"format": "aetnamem-restore-receipt-v1", "step": 1},
        )
        foreign = splice.append_evidence(
            foreign_migration,
            kind="restore",
            body={"format": "aetnamem-restore-receipt-v1", "step": 2},
        )
        splice._conn.execute(
            """
            UPDATE evidence SET body_json = ?, body_sha256 = ?, entry_sha256 = ?
            WHERE id = ?
            """,
            (
                splice._conn.execute(
                    "SELECT body_json FROM evidence WHERE id = ?", (foreign["id"],)
                ).fetchone()[0],
                foreign["body_sha256"],
                foreign["entry_sha256"],
                local["id"],
            ),
        )
        splice._conn.commit()
        assert splice.verify_evidence_chain(
            local_migration, kind="restore"
        )["valid"] is False
    finally:
        splice.close()
