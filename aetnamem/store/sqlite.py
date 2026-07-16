from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.core.policy import normalize_content


class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode keeps transaction ownership explicit. Public write
        # methods enter ``transaction()``; an outer engine operation can wrap
        # several of them in one atomic unit without an inner method committing
        # early through sqlite3.Connection.__exit__.
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self._fts_enabled = False
        self._graph_fts_enabled = False
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            try:
                self._conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError as exc:
                # Concurrent first-open calls can race while one connection
                # changes the persistent journal mode. BEGIN IMMEDIATE still
                # provides correct serialization; the winning connection has
                # already made WAL persistent for subsequent opens.
                if "locked" not in str(exc).lower():
                    raise
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator["SQLiteStore"]:
        """Join or open one explicit SQLite unit of work.

        The outermost scope owns BEGIN/COMMIT/ROLLBACK. Nested store calls only
        join it, which is what makes a semantic mutation and its audit event
        atomic. ``BEGIN IMMEDIATE`` is the write default: it also serializes
        the per-subject audit-head read with the following append so two
        connections cannot derive competing events from the same head.
        """
        if self._transaction_depth:
            self._transaction_depth += 1
            try:
                yield self
            finally:
                self._transaction_depth -= 1
            return

        self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        self._transaction_depth = 1
        try:
            yield self
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            self._transaction_depth = 0

    def reset_subject(self, subject_id: str) -> None:
        with self.transaction():
            action_table = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'action_transactions'"
            ).fetchone()
            if action_table is not None:
                self._conn.execute(
                    "DELETE FROM action_transactions WHERE subject_id = ?", (subject_id,)
                )
            if self._fts_enabled:
                self._delete_records_fts_subject(subject_id)
            if self._graph_fts_enabled:
                self._delete_graph_fts_subject(subject_id)
            self._conn.execute("DELETE FROM graph_merge_proposals WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM graph_archive_members WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM graph_archive_partitions WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM edges WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM entity_aliases WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM entities WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM records WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM episodes WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM retrieval_events WHERE subject_id = ?", (subject_id,))
            self._conn.execute("DELETE FROM audit_verification_state WHERE subject_id = ?", (subject_id,))
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
        with self.transaction():
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
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO records (
                  id, subject_id, content, content_normalized, source_type, trust_tier,
                  source_session_id, source_turn_id, episode_id, created_at,
                  updated_at, deleted_at, confidence, scope, status,
                  supersedes_id, fact_key, raw
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    subject_id,
                    content,
                    normalize_content(content),
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

    def find_duplicate_record(
        self,
        subject_id: str,
        content: str,
        *,
        statuses: tuple[str, ...],
    ) -> dict[str, Any] | None:
        normalized = normalize_content(content)
        if not normalized or not statuses:
            return None
        placeholders = ",".join("?" for _ in statuses)
        row = self._conn.execute(
            f"""
            SELECT * FROM records
            WHERE subject_id = ? AND content_normalized = ?
              AND status IN ({placeholders})
            ORDER BY created_at, id
            LIMIT 1
            """,
            (subject_id, normalized, *statuses),
        ).fetchone()
        return _record_from_row(row) if row else None

    def active_records_for_fact_key(
        self,
        subject_id: str,
        fact_key: str | None,
        *,
        exclude_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not fact_key:
            return []
        params: list[Any] = [subject_id, fact_key]
        exclusion = ""
        if exclude_id is not None:
            exclusion = "AND id != ?"
            params.append(exclude_id)
        rows = self._conn.execute(
            f"""
            SELECT * FROM records
            WHERE subject_id = ? AND fact_key = ? AND status = 'active'
              {exclusion}
            ORDER BY created_at, id
            """,
            params,
        ).fetchall()
        return [_record_from_row(row) for row in rows]

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
        with self.transaction():
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
        with self.transaction():
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

        Applies to active, quarantined, and superseded records alike. Purging
        clears content *and* fact_key, since the fact slot name itself can
        reveal what was stored.
        """
        if not record_ids:
            return [], []
        deleted_at = utc_now()
        changed: list[str] = []
        with self.transaction():
            for record_id in record_ids:
                row = self._conn.execute(
                    """
                    SELECT id FROM records
                    WHERE subject_id = ? AND id = ?
                      AND status IN ('active', 'quarantined', 'superseded')
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
                        content_normalized = NULL,
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

    def recall_candidates(
        self,
        subject_id: str,
        terms: list[str],
        *,
        limit: int = 200,
    ) -> tuple[list[dict[str, Any]], dict[str, float]]:
        """Bound recall work to FTS matches plus the most recent actives."""
        limit = max(1, min(int(limit), 2000))
        scores = self.fts_match_scores(subject_id, terms, limit=limit)
        matched_ids = list(scores)
        rows: list[sqlite3.Row] = []
        if matched_ids:
            placeholders = ",".join("?" for _ in matched_ids)
            rows.extend(
                self._conn.execute(
                    f"SELECT * FROM records WHERE subject_id = ? AND status = 'active' "
                    f"AND id IN ({placeholders})",
                    (subject_id, *matched_ids),
                ).fetchall()
            )
        seen = {str(row["id"]) for row in rows}
        if len(rows) < limit:
            recent = self._conn.execute(
                """
                SELECT * FROM records
                WHERE subject_id = ? AND status = 'active'
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (subject_id, limit + len(seen)),
            ).fetchall()
            for row in recent:
                if str(row["id"]) not in seen:
                    rows.append(row)
                    seen.add(str(row["id"]))
                    if len(rows) >= limit:
                        break
        records = [_record_from_row(row) for row in rows]
        records.sort(key=lambda record: (record["created_at"], record["id"]))
        return records, scores

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
        raw: dict[str, Any] | None = None,
    ) -> str:
        event_id = _new_id("ret")
        created_at = utc_now()
        with self.transaction():
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
                    _json(raw or {}),
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
        with self.transaction(immediate=True):
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

    def fts_match_scores(
        self, subject_id: str, terms: list[str], *, limit: int | None = None
    ) -> dict[str, float]:
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
            sql = """
                SELECT record_id, bm25(records_fts) AS rank
                FROM records_fts
                WHERE records_fts MATCH ? AND subject_id = ?
                ORDER BY bm25(records_fts), record_id
                """
            params: tuple[Any, ...] = (match_expr, subject_id)
            if limit is not None:
                sql += " LIMIT ?"
                params = (*params, max(1, int(limit)))
            rows = self._conn.execute(sql, params).fetchall()
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

    def verify_audit_chain_incremental(
        self, subject_id: str, *, reset: bool = False
    ) -> dict[str, Any]:
        """Verify only the suffix after a locally cached, hash-checked head.

        This is a performance cache, not an external trust anchor. The cached
        event is re-read and hash-compared on every run; externally anchored
        checkpoints remain necessary against whole-database replacement.
        """
        if reset:
            with self.transaction():
                self._conn.execute(
                    "DELETE FROM audit_verification_state WHERE subject_id = ?",
                    (subject_id,),
                )
        state = None if reset else self._conn.execute(
            "SELECT * FROM audit_verification_state WHERE subject_id = ?",
            (subject_id,),
        ).fetchone()
        previous_hash: str | None = None
        start_sequence = 0
        if state is not None:
            anchor = self.event_at_sequence(subject_id, int(state["sequence"]))
            anchor_expected = (
                _event_hash(
                    {
                        "event_id": anchor["event_id"],
                        "subject_id": anchor["subject_id"],
                        "event_type": anchor["event_type"],
                        "created_at": anchor["created_at"],
                        "actor": anchor["actor"],
                        "session_id": anchor["session_id"],
                        "turn_id": anchor["turn_id"],
                        "record_id": anchor["record_id"],
                        "payload": anchor["payload"],
                        "prev_hash": anchor["prev_hash"],
                    }
                )
                if anchor is not None
                else None
            )
            if (
                anchor is None
                or anchor["event_hash"] != state["event_hash"]
                or anchor_expected != anchor["event_hash"]
            ):
                return {
                    "valid": False,
                    "cached_from_sequence": int(state["sequence"]),
                    "verified_events": 0,
                    "failure": "cached verification anchor is missing or changed",
                }
            start_sequence = int(state["sequence"])
            previous_hash = str(state["event_hash"])

        rows = self._conn.execute(
            """
            SELECT * FROM audit_log
            WHERE subject_id = ? AND sequence > ?
            ORDER BY sequence ASC
            """,
            (subject_id, start_sequence),
        ).fetchall()
        verified = 0
        last_sequence = start_sequence
        for row in rows:
            event = _audit_from_row(row)
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
                return {
                    "valid": False,
                    "cached_from_sequence": start_sequence,
                    "verified_events": verified,
                    "failure": f"audit mismatch at sequence {event['sequence']}",
                }
            previous_hash = str(event["event_hash"])
            last_sequence = int(event["sequence"])
            verified += 1

        if last_sequence:
            with self.transaction():
                self._conn.execute(
                    """
                    INSERT INTO audit_verification_state (
                      subject_id, sequence, event_hash, verified_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(subject_id) DO UPDATE SET
                      sequence = excluded.sequence,
                      event_hash = excluded.event_hash,
                      verified_at = excluded.verified_at
                    """,
                    (subject_id, last_sequence, previous_hash, utc_now()),
                )
        return {
            "valid": True,
            "cached_from_sequence": start_sequence,
            "verified_through_sequence": last_sequence,
            "verified_events": verified,
            "failure": None,
        }

    def subject_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT subject_id FROM audit_log ORDER BY subject_id"
        ).fetchall()
        return [str(row["subject_id"]) for row in rows]

    def optimize(self) -> None:
        self._conn.execute("PRAGMA optimize")

    def _migrate(self) -> None:
        with self.transaction():
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
                  content_normalized TEXT,
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

                CREATE TABLE IF NOT EXISTS records_fts_map (
                  record_id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  fts_rowid INTEGER NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_records_fts_map_subject
                  ON records_fts_map(subject_id);

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

                CREATE TABLE IF NOT EXISTS entities (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  canonical TEXT NOT NULL,
                  normalized TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL CHECK (
                    status IN ('active', 'quarantined', 'merged', 'tombstoned')
                  ),
                  merged_into TEXT,
                  source_record TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT,
                  UNIQUE (subject_id, normalized, kind),
                  FOREIGN KEY (merged_into) REFERENCES entities(id),
                  FOREIGN KEY (source_record) REFERENCES records(id)
                );

                CREATE INDEX IF NOT EXISTS idx_entities_subject_status
                  ON entities(subject_id, status, kind);

                CREATE TABLE IF NOT EXISTS entity_aliases (
                  id TEXT PRIMARY KEY,
                  entity_id TEXT NOT NULL,
                  subject_id TEXT NOT NULL,
                  surface TEXT NOT NULL,
                  normalized TEXT NOT NULL,
                  source_record TEXT,
                  trust_tier TEXT NOT NULL,
                  status TEXT NOT NULL CHECK (
                    status IN ('active', 'quarantined', 'superseded', 'tombstoned')
                  ),
                  created_at TEXT NOT NULL,
                  UNIQUE (subject_id, entity_id, normalized, source_record),
                  FOREIGN KEY (entity_id) REFERENCES entities(id),
                  FOREIGN KEY (source_record) REFERENCES records(id)
                );

                CREATE INDEX IF NOT EXISTS idx_aliases_subject_surface
                  ON entity_aliases(subject_id, normalized, status);

                CREATE TABLE IF NOT EXISTS edges (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  src_entity TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  relation_label TEXT NOT NULL,
                  dst_entity TEXT,
                  dst_value TEXT,
                  record_id TEXT NOT NULL,
                  trust_tier TEXT NOT NULL,
                  confidence REAL,
                  status TEXT NOT NULL CHECK (
                    status IN ('active', 'superseded', 'quarantined', 'tombstoned')
                  ),
                  supersedes_id TEXT,
                  extractor_version TEXT NOT NULL DEFAULT 'graph-rules-v1',
                  created_at TEXT NOT NULL,
                  updated_at TEXT,
                  UNIQUE (subject_id, record_id),
                  FOREIGN KEY (record_id) REFERENCES records(id),
                  FOREIGN KEY (src_entity) REFERENCES entities(id),
                  FOREIGN KEY (dst_entity) REFERENCES entities(id),
                  FOREIGN KEY (supersedes_id) REFERENCES edges(id)
                );

                CREATE INDEX IF NOT EXISTS idx_edges_src
                  ON edges(subject_id, src_entity, relation, status);

                CREATE INDEX IF NOT EXISTS idx_edges_dst
                  ON edges(subject_id, dst_entity, status);

                CREATE INDEX IF NOT EXISTS idx_edges_record
                  ON edges(subject_id, record_id, status);

                CREATE TABLE IF NOT EXISTS graph_fts_map (
                  object_type TEXT NOT NULL,
                  object_id TEXT NOT NULL,
                  subject_id TEXT NOT NULL,
                  fts_rowid INTEGER NOT NULL UNIQUE,
                  PRIMARY KEY (object_type, object_id)
                );

                CREATE INDEX IF NOT EXISTS idx_graph_fts_map_subject
                  ON graph_fts_map(subject_id);

                CREATE TABLE IF NOT EXISTS graph_merge_proposals (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  left_entity TEXT NOT NULL,
                  right_entity TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  reason TEXT NOT NULL,
                  evidence_record_ids TEXT NOT NULL DEFAULT '[]',
                  status TEXT NOT NULL CHECK (
                    status IN ('pending', 'approved', 'rejected', 'reverted')
                  ),
                  winner_entity TEXT,
                  proposed_at TEXT NOT NULL,
                  decided_at TEXT,
                  decided_by TEXT,
                  UNIQUE (subject_id, left_entity, right_entity),
                  FOREIGN KEY (left_entity) REFERENCES entities(id),
                  FOREIGN KEY (right_entity) REFERENCES entities(id),
                  FOREIGN KEY (winner_entity) REFERENCES entities(id)
                );

                CREATE INDEX IF NOT EXISTS idx_graph_merge_status
                  ON graph_merge_proposals(subject_id, status, proposed_at);

                CREATE TABLE IF NOT EXISTS graph_archive_partitions (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  partition_year INTEGER NOT NULL,
                  path TEXT NOT NULL,
                  cutoff TEXT NOT NULL,
                  row_count INTEGER NOT NULL,
                  content_sha256 TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE (subject_id, partition_year, path)
                );

                CREATE INDEX IF NOT EXISTS idx_graph_archive_subject
                  ON graph_archive_partitions(subject_id, partition_year);

                CREATE TABLE IF NOT EXISTS graph_archive_members (
                  subject_id TEXT NOT NULL,
                  object_type TEXT NOT NULL,
                  object_id TEXT NOT NULL,
                  source_record_id TEXT NOT NULL,
                  partition_id TEXT NOT NULL,
                  archived_at TEXT NOT NULL,
                  PRIMARY KEY (object_type, object_id),
                  FOREIGN KEY (partition_id) REFERENCES graph_archive_partitions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_graph_archive_record
                  ON graph_archive_members(subject_id, source_record_id);

                CREATE TABLE IF NOT EXISTS audit_verification_state (
                  subject_id TEXT PRIMARY KEY,
                  sequence INTEGER NOT NULL,
                  event_hash TEXT NOT NULL,
                  verified_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS invalidate_audit_verification_update
                AFTER UPDATE ON audit_log
                BEGIN
                  DELETE FROM audit_verification_state
                  WHERE subject_id IN (OLD.subject_id, NEW.subject_id);
                END;

                CREATE TRIGGER IF NOT EXISTS invalidate_audit_verification_delete
                AFTER DELETE ON audit_log
                BEGIN
                  DELETE FROM audit_verification_state
                  WHERE subject_id = OLD.subject_id;
                END;
                """
            )
            self._ensure_column("records", "fact_key", "TEXT")
            self._ensure_column("records", "content_normalized", "TEXT")
            self._ensure_column("retrieval_events", "query_sha256", "TEXT")
            self._ensure_column(
                "edges", "extractor_version", "TEXT NOT NULL DEFAULT 'graph-rules-v1'"
            )
            self._migrate_alias_status()
            self._backfill_record_normalization()
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_records_subject_normalized
                ON records(subject_id, status, content_normalized)
                """
            )
            self._migrate_fts()
            self._migrate_graph_fts()

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _backfill_record_normalization(self) -> None:
        rows = self._conn.execute(
            """
            SELECT id, content FROM records
            WHERE content_normalized IS NULL AND status != 'tombstoned'
            """
        ).fetchall()
        for row in rows:
            self._conn.execute(
                "UPDATE records SET content_normalized = ? WHERE id = ?",
                (normalize_content(str(row["content"])), row["id"]),
            )

    def _migrate_alias_status(self) -> None:
        schema = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'entity_aliases'"
        ).fetchone()
        if schema is None or "'superseded'" in str(schema["sql"]):
            return
        self._conn.execute("ALTER TABLE entity_aliases RENAME TO entity_aliases_legacy")
        self._conn.execute(
            """
            CREATE TABLE entity_aliases (
              id TEXT PRIMARY KEY,
              entity_id TEXT NOT NULL,
              subject_id TEXT NOT NULL,
              surface TEXT NOT NULL,
              normalized TEXT NOT NULL,
              source_record TEXT,
              trust_tier TEXT NOT NULL,
              status TEXT NOT NULL CHECK (
                status IN ('active', 'quarantined', 'superseded', 'tombstoned')
              ),
              created_at TEXT NOT NULL,
              UNIQUE (subject_id, entity_id, normalized, source_record),
              FOREIGN KEY (entity_id) REFERENCES entities(id),
              FOREIGN KEY (source_record) REFERENCES records(id)
            )
            """
        )
        self._conn.execute(
            """
            INSERT INTO entity_aliases (
              id, entity_id, subject_id, surface, normalized, source_record,
              trust_tier, status, created_at
            )
            SELECT id, entity_id, subject_id, surface, normalized, source_record,
                   trust_tier, status, created_at
            FROM entity_aliases_legacy
            """
        )
        self._conn.execute("DROP TABLE entity_aliases_legacy")
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_aliases_subject_surface
            ON entity_aliases(subject_id, normalized, status)
            """
        )

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
            elif self._conn.execute(
                "SELECT 1 FROM records_fts LIMIT 1"
            ).fetchone() is not None and self._conn.execute(
                "SELECT 1 FROM records_fts_map LIMIT 1"
            ).fetchone() is None:
                self._rebuild_fts()
        except sqlite3.OperationalError:
            self._fts_enabled = False

    def _migrate_graph_fts(self) -> None:
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS graph_fts
                USING fts5(
                  object_type UNINDEXED, object_id UNINDEXED,
                  subject_id UNINDEXED, text,
                  tokenize='porter unicode61'
                )
                """
            )
            self._graph_fts_enabled = True
            if self._conn.execute(
                "SELECT 1 FROM graph_fts LIMIT 1"
            ).fetchone() is not None and self._conn.execute(
                "SELECT 1 FROM graph_fts_map LIMIT 1"
            ).fetchone() is None:
                self._conn.execute(
                    """
                    INSERT INTO graph_fts_map (
                      object_type, object_id, subject_id, fts_rowid
                    )
                    SELECT object_type, object_id, subject_id, rowid
                    FROM graph_fts
                    """
                )
        except sqlite3.OperationalError:
            self._graph_fts_enabled = False

    def _rebuild_fts(self) -> None:
        self._conn.execute("DELETE FROM records_fts_map")
        self._conn.execute("DELETE FROM records_fts")
        self._conn.execute(
            """
            INSERT INTO records_fts(record_id, subject_id, content)
            SELECT id, subject_id, content FROM records WHERE status = 'active'
            """
        )
        self._conn.execute(
            """
            INSERT INTO records_fts_map(record_id, subject_id, fts_rowid)
            SELECT record_id, subject_id, rowid FROM records_fts
            """
        )

    def _upsert_fts(self, record_id: str, subject_id: str, content: str) -> None:
        if not self._fts_enabled:
            return
        mapped = self._conn.execute(
            "SELECT fts_rowid FROM records_fts_map WHERE record_id = ?", (record_id,)
        ).fetchone()
        if mapped is None:
            cursor = self._conn.execute(
                "INSERT INTO records_fts(record_id, subject_id, content) VALUES (?, ?, ?)",
                (record_id, subject_id, content),
            )
            self._conn.execute(
                "INSERT INTO records_fts_map(record_id, subject_id, fts_rowid) VALUES (?, ?, ?)",
                (record_id, subject_id, cursor.lastrowid),
            )
            return
        rowid = int(mapped["fts_rowid"])
        self._conn.execute("DELETE FROM records_fts WHERE rowid = ?", (rowid,))
        self._conn.execute(
            "INSERT INTO records_fts(rowid, record_id, subject_id, content) VALUES (?, ?, ?, ?)",
            (rowid, record_id, subject_id, content),
        )
        self._conn.execute(
            "UPDATE records_fts_map SET subject_id = ? WHERE record_id = ?",
            (subject_id, record_id),
        )

    def _delete_fts(self, record_id: str) -> None:
        if not self._fts_enabled:
            return
        mapped = self._conn.execute(
            "SELECT fts_rowid FROM records_fts_map WHERE record_id = ?", (record_id,)
        ).fetchone()
        if mapped is None:
            return
        self._conn.execute(
            "DELETE FROM records_fts WHERE rowid = ?", (mapped["fts_rowid"],)
        )
        self._conn.execute(
            "DELETE FROM records_fts_map WHERE record_id = ?", (record_id,)
        )

    def _delete_records_fts_subject(self, subject_id: str) -> None:
        rows = self._conn.execute(
            "SELECT fts_rowid FROM records_fts_map WHERE subject_id = ?", (subject_id,)
        ).fetchall()
        for row in rows:
            self._conn.execute(
                "DELETE FROM records_fts WHERE rowid = ?", (row["fts_rowid"],)
            )
        self._conn.execute(
            "DELETE FROM records_fts_map WHERE subject_id = ?", (subject_id,)
        )

    def _upsert_graph_fts(
        self, object_type: str, object_id: str, subject_id: str, text: str
    ) -> None:
        if not self._graph_fts_enabled:
            return
        mapped = self._conn.execute(
            """
            SELECT fts_rowid FROM graph_fts_map
            WHERE object_type = ? AND object_id = ?
            """,
            (object_type, object_id),
        ).fetchone()
        if mapped is None:
            cursor = self._conn.execute(
                """
                INSERT INTO graph_fts(object_type, object_id, subject_id, text)
                VALUES (?, ?, ?, ?)
                """,
                (object_type, object_id, subject_id, text),
            )
            self._conn.execute(
                """
                INSERT INTO graph_fts_map (
                  object_type, object_id, subject_id, fts_rowid
                ) VALUES (?, ?, ?, ?)
                """,
                (object_type, object_id, subject_id, cursor.lastrowid),
            )
            return
        rowid = int(mapped["fts_rowid"])
        self._conn.execute("DELETE FROM graph_fts WHERE rowid = ?", (rowid,))
        self._conn.execute(
            """
            INSERT INTO graph_fts(rowid, object_type, object_id, subject_id, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rowid, object_type, object_id, subject_id, text),
        )
        self._conn.execute(
            """
            UPDATE graph_fts_map SET subject_id = ?
            WHERE object_type = ? AND object_id = ?
            """,
            (subject_id, object_type, object_id),
        )

    def _delete_graph_fts(self, object_type: str, object_id: str) -> None:
        if not self._graph_fts_enabled:
            return
        mapped = self._conn.execute(
            """
            SELECT fts_rowid FROM graph_fts_map
            WHERE object_type = ? AND object_id = ?
            """,
            (object_type, object_id),
        ).fetchone()
        if mapped is None:
            return
        self._conn.execute(
            "DELETE FROM graph_fts WHERE rowid = ?", (mapped["fts_rowid"],)
        )
        self._conn.execute(
            "DELETE FROM graph_fts_map WHERE object_type = ? AND object_id = ?",
            (object_type, object_id),
        )

    def _delete_graph_fts_subject(self, subject_id: str) -> None:
        rows = self._conn.execute(
            "SELECT object_type, object_id FROM graph_fts_map WHERE subject_id = ?",
            (subject_id,),
        ).fetchall()
        for row in rows:
            self._delete_graph_fts(str(row["object_type"]), str(row["object_id"]))


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
