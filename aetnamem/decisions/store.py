"""Lazy SQLite persistence for the collaborative decision engine."""

from __future__ import annotations

from contextlib import AbstractContextManager
import json
from typing import Any

from aetnamem.store.sqlite import SQLiteStore


class SQLiteDecisionStore:
    """Decision tables sharing one SQLite unit of work with the audit ledger."""

    SCHEMA_VERSION = 3

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self._conn = store._conn
        self._migrate()

    def transaction(self) -> AbstractContextManager[SQLiteStore]:
        return self.store.transaction(immediate=True)

    def _migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decision_templates (
              namespace_id TEXT NOT NULL,
              template_id TEXT NOT NULL,
              version TEXT NOT NULL,
              template_json TEXT NOT NULL,
              digest TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, template_id, version)
            );

            CREATE TABLE IF NOT EXISTS decision_cases (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active','closed','superseded')),
              template_id TEXT NOT NULL,
              template_version TEXT NOT NULL,
              template_digest TEXT NOT NULL,
              current_revision INTEGER NOT NULL,
              version INTEGER NOT NULL,
              audit_scope_id TEXT NOT NULL UNIQUE,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id)
            );
            CREATE INDEX IF NOT EXISTS idx_decision_cases_namespace
              ON decision_cases(namespace_id, status, updated_at);

            CREATE TABLE IF NOT EXISTS decision_case_revisions (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              content_json TEXT NOT NULL,
              digest TEXT NOT NULL,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id),
              UNIQUE(namespace_id, case_id, revision)
            );

            CREATE TABLE IF NOT EXISTS decision_memberships (
              namespace_id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              role TEXT NOT NULL,
              capabilities_json TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active','inactive')),
              version INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, case_id, principal_id)
            );

            CREATE TABLE IF NOT EXISTS decision_conflicts (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              scope TEXT NOT NULL,
              details_json TEXT NOT NULL,
              details_digest TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('declared','cleared','managed','recused')),
              ruled_by TEXT,
              ruling_digest TEXT,
              version INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id)
            );
            CREATE INDEX IF NOT EXISTS idx_decision_conflicts_case
              ON decision_conflicts(namespace_id, case_id, principal_id, status);

            CREATE TABLE IF NOT EXISTS decision_artifacts (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('draft','submitted','final','superseded','withdrawn')),
              current_revision INTEGER NOT NULL,
              version INTEGER NOT NULL,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id)
            );
            CREATE INDEX IF NOT EXISTS idx_decision_artifacts_case
              ON decision_artifacts(namespace_id, case_id, kind, status);

            CREATE TABLE IF NOT EXISTS decision_artifact_revisions (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              artifact_id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              kind TEXT NOT NULL,
              content_json TEXT NOT NULL,
              digest TEXT NOT NULL,
              author TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id),
              UNIQUE(namespace_id, artifact_id, revision)
            );

            CREATE TABLE IF NOT EXISTS decision_artifact_links (
              namespace_id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              target_revision_id TEXT NOT NULL,
              source_revision_id TEXT NOT NULL,
              source_digest TEXT NOT NULL,
              role TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, target_revision_id, source_revision_id, role)
            );
            CREATE INDEX IF NOT EXISTS idx_decision_links_source
              ON decision_artifact_links(namespace_id, source_revision_id, role);

            CREATE TABLE IF NOT EXISTS decision_ballots (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              target_revision_id TEXT NOT NULL,
              target_digest TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('open','closed','cancelled')),
              choices_json TEXT NOT NULL,
              policy_json TEXT NOT NULL,
              policy_digest TEXT NOT NULL,
              visibility TEXT NOT NULL CHECK(visibility IN ('open','hidden_until_close')),
              closes_at TEXT,
              version INTEGER NOT NULL,
              opened_by TEXT NOT NULL,
              opened_at TEXT NOT NULL,
              closed_at TEXT,
              PRIMARY KEY(namespace_id, id)
            );

            CREATE TABLE IF NOT EXISTS decision_ballot_eligibility (
              namespace_id TEXT NOT NULL,
              ballot_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              eligible INTEGER NOT NULL,
              reason TEXT,
              membership_version INTEGER NOT NULL,
              PRIMARY KEY(namespace_id, ballot_id, principal_id)
            );

            CREATE TABLE IF NOT EXISTS decision_vote_revisions (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              ballot_id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              choice TEXT NOT NULL,
              rationale_json TEXT NOT NULL,
              salt TEXT NOT NULL,
              commitment TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('current','superseded')),
              supersedes_id TEXT,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id),
              UNIQUE(namespace_id, ballot_id, principal_id, revision)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_vote_current
              ON decision_vote_revisions(namespace_id, ballot_id, principal_id)
              WHERE status = 'current';

            CREATE TABLE IF NOT EXISTS decision_ballot_outcomes (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              ballot_id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              outcome_json TEXT NOT NULL,
              digest TEXT NOT NULL,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id),
              UNIQUE(namespace_id, ballot_id)
            );

            CREATE TABLE IF NOT EXISTS decision_adoptions (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              target_revision_id TEXT NOT NULL,
              target_digest TEXT NOT NULL,
              outcome_id TEXT NOT NULL,
              digest TEXT NOT NULL,
              adopted_by TEXT NOT NULL,
              adopted_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id),
              UNIQUE(namespace_id, target_revision_id)
            );

            CREATE TABLE IF NOT EXISTS decision_approval_records (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              target_revision_id TEXT NOT NULL,
              target_digest TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              decision TEXT NOT NULL CHECK(decision IN ('approve','reject')),
              rationale_json TEXT NOT NULL,
              digest TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id),
              UNIQUE(namespace_id, target_revision_id, principal_id)
            );

            CREATE TABLE IF NOT EXISTS decision_authorizations (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              plan_revision_id TEXT NOT NULL,
              plan_digest TEXT NOT NULL,
              adoption_id TEXT NOT NULL,
              approval_ids_json TEXT NOT NULL,
              scope_json TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active','revoked','expired')),
              expires_at TEXT,
              digest TEXT NOT NULL,
              granted_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              revoked_at TEXT,
              PRIMARY KEY(namespace_id, id)
            );
            CREATE INDEX IF NOT EXISTS idx_decision_authorizations_plan
              ON decision_authorizations(namespace_id, plan_revision_id, status);

            CREATE TABLE IF NOT EXISTS decision_action_links (
              namespace_id TEXT NOT NULL,
              authorization_id TEXT NOT NULL,
              transaction_id TEXT NOT NULL,
              receipt_id TEXT,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, authorization_id, transaction_id)
            );

            CREATE TABLE IF NOT EXISTS decision_idempotency (
              namespace_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,
              command TEXT NOT NULL,
              request_digest TEXT NOT NULL,
              response_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, principal_id, idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS decision_signatures (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              object_kind TEXT NOT NULL,
              object_id TEXT NOT NULL,
              object_digest TEXT NOT NULL,
              receipt_digest TEXT NOT NULL,
              signature_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id),
              UNIQUE(namespace_id, object_kind, object_id)
            );

            CREATE TABLE IF NOT EXISTS decision_retention_policies (
              namespace_id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              payload_days INTEGER,
              coi_days INTEGER,
              updated_by TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, case_id)
            );

            CREATE TABLE IF NOT EXISTS decision_purge_receipts (
              namespace_id TEXT NOT NULL,
              id TEXT NOT NULL,
              case_id TEXT NOT NULL,
              categories_json TEXT NOT NULL,
              items_json TEXT NOT NULL,
              cutoff_at TEXT NOT NULL,
              digest TEXT NOT NULL,
              purged_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(namespace_id, id)
            );
            """
        )
        self._add_column("decision_case_revisions", "purged_at", "TEXT")
        self._add_column("decision_cases", "payload_purged_at", "TEXT")
        self._add_column("decision_conflicts", "purged_at", "TEXT")
        self._add_column("decision_artifact_revisions", "purged_at", "TEXT")
        self._add_column("decision_vote_revisions", "purged_at", "TEXT")
        self._add_column("decision_approval_records", "purged_at", "TEXT")
        self._add_column("decision_idempotency", "case_id", "TEXT")
        self._add_column("decision_idempotency", "purged_at", "TEXT")
        with self.store.transaction():
            self._conn.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES ('decision_schema', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(self.SCHEMA_VERSION),),
            )

    def _add_column(self, table: str, column: str, declaration: str) -> None:
        columns = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def close(self) -> None:
        """Repository lifecycle hook; the owning engine closes the SQLiteStore."""

    # -- generic row helpers -------------------------------------------------

    def one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...]) -> Any:
        return self._conn.execute(sql, params)

    # -- scoped reads --------------------------------------------------------

    def get_case(self, namespace_id: str, case_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM decision_cases WHERE namespace_id = ? AND id = ?",
            (namespace_id, case_id),
        )

    def get_template(self, case: dict[str, Any]) -> dict[str, Any]:
        row = self.one(
            """
            SELECT * FROM decision_templates
            WHERE namespace_id = ? AND template_id = ? AND version = ?
            """,
            (case["namespace_id"], case["template_id"], case["template_version"]),
        )
        if row is None:
            raise RuntimeError("pinned decision template is missing")
        row["template"] = json.loads(row.pop("template_json"))
        return row

    def get_membership(
        self, namespace_id: str, case_id: str, principal_id: str
    ) -> dict[str, Any] | None:
        row = self.one(
            """
            SELECT * FROM decision_memberships
            WHERE namespace_id = ? AND case_id = ? AND principal_id = ?
            """,
            (namespace_id, case_id, principal_id),
        )
        if row:
            row["capabilities"] = json.loads(row.pop("capabilities_json"))
        return row

    def list_memberships(self, namespace_id: str, case_id: str) -> list[dict[str, Any]]:
        rows = self.all(
            """
            SELECT * FROM decision_memberships
            WHERE namespace_id = ? AND case_id = ? ORDER BY principal_id
            """,
            (namespace_id, case_id),
        )
        for row in rows:
            row["capabilities"] = json.loads(row.pop("capabilities_json"))
        return rows

    def get_artifact(self, namespace_id: str, artifact_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM decision_artifacts WHERE namespace_id = ? AND id = ?",
            (namespace_id, artifact_id),
        )

    def get_revision(self, namespace_id: str, revision_id: str) -> dict[str, Any] | None:
        row = self.one(
            """
            SELECT * FROM decision_artifact_revisions
            WHERE namespace_id = ? AND id = ?
            """,
            (namespace_id, revision_id),
        )
        if row:
            row["content"] = json.loads(row.pop("content_json"))
        return row

    def current_revision(self, artifact: dict[str, Any]) -> dict[str, Any]:
        row = self.one(
            """
            SELECT * FROM decision_artifact_revisions
            WHERE namespace_id = ? AND artifact_id = ? AND revision = ?
            """,
            (artifact["namespace_id"], artifact["id"], artifact["current_revision"]),
        )
        if row is None:
            raise RuntimeError("current artifact revision is missing")
        row["content"] = json.loads(row.pop("content_json"))
        return row

    def get_ballot(self, namespace_id: str, ballot_id: str) -> dict[str, Any] | None:
        row = self.one(
            "SELECT * FROM decision_ballots WHERE namespace_id = ? AND id = ?",
            (namespace_id, ballot_id),
        )
        if row:
            row["choices"] = json.loads(row.pop("choices_json"))
            row["policy"] = json.loads(row.pop("policy_json"))
        return row

    def eligible_voters(self, namespace_id: str, ballot_id: str) -> list[dict[str, Any]]:
        return self.all(
            """
            SELECT * FROM decision_ballot_eligibility
            WHERE namespace_id = ? AND ballot_id = ? ORDER BY principal_id
            """,
            (namespace_id, ballot_id),
        )

    def current_votes(self, namespace_id: str, ballot_id: str) -> list[dict[str, Any]]:
        rows = self.all(
            """
            SELECT * FROM decision_vote_revisions
            WHERE namespace_id = ? AND ballot_id = ? AND status = 'current'
            ORDER BY principal_id
            """,
            (namespace_id, ballot_id),
        )
        for row in rows:
            row["rationale"] = json.loads(row.pop("rationale_json"))
        return rows

    def get_outcome(self, namespace_id: str, outcome_id: str) -> dict[str, Any] | None:
        row = self.one(
            """
            SELECT * FROM decision_ballot_outcomes
            WHERE namespace_id = ? AND id = ?
            """,
            (namespace_id, outcome_id),
        )
        if row:
            row["outcome"] = json.loads(row.pop("outcome_json"))
        return row

    def get_adoption(self, namespace_id: str, adoption_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM decision_adoptions WHERE namespace_id = ? AND id = ?",
            (namespace_id, adoption_id),
        )

    def get_authorization(
        self, namespace_id: str, authorization_id: str
    ) -> dict[str, Any] | None:
        row = self.one(
            """
            SELECT * FROM decision_authorizations
            WHERE namespace_id = ? AND id = ?
            """,
            (namespace_id, authorization_id),
        )
        if row:
            row["approval_ids"] = json.loads(row.pop("approval_ids_json"))
            row["scope"] = json.loads(row.pop("scope_json"))
        return row

    def list_links(self, namespace_id: str, revision_id: str) -> list[dict[str, Any]]:
        return self.all(
            """
            SELECT * FROM decision_artifact_links
            WHERE namespace_id = ? AND target_revision_id = ?
            ORDER BY role, source_revision_id
            """,
            (namespace_id, revision_id),
        )

    def append_audit(
        self,
        case: dict[str, Any],
        event_type: str,
        actor: str,
        payload: dict[str, Any],
    ) -> str:
        return self.store.append_audit_event(
            subject_id=case["audit_scope_id"],
            event_type=event_type,
            actor=actor,
            payload=payload,
        )

    def list_events(
        self, namespace_id: str, case_id: str, *, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        case = self.get_case(namespace_id, case_id)
        if case is None:
            return []
        rows = self.all(
            """
            SELECT * FROM audit_log
            WHERE subject_id = ? AND sequence > ? ORDER BY sequence
            """,
            (case["audit_scope_id"], after_sequence),
        )
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    def find_idempotent(
        self, namespace_id: str, principal_id: str, key: str
    ) -> dict[str, Any] | None:
        row = self.one(
            """
            SELECT * FROM decision_idempotency
            WHERE namespace_id = ? AND principal_id = ? AND idempotency_key = ?
            """,
            (namespace_id, principal_id, key),
        )
        if row:
            row["response"] = json.loads(row.pop("response_json"))
        return row

    def record_idempotent(
        self,
        namespace_id: str,
        principal_id: str,
        key: str,
        command: str,
        request_digest: str,
        response: dict[str, Any],
        created_at: str,
        case_id: str | None = None,
    ) -> None:
        self.execute(
            """
            INSERT INTO decision_idempotency(
              namespace_id, principal_id, idempotency_key, command,
              request_digest, response_json, created_at, case_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                namespace_id,
                principal_id,
                key,
                command,
                request_digest,
                json.dumps(response, sort_keys=True, separators=(",", ":")),
                created_at,
                case_id,
            ),
        )

    def get_signature(self, namespace_id: str, object_kind: str, object_id: str) -> dict[str, Any] | None:
        row = self.one(
            """SELECT * FROM decision_signatures
               WHERE namespace_id = ? AND object_kind = ? AND object_id = ?""",
            (namespace_id, object_kind, object_id),
        )
        if row:
            row["signature"] = json.loads(row.pop("signature_json"))
        return row

    def list_signatures(self, namespace_id: str, case_id: str) -> list[dict[str, Any]]:
        rows = self.all(
            """SELECT * FROM decision_signatures
               WHERE namespace_id = ? AND case_id = ? ORDER BY created_at, id""",
            (namespace_id, case_id),
        )
        for row in rows:
            row["signature"] = json.loads(row.pop("signature_json"))
        return rows
