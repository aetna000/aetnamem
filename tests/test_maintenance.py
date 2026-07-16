from pathlib import Path

from aetnamem import Memory
from aetnamem.maintenance import GraphMaintenanceWorker


def test_graph_maintenance_uses_independent_connection_and_archives(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    memory = Memory(database)
    memory.remember("u1", "My preferred airport is SEA.")
    memory.remember("u1", "My preferred airport is LAX.")
    memory.store._conn.execute(
        "UPDATE edges SET created_at = '2000-01-01T00:00:00+00:00' "
        "WHERE status = 'superseded'"
    )
    memory.close()

    worker = GraphMaintenanceWorker(
        database,
        interval_seconds=60,
        archive_root=tmp_path / "archive",
        archive_after_days=1,
    )
    [report] = worker.run_once()

    assert report["archive"]["archived_edges"] == 1
    reopened = Memory(database)
    assert len(reopened.read_graph_archive("u1")) == 1
    verification = reopened.store.verify_audit_chain_incremental("u1")
    assert verification["valid"] is True
    assert verification["verified_events"] == 0
    reopened.close()
