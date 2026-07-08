from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex


class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._fts_enabled = False
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def reset_subject(self, subject_id: str) -> None:
        with self._conn:
            if self._fts_enabled:
                self._conn.execute("DELETE FROM records_fts WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM records WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM episodes WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM retrieval_events WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM audit_log WHERE subject_id = ?", (subject_id,))

    def insert_episode(
        self,
        *,
        subject_id: str,
        session_id: str | None,
        turn_id: str | None,
        message: str,
        source_type: str,
        raw: dict[str, Any] | None = None,
    ) -> str:
        episode_id = _new_id("ep")
        created_at = utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO episodes (
                  id, subject_id, session_id, turn_id, message, source_type,
                  created_at, raw
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    subject_id,
                    session_id,
                    turn_id,
                    message,
                    source_type,
                    created_at,
                    _json(raw or {}),
                ),
            )
        return episode_id

    def insert_record(
        self,
        *,
        subject_id: str,
        content: str,
        source_type: str,
        trust_tier: str,
        source_session_id: str | None,
        source_turn_id: str | None,
        episode_id: str | None,
        confidence: float | None,
        scope: str,
        status: str = "active",
        supersedes_id: str | None = None,
        fact_key: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> str:
        record_id = _new_id("rec")
        created_at = utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO records (
                  id, subject_id, content, source_type, trust_tier,
                  source_session_id, source_turn_id, episode_id, created_at,
                  updated_at, deleted_at, confidence, scope, status,
                  supersedes_id, fact_key, raw
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    subject_id,
                    content,
                    source_type,
                    trust_tier,
                    source_session_id,
                    source_turn_id,
                    episode_id,
                    created_at,
                    confidence,
                    scope,
                    status,
                    supersedes_id,
                    fact_key,
                    _json(raw or {}),
                ),
            )
            if status == "active":
                self._upsert_fts(record_id, subject_id, content)
        return record_id

    def get_record(self, subject_id: str, record_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM records WHERE subject_id = ? AND id = ?",
            (subject_id, record_id),
        ).fetchone()
        return _record_from_row(row) if row else None

    def promote_record(
        self,
        *,
        subject_id: str,
        record_id: str,
        trust_tier: str = "user_confirmed",
    ) -> dict[str, Any] | None:
        """Activate a quarantined record. Returns the record, or None if it
        was not quarantined (promotion is only meaningful from quarantine)."""
        updated_at = utc_now()
        with self._conn:
            row = self._conn.execute(
                """
                SELECT * FROM records
                WHERE subject_id = ? AND id = ? AND status = 'quarantined'
                """,
                (subject_id, record_id),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                """
                UPDATE records
                SET status = 'active', trust_tier = ?, updated_at = ?
                WHERE subject_id = ? AND id = ?
                """,
                (trust_tier, updated_at, subject_id, record_id),
            )
            self._upsert_fts(record_id, subject_id, row["content"])
        return self.get_record(subject_id, record_id)

    def supersede_records(
        self,
        *,
        subject_id: str,
        record_ids: list[str],
        superseded_by_id: str,
    ) -> None:
        if not record_ids:
            return
        updated_at = utc_now()
        with self._conn:
            for record_id in record_ids:
                row = self._conn.execute(
                    """
                    SELECT raw FROM records
                    WHERE subject_id = ? AND id = ? AND status = 'active'
                    """,
                    (subject_id, record_id),
                ).fetchone()
                if row is None:
                    continue
                raw = _load_json(row["raw"], {})
                raw["superseded_by_id"] = superseded_by_id
                self._conn.execute(
                    """
                    UPDATE records
                    SET status = 'superseded', updated_at = ?, raw = ?
                    WHERE subject_id = ? AND id = ? AND status = 'active'
                    """,
                    (updated_at, _json(raw), subject_id, record_id),
                )
                self._delete_fts(record_id)

    def tombstone_records(
        self, *, subject_id: str, record_ids: list[str]
    ) -> tuple[list[str], list[str]]:
        """Tombstone + purge records; returns (record_ids, episode_ids) purged.

        Applies to active and quarantined records alike — deletion must also
        empty the quarantine. Purging clears content *and* fact_key, since the
        fact slot name itself can reveal what was stored.
        """
        if not record_ids:
            return [], []
        deleted_at = utc_now()
        changed: list[str] = []
        with self._conn:
            for record_id in record_ids:
                row = self._conn.execute(
                    """
                    SELECT id FROM records
                    WHERE subject_id = ? AND id = ?
                      AND status IN ('active', 'quarantined')
                    """,
                    (subject_id, record_id),
                ).fetchone()
                if row is None:
                    continue
                self._conn.execute(
                    """
                    UPDATE records
                    SET status = 'tombstoned',
                        content = '',
                        fact_key = NULL,
                        updated_at = ?,
                        deleted_at = ?,
                        raw = ?
                    WHERE subject_id = ? AND id = ?
                    """,
                    (deleted_at, deleted_at, _json({"purged": True}), subject_id, record_id),
                )
                self._delete_fts(record_id)
                changed.append(record_id)
            episode_ids: list[str] = []
            if changed:
                placeholders = ",".join("?" for _ in changed)
                episode_rows = self._conn.execute(
                    f"""
                    SELECT DISTINCT episode_id FROM records
                    WHERE subject_id = ? AND id IN ({placeholders})
                      AND episode_id IS NOT NULL
                    """,
                    (subject_id, *changed),
                ).fetchall()
                episode_ids = [row["episode_id"] for row in episode_rows]
            if episode_ids:
                placeholders = ",".join("?" for _ in episode_ids)
                self._conn.execute(
                    f"""
                    UPDATE episodes
                    SET message = '[purged]', raw = ?
                    WHERE subject_id = ? AND id IN ({placeholders})
                    """,
                    (_json({"purged": True}), subject_id, *episode_ids),
                )
        return changed, episode_ids

    def list_records(
        self,
        subject_id: str,
        *,
        statuses: tuple[str, ...] | None = ("active",),
    ) -> list[dict[str, Any]]:
        params: list[Any] = [subject_id]
        status_clause = ""
        if statuses is not None:
            status_clause = f"AND status IN ({','.join('?' for _ in statuses)})"
            params.extend(statuses)
        rows = self._conn.execute(
            f"""
            SELECT * FROM records
            WHERE subject_id = ? {status_clause}
            ORDER BY created_at ASC, id ASC
            """,
            params,
        ).fetchall()
        return [_record_from_row(row) for row in rows]

    def list_episodes(self, subject_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM episodes
            WHERE subject_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (subject_id,),
        ).fetchall()
        return [_episode_from_row(row) for row in rows]

    def insert_retrieval_event(
        self,
        *,
        subject_id: str,
        session_id: str | None,
        query: str,
        query_sha256: str,
        candidates: list[dict[str, Any]],
        returned_ids: list[str],
    ) -> str:
        event_id = _new_id("ret")
        created_at = utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO retrieval_events (
                  id, subject_id, session_id, query, query_sha256, candidates,
                  returned_ids, created_at, raw
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    subject_id,
                    session_id,
                    query,
                    query_sha256,
                    _json(candidates),
                    _json(returned_ids),
                    created_at,
                    _json({}),
                ),
            )
        return event_id

    def list_retrieval_events(
        self,
        subject_id: str,
        *,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [subject_id]
        session_clause = ""
        if session_id is not None:
            session_clause = "AND session_id = ?"
            params.append(session_id)
        rows = self._conn.execute(
            f"""
            SELECT * FROM retrieval_events
            WHERE subject_id = ? {session_clause}
            ORDER BY created_at ASC, id ASC
            """,
            params,
        ).fetchall()
        return [_retrieval_from_row(row) for row in rows]

    def append_audit_event(
        self,
        *,
        subject_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
        session_id: str | None = None,
        turn_id: str | None = None,
        record_id: str | None = None,
    ) -> str:
        event_id = _new_id("aud")
        created_at = utc_now()
        payload_json = _json(payload or {})
        previous = self._conn.execute(
            """
            SELECT event_hash FROM audit_log
            WHERE subject_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (subject_id,),
        ).fetchone()
        prev_hash = previous["event_hash"] if previous else None
        event_hash = _event_hash(
            {
                "event_id": event_id,
                "subject_id": subject_id,
                "event_type": event_type,
                "created_at": created_at,
                "actor": actor,
                "session_id": session_id,
                "turn_id": turn_id,
                "record_id": record_id,
                "payload": json.loads(payload_json),
                "prev_hash": prev_hash,
            }
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO audit_log (
                  event_id, subject_id, event_type, created_at, actor,
                  session_id, turn_id, record_id, payload, prev_hash, event_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    subject_id,
                    event_type,
                    created_at,
                    actor,
                    session_id,
                    turn_id,
                    record_id,
                    payload_json,
                    prev_hash,
                    event_hash,
                ),
            )
        return event_id

    def fts_match_scores(self, subject_id: str, terms: list[str]) -> dict[str, float]:
        """Full-text relevance for active records, higher is better.

        Returns {} when FTS5 is unavailable or the query has no usable terms,
        in which case callers fall back to a lexical overlap scorer.
        """
        if not self._fts_enabled or not terms:
            return {}
        match_expr = " OR ".join(
            '"' + term.replace('"', "") + '"' for term in terms if term.strip()
        )
        if not match_expr:
            return {}
        try:
            rows = self._conn.execute(
                """
                SELECT record_id, bm25(records_fts) AS rank
                FROM records_fts
                WHERE records_fts MATCH ? AND subject_id = ?
                """,
                (match_expr, subject_id),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        # SQLite bm25() is lower-is-better (usually negative); negate it.
        return {row["record_id"]: -float(row["rank"]) for row in rows}

    def list_audit_events(self, subject_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM audit_log
            WHERE subject_id = ?
            ORDER BY sequence ASC
            """,
            (subject_id,),
        ).fetchall()
        return [_audit_from_row(row) for row in rows]

    def get_audit_event(self, subject_id: str, event_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM audit_log WHERE subject_id = ? AND event_id = ?",
            (subject_id, event_id),
        ).fetchone()
        return _audit_from_row(row) if row else None

    def event_at_sequence(self, subject_id: str, sequence: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM audit_log WHERE subject_id = ? AND sequence = ?",
            (subject_id, sequence),
        ).fetchone()
        return _audit_from_row(row) if row else None

    def chain_heads(self) -> dict[str, dict[str, Any]]:
        """Latest audit event per subject: {subject_id: {sequence, event_hash,
        event_count}}. This is what a checkpoint anchors."""
        rows = self._conn.execute(
            """
            SELECT a.subject_id, a.sequence, a.event_hash,
                   (SELECT COUNT(*) FROM audit_log b
                    WHERE b.subject_id = a.subject_id) AS event_count
            FROM audit_log a
            WHERE a.sequence = (
              SELECT MAX(c.sequence) FROM audit_log c
              WHERE c.subject_id = a.subject_id
            )
            """
        ).fetchall()
        return {
            row["subject_id"]: {
                "sequence": row["sequence"],
                "event_hash": row["event_hash"],
                "event_count": row["event_count"],
            }
            for row in rows
        }

    def verify_audit_chain(self, subject_id: str) -> bool:
        previous_hash: str | None = None
        for event in self.list_audit_events(subject_id):
            expected = _event_hash(
                {
                    "event_id": event["event_id"],
                    "subject_id": event["subject_id"],
                    "event_type": event["event_type"],
                    "created_at": event["created_at"],
                    "actor": event["actor"],
                    "session_id": event["session_id"],
                    "turn_id": event["turn_id"],
                    "record_id": event["record_id"],
                    "payload": event["payload"],
                    "prev_hash": previous_hash,
                }
            )
            if event["prev_hash"] != previous_hash or event["event_hash"] != expected:
                return False
            previous_hash = event["event_hash"]
        return True

    def _migrate(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  session_id TEXT,
                  turn_id TEXT,
                  message TEXT NOT NULL,
                  source_type TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  raw TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS records (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  content TEXT NOT NULL,
                  source_type TEXT NOT NULL,
                  trust_tier TEXT NOT NULL,
                  source_session_id TEXT,
                  source_turn_id TEXT,
                  episode_id TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT,
                  deleted_at TEXT,
                  confidence REAL,
                  scope TEXT NOT NULL,
                  status TEXT NOT NULL CHECK (
                    status IN ('active', 'superseded', 'quarantined', 'tombstoned')
                  ),
                  supersedes_id TEXT,
                  fact_key TEXT,
                  raw TEXT NOT NULL DEFAULT '{}',
                  FOREIGN KEY (episode_id) REFERENCES episodes(id),
                  FOREIGN KEY (supersedes_id) REFERENCES records(id)
                );

                CREATE INDEX IF NOT EXISTS idx_records_subject_status
                  ON records(subject_id, status);

                CREATE INDEX IF NOT EXISTS idx_records_subject_key
                  ON records(subject_id, fact_key, status);

                CREATE TABLE IF NOT EXISTS retrieval_events (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  session_id TEXT,
                  query TEXT NOT NULL,
                  query_sha256 TEXT,
                  candidates TEXT NOT NULL DEFAULT '[]',
                  returned_ids TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL,
                  raw TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_id TEXT NOT NULL UNIQUE,
                  subject_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  session_id TEXT,
                  turn_id TEXT,
                  record_id TEXT,
                  payload TEXT NOT NULL DEFAULT '{}',
                  prev_hash TEXT,
                  event_hash TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_subject_sequence
                  ON audit_log(subject_id, sequence);
                """
            )
            self._ensure_column("records", "fact_key", "TEXT")
            self._ensure_column("retrieval_events", "query_sha256", "TEXT")
            self._migrate_fts()

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _migrate_fts(self) -> None:
        try:
            existing = self._conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'records_fts'"
            ).fetchone()
            if existing is not None and "porter" not in (existing["sql"] or ""):
                self._conn.execute("DROP TABLE records_fts")
                existing = None
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
                USING fts5(
                  record_id UNINDEXED, subject_id UNINDEXED, content,
                  tokenize='porter unicode61'
                )
                """
            )
            self._fts_enabled = True
            if existing is None:
                self._rebuild_fts()
        except sqlite3.OperationalError:
            self._fts_enabled = False

    def _rebuild_fts(self) -> None:
        self._conn.execute("DELETE FROM records_fts")
        self._conn.execute(
            """
            INSERT INTO records_fts(record_id, subject_id, content)
            SELECT id, subject_id, content FROM records WHERE status = 'active'
            """
        )

    def _upsert_fts(self, record_id: str, subject_id: str, content: str) -> None:
        if not self._fts_enabled:
            return
        self._conn.execute("DELETE FROM records_fts WHERE record_id = ?", (record_id,))
        self._conn.execute(
            "INSERT INTO records_fts(record_id, subject_id, content) VALUES (?, ?, ?)",
            (record_id, subject_id, content),
        )

    def _delete_fts(self, record_id: str) -> None:
        if self._fts_enabled:
            self._conn.execute("DELETE FROM records_fts WHERE record_id = ?", (record_id,))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return canonical_json(value)


def _load_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _event_hash(event: dict[str, Any]) -> str:
    return sha256_hex(_json(event))


def _record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = _load_json(row["raw"], {})
    return {
        "id": row["id"],
        "memory_id": row["id"],
        "framework": "aetnamem",
        "subject_id": row["subject_id"],
        "subject_id_hash": f"plain:{row['subject_id']}",
        "tenant_id_hash": None,
        "content": row["content"],
        "source_type": row["source_type"],
        "trust_tier": row["trust_tier"],
        "source_session_id": row["source_session_id"],
        "source_turn_id": row["source_turn_id"],
        "episode_id": row["episode_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
        "confidence": row["confidence"],
        "scope": row["scope"],
        "status": row["status"],
        "supersedes_id": row["supersedes_id"],
        "fact_key": row["fact_key"],
        "raw": raw,
    }


def _episode_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "subject_id": row["subject_id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "message": row["message"],
        "source_type": row["source_type"],
        "created_at": row["created_at"],
        "raw": _load_json(row["raw"], {}),
    }


def _retrieval_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "subject_id": row["subject_id"],
        "session_id": row["session_id"],
        "query": row["query"],
        "query_sha256": row["query_sha256"],
        "candidates": _load_json(row["candidates"], []),
        "returned_ids": _load_json(row["returned_ids"], []),
        "memory_ids": _load_json(row["returned_ids"], []),
        "created_at": row["created_at"],
        "raw": _load_json(row["raw"], {}),
    }


def _audit_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "sequence": row["sequence"],
        "event_id": row["event_id"],
        "subject_id": row["subject_id"],
        "event_type": row["event_type"],
        "created_at": row["created_at"],
        "actor": row["actor"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "record_id": row["record_id"],
        "payload": _load_json(row["payload"], {}),
        "prev_hash": row["prev_hash"],
        "event_hash": row["event_hash"],
    }
