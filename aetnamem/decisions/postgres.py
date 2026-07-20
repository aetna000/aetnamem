"""PostgreSQL repository for horizontally deployed decision hosts."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from typing import Any, Iterator
import uuid

from aetnamem.decisions.store import SQLiteDecisionStore
from aetnamem.store.sqlite import SQLiteStore, utc_now


class PostgresDecisionStore(SQLiteDecisionStore):
    """PostgreSQL implementation of the decision repository contract.

    A store owns one psycopg connection. Web hosts should create one per request
    or acquire one from their normal connection pool. Transactions and audit
    chain appends are safe across processes.
    """

    SCHEMA_VERSION = SQLiteDecisionStore.SCHEMA_VERSION

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection: Any | None = None,
        connect_kwargs: dict[str, Any] | None = None,
    ) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("PostgreSQL support requires a complete 'pip install aetnamem'") from exc
        if connection is not None and dsn is not None:
            raise ValueError("supply either dsn or connection, not both")
        if connection is None and not dsn:
            raise ValueError("dsn or connection is required")
        self._owns_connection = connection is None
        self._conn = connection or psycopg.connect(dsn, row_factory=dict_row, **(connect_kwargs or {}))
        self._original_autocommit = self._conn.autocommit
        self._original_row_factory = self._conn.row_factory
        self._conn.row_factory = dict_row
        self._transaction_depth = 0
        self._migrate_postgres()
        self._conn.autocommit = True

    def close(self) -> None:
        if self._owns_connection:
            self._conn.close()
        elif not self._conn.closed:
            self._conn.autocommit = self._original_autocommit
            self._conn.row_factory = self._original_row_factory

    @contextmanager
    def transaction(self) -> Iterator["PostgresDecisionStore"]:
        if self._transaction_depth:
            self._transaction_depth += 1
            try:
                yield self
            finally:
                self._transaction_depth -= 1
            return
        self._transaction_depth = 1
        try:
            with self._conn.transaction():
                yield self
        finally:
            self._transaction_depth = 0

    def one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self._conn.execute(_postgres_sql(sql), params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._conn.execute(_postgres_sql(sql), params).fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...]) -> Any:
        return self._conn.execute(_postgres_sql(sql), params)

    def get_ballot(self, namespace_id: str, ballot_id: str) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if self._transaction_depth else ""
        row = self.one(
            "SELECT * FROM decision_ballots WHERE namespace_id = ? AND id = ?" + suffix,
            (namespace_id, ballot_id),
        )
        if row:
            row["choices"] = json.loads(row.pop("choices_json"))
            row["policy"] = json.loads(row.pop("policy_json"))
        return row

    def find_idempotent(
        self, namespace_id: str, principal_id: str, key: str
    ) -> dict[str, Any] | None:
        # Makes the check-and-record sequence atomic for identical command keys.
        lock_key = json.dumps([namespace_id, principal_id, key], separators=(",", ":"))
        self._conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
        return super().find_idempotent(namespace_id, principal_id, key)

    def append_audit(
        self,
        case: dict[str, Any],
        event_type: str,
        actor: str,
        payload: dict[str, Any],
    ) -> str:
        subject_id = str(case["audit_scope_id"])
        # Serializes even the first event for a subject, where no head row yet exists.
        self._conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (subject_id,))
        previous = self.one(
            "SELECT event_hash FROM audit_log WHERE subject_id = ? ORDER BY sequence DESC LIMIT 1",
            (subject_id,),
        )
        event_id = f"aud_{uuid.uuid4().hex}"
        created_at = utc_now()
        body = {
            "event_id": event_id,
            "subject_id": subject_id,
            "event_type": event_type,
            "created_at": created_at,
            "actor": actor,
            "session_id": None,
            "turn_id": None,
            "record_id": None,
            "payload": payload,
            "prev_hash": previous["event_hash"] if previous else None,
        }
        event_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.execute(
            """INSERT INTO audit_log(
                 event_id, subject_id, event_type, created_at, actor, session_id,
                 turn_id, record_id, payload, prev_hash, event_hash
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                subject_id,
                event_type,
                created_at,
                actor,
                None,
                None,
                None,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                body["prev_hash"],
                event_hash,
            ),
        )
        return event_id

    def _migrate_postgres(self) -> None:
        # SQLite is the canonical portable DDL. Introspection keeps both stores
        # on exactly the same table/index set while PostgreSQL owns runtime data.
        with self._conn.transaction():
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("aetnamem:decision-schema",),
            )
            exists = self._conn.execute(
                "SELECT to_regclass('schema_meta') AS relation"
            ).fetchone()
            if exists and exists["relation"]:
                current = self._conn.execute(
                    "SELECT value FROM schema_meta WHERE key = 'decision_schema'"
                ).fetchone()
                if current and current["value"] == str(self.SCHEMA_VERSION):
                    return

            source = SQLiteStore(":memory:")
            try:
                SQLiteDecisionStore(source)
                rows = source._conn.execute(
                    """SELECT type, name, sql FROM sqlite_master
                       WHERE sql IS NOT NULL AND (
                         name = 'schema_meta' OR name = 'audit_log' OR
                         name = 'idx_audit_subject_sequence' OR name LIKE 'decision_%' OR
                         name LIKE 'idx_decision_%'
                       )
                       ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name"""
                ).fetchall()
            finally:
                source.close()
            for row in rows:
                ddl = str(row["sql"])
                ddl = ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
                ddl = ddl.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
                ddl = ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
                if row["name"] == "audit_log":
                    ddl = ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
                self._conn.execute(ddl)
            for table, column in (
                ("decision_cases", "payload_purged_at"),
                ("decision_case_revisions", "purged_at"),
                ("decision_conflicts", "purged_at"),
                ("decision_artifact_revisions", "purged_at"),
                ("decision_vote_revisions", "purged_at"),
                ("decision_approval_records", "purged_at"),
                ("decision_idempotency", "case_id"),
                ("decision_idempotency", "purged_at"),
            ):
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} TEXT"
                )
            self._conn.execute(
                """INSERT INTO schema_meta(key, value) VALUES ('decision_schema', %s)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (str(self.SCHEMA_VERSION),),
            )


def _postgres_sql(sql: str) -> str:
    """Translate the repository's DB-API qmark placeholders to psycopg."""
    return sql.replace("?", "%s")
