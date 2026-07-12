"""Durable operational ledger for guarded actions.

Rows here are mutable recovery state. Every security-relevant transition is
also appended to aetnamem's engine-append-only hash chain by ``ActionEngine``. Raw
arguments and before-images live only in ``action_payloads`` so they can be
purged independently from the audit plane.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from aetnamem.store.sqlite import SQLiteStore, utc_now


class ActionStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self._conn = store._conn
        self._migrate()

    def create_plan(
        self,
        transaction: dict[str, Any],
        operations: list[dict[str, Any]],
        dependencies: list[tuple[str, str]],
        evidence: list[dict[str, Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        with self.store.transaction():
            self._conn.execute(
                """
                INSERT INTO action_transactions (
                  id, subject_id, session_id, turn_id, actor_id, mode, state,
                  plan_version, plan_hash, policy_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction["id"], transaction["subject_id"],
                    transaction.get("session_id"), transaction.get("turn_id"),
                    transaction["actor_id"], transaction["mode"],
                    transaction["state"], transaction["plan_version"],
                    transaction["plan_hash"], transaction["policy_hash"],
                    transaction["created_at"], transaction["created_at"],
                ),
            )
            for operation in operations:
                self._conn.execute(
                    """
                    INSERT INTO action_operations (
                      id, transaction_id, operation_key, ordinal, adapter,
                      operation, effect_class, state, idempotency_key,
                      arguments_digest, preview_digest, precondition_digest,
                      manifest_digest, selected
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation["id"], transaction["id"], operation["key"],
                        operation["ordinal"], operation["adapter"],
                        operation["operation"], operation["effect_class"],
                        operation["state"], operation["idempotency_key"],
                        operation["arguments_digest"], operation["preview_digest"],
                        operation["precondition_digest"], operation["manifest_digest"],
                        int(operation.get("selected", True)),
                    ),
                )
            for operation_id, depends_on_id in dependencies:
                self._conn.execute(
                    "INSERT INTO action_dependencies (operation_id, depends_on_operation_id) VALUES (?, ?)",
                    (operation_id, depends_on_id),
                )
            for item in evidence:
                self._conn.execute(
                    """
                    INSERT INTO action_evidence (
                      id, transaction_id, operation_id, evidence_kind, ref_id,
                      digest, relation, trust_tier, attested
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"], transaction["id"], item.get("operation_id"),
                        item["kind"], item["ref_id"], item["digest"],
                        item["relation"], item["trust_tier"], int(item["attested"]),
                    ),
                )
            for payload in payloads:
                self._put_payload(payload)

    def get_transaction(
        self, transaction_id: str, *, include_payloads: bool = False
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM action_transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        if row is None:
            return None
        value = dict(row)
        operations = [
            dict(item)
            for item in self._conn.execute(
                "SELECT * FROM action_operations WHERE transaction_id = ? ORDER BY ordinal",
                (transaction_id,),
            ).fetchall()
        ]
        dependencies = self._conn.execute(
            """
            SELECT operation_id, depends_on_operation_id
            FROM action_dependencies
            WHERE operation_id IN (
              SELECT id FROM action_operations WHERE transaction_id = ?
            )
            ORDER BY operation_id, depends_on_operation_id
            """,
            (transaction_id,),
        ).fetchall()
        evidence = [
            {**dict(item), "attested": bool(item["attested"])}
            for item in self._conn.execute(
                "SELECT * FROM action_evidence WHERE transaction_id = ? ORDER BY id",
                (transaction_id,),
            ).fetchall()
        ]
        dependency_map: dict[str, list[str]] = {item["id"]: [] for item in operations}
        for dependency in dependencies:
            dependency_map[dependency["operation_id"]].append(
                dependency["depends_on_operation_id"]
            )
        evidence_map: dict[str, list[dict[str, Any]]] = {item["id"]: [] for item in operations}
        for item in evidence:
            if item["operation_id"] in evidence_map:
                evidence_map[item["operation_id"]].append(item)
        payload_map: dict[str, dict[str, Any]] = {}
        if include_payloads:
            for payload in self._conn.execute(
                """
                SELECT * FROM action_payloads
                WHERE transaction_id = ? AND purged_at IS NULL
                """,
                (transaction_id,),
            ).fetchall():
                payload_map.setdefault(payload["operation_id"], {})[payload["kind"]] = json.loads(
                    payload["payload"]
                )
        for operation in operations:
            operation["selected"] = bool(operation["selected"])
            operation["depends_on"] = dependency_map[operation["id"]]
            operation["evidence"] = evidence_map[operation["id"]]
            if include_payloads:
                operation["payloads"] = payload_map.get(operation["id"], {})
        value["operations"] = operations
        value["evidence"] = evidence
        value["approvals"] = self.list_approvals(transaction_id)
        value["receipts"] = self.list_receipts(transaction_id)
        return value

    def list_transactions(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        if subject_id is None:
            rows = self._conn.execute(
                "SELECT * FROM action_transactions ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM action_transactions WHERE subject_id = ? ORDER BY created_at DESC",
                (subject_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_transaction_state(
        self,
        transaction_id: str,
        state: str,
        *,
        expected: Iterable[str] | None = None,
        error_code: str | None = None,
        error_digest: str | None = None,
    ) -> None:
        with self.store.transaction():
            if expected is not None:
                current = self._conn.execute(
                    "SELECT state FROM action_transactions WHERE id = ?", (transaction_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(transaction_id)
                allowed = set(expected)
                if current["state"] not in allowed:
                    raise ValueError(
                        f"transaction {transaction_id} is {current['state']}, expected {sorted(allowed)}"
                    )
            terminal_at = utc_now() if state in {
                "committed", "aborted", "compensated", "partial", "uncertain",
                "recovery_required",
            } else None
            self._conn.execute(
                """
                UPDATE action_transactions
                SET state = ?, updated_at = ?, terminal_at = COALESCE(?, terminal_at),
                    error_code = ?, error_digest = ?
                WHERE id = ?
                """,
                (state, utc_now(), terminal_at, error_code, error_digest, transaction_id),
            )

    def set_operation_state(
        self,
        operation_id: str,
        state: str,
        *,
        result_digest: str | None = None,
        compensation_digest: str | None = None,
    ) -> None:
        with self.store.transaction():
            self._conn.execute(
                """
                UPDATE action_operations
                SET state = ?, result_digest = COALESCE(?, result_digest),
                    compensation_digest = COALESCE(?, compensation_digest)
                WHERE id = ?
                """,
                (state, result_digest, compensation_digest, operation_id),
            )

    def put_payload(
        self,
        *,
        transaction_id: str,
        operation_id: str,
        kind: str,
        payload: dict[str, Any],
        digest: str,
    ) -> None:
        with self.store.transaction():
            self._put_payload(
                {
                    "transaction_id": transaction_id,
                    "operation_id": operation_id,
                    "kind": kind,
                    "payload": payload,
                    "digest": digest,
                }
            )

    def _put_payload(self, value: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO action_payloads (
              transaction_id, operation_id, kind, payload, digest, created_at, purged_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(operation_id, kind) DO UPDATE SET
              payload = excluded.payload, digest = excluded.digest,
              created_at = excluded.created_at, purged_at = NULL
            """,
            (
                value["transaction_id"], value["operation_id"], value["kind"],
                json.dumps(value["payload"], sort_keys=True, separators=(",", ":")),
                value["digest"], utc_now(),
            ),
        )

    def record_approval(self, transaction_id: str, approval: dict[str, Any]) -> str:
        approval_id = f"apr_{approval['nonce']}"
        with self.store.transaction():
            self._conn.execute(
                """
                INSERT INTO action_approvals (
                  id, transaction_id, plan_hash, approver_principal, decision,
                  issued_at, expires_at, nonce, signature, approval_digest, created_at
                ) VALUES (?, ?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id, transaction_id, approval["plan_hash"],
                    approval["approver"], approval["issued_at"], approval["expires_at"],
                    approval["nonce"], approval["signature"], approval["digest"], utc_now(),
                ),
            )
        return approval_id

    def list_approvals(self, transaction_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM action_approvals WHERE transaction_id = ? ORDER BY created_at",
                (transaction_id,),
            ).fetchall()
        ]

    def start_attempt(
        self, operation_id: str, phase: str, idempotency_key: str
    ) -> tuple[str, int]:
        with self.store.transaction():
            row = self._conn.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) AS n FROM action_attempts WHERE operation_id = ? AND phase = ?",
                (operation_id, phase),
            ).fetchone()
            number = int(row["n"]) + 1
            attempt_id = f"att_{operation_id}_{phase}_{number}"
            self._conn.execute(
                """
                INSERT INTO action_attempts (
                  id, operation_id, phase, attempt_number, state, idempotency_key,
                  started_at
                ) VALUES (?, ?, ?, ?, 'executing', ?, ?)
                """,
                (attempt_id, operation_id, phase, number, idempotency_key, utc_now()),
            )
        return attempt_id, number

    def finish_attempt(
        self,
        attempt_id: str,
        state: str,
        *,
        provider_request_id: str | None = None,
        error_code: str | None = None,
        error_digest: str | None = None,
    ) -> None:
        with self.store.transaction():
            self._conn.execute(
                """
                UPDATE action_attempts
                SET state = ?, finished_at = ?, provider_request_id = ?,
                    error_code = ?, error_digest = ?
                WHERE id = ?
                """,
                (
                    state, utc_now(), provider_request_id, error_code, error_digest,
                    attempt_id,
                ),
            )

    def store_receipt(
        self, transaction_id: str, receipt: dict[str, Any]
    ) -> None:
        with self.store.transaction():
            self._conn.execute(
                """
                INSERT INTO action_receipts (
                  id, transaction_id, format, receipt_json, receipt_hash,
                  audit_event_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"rcp_{receipt['receipt_sha256'][:24]}", transaction_id,
                    receipt["format"],
                    json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                    receipt["receipt_sha256"], receipt["audit_event_id"],
                    receipt["created_at"],
                ),
            )

    def list_receipts(self, transaction_id: str) -> list[dict[str, Any]]:
        return [
            json.loads(row["receipt_json"])
            for row in self._conn.execute(
                "SELECT receipt_json FROM action_receipts WHERE transaction_id = ? ORDER BY created_at",
                (transaction_id,),
            ).fetchall()
        ]

    def purge_payloads(self, transaction_id: str) -> int:
        with self.store.transaction():
            cursor = self._conn.execute(
                """
                UPDATE action_payloads
                SET payload = '{}', purged_at = ?
                WHERE transaction_id = ? AND purged_at IS NULL
                """,
                (utc_now(), transaction_id),
            )
        return cursor.rowcount

    def _migrate(self) -> None:
        # executescript owns its schema transaction. Migrations are additive so
        # existing audit-v1 databases and independent verifiers remain valid.
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_transactions (
              id TEXT PRIMARY KEY,
              subject_id TEXT NOT NULL,
              session_id TEXT,
              turn_id TEXT,
              actor_id TEXT NOT NULL,
              mode TEXT NOT NULL,
              state TEXT NOT NULL,
              plan_version INTEGER NOT NULL,
              plan_hash TEXT NOT NULL,
              policy_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              terminal_at TEXT,
              error_code TEXT,
              error_digest TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_action_transactions_subject
              ON action_transactions(subject_id, created_at);

            CREATE TABLE IF NOT EXISTS action_operations (
              id TEXT PRIMARY KEY,
              transaction_id TEXT NOT NULL,
              operation_key TEXT NOT NULL,
              ordinal INTEGER NOT NULL,
              adapter TEXT NOT NULL,
              operation TEXT NOT NULL,
              effect_class TEXT NOT NULL,
              state TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,
              arguments_digest TEXT NOT NULL,
              preview_digest TEXT NOT NULL,
              precondition_digest TEXT NOT NULL,
              result_digest TEXT,
              compensation_digest TEXT,
              manifest_digest TEXT NOT NULL,
              selected INTEGER NOT NULL DEFAULT 1,
              UNIQUE(transaction_id, operation_key),
              UNIQUE(transaction_id, ordinal),
              FOREIGN KEY (transaction_id) REFERENCES action_transactions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_dependencies (
              operation_id TEXT NOT NULL,
              depends_on_operation_id TEXT NOT NULL,
              PRIMARY KEY(operation_id, depends_on_operation_id),
              FOREIGN KEY (operation_id) REFERENCES action_operations(id) ON DELETE CASCADE,
              FOREIGN KEY (depends_on_operation_id) REFERENCES action_operations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_evidence (
              id TEXT PRIMARY KEY,
              transaction_id TEXT NOT NULL,
              operation_id TEXT,
              evidence_kind TEXT NOT NULL,
              ref_id TEXT NOT NULL,
              digest TEXT NOT NULL,
              relation TEXT NOT NULL CHECK (relation IN ('informed_by', 'authorized_by')),
              trust_tier TEXT NOT NULL,
              attested INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY (transaction_id) REFERENCES action_transactions(id) ON DELETE CASCADE,
              FOREIGN KEY (operation_id) REFERENCES action_operations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_approvals (
              id TEXT PRIMARY KEY,
              transaction_id TEXT NOT NULL,
              plan_hash TEXT NOT NULL,
              approver_principal TEXT NOT NULL,
              decision TEXT NOT NULL,
              issued_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              nonce TEXT NOT NULL UNIQUE,
              signature TEXT NOT NULL,
              approval_digest TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (transaction_id) REFERENCES action_transactions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_attempts (
              id TEXT PRIMARY KEY,
              operation_id TEXT NOT NULL,
              phase TEXT NOT NULL,
              attempt_number INTEGER NOT NULL,
              state TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              provider_request_id TEXT,
              error_code TEXT,
              error_digest TEXT,
              UNIQUE(operation_id, phase, attempt_number),
              FOREIGN KEY (operation_id) REFERENCES action_operations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_payloads (
              transaction_id TEXT NOT NULL,
              operation_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              digest TEXT NOT NULL,
              created_at TEXT NOT NULL,
              purged_at TEXT,
              PRIMARY KEY(operation_id, kind),
              FOREIGN KEY (transaction_id) REFERENCES action_transactions(id) ON DELETE CASCADE,
              FOREIGN KEY (operation_id) REFERENCES action_operations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_receipts (
              id TEXT PRIMARY KEY,
              transaction_id TEXT NOT NULL,
              format TEXT NOT NULL,
              receipt_json TEXT NOT NULL,
              receipt_hash TEXT NOT NULL,
              audit_event_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (transaction_id) REFERENCES action_transactions(id) ON DELETE CASCADE
            );
            """
        )
        with self.store.transaction():
            self._conn.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES ('actions_schema', '1')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )
