# Data storage and backup

Default locations:

```text
~/.aetnamem/memories.db
~/.aetnamem/control-plane.json
~/.aetnamem/migrations/<migration-id>/
```

The migration directory contains the isolated OpenClaw mirror, source snapshots, restore material and control evidence. Dashboard service metadata and its protected access key are separate from memory; removing the dashboard daemon does not delete memory.

Before copying a SQLite database, stop active writers or use SQLite's online backup mechanism. Copy the database together with `-wal` and `-shm` only when following SQLite's documented procedure. After restoration, run:

```bash
aetnamem verify /path/to/memories.db --incremental
aetnamem control status
```

Protect backups as personal data. A deletion from the live database does not erase independent backups; retention and backup expiry remain deployment responsibilities.
