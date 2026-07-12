"""Safe compatibility bridge for external operational journals.

Source rows are imported as unverified evidence, never as authoritative aetnamem
state. Raw arguments, snapshots, results, actor names, and client identities
are reduced to digests before entering aetnamem's engine-append-only audit plane.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from aetnamem.actions.models import digest_json
from aetnamem.memory import Memory


class TransactionJournalImporter:
    def __init__(self, memory: Memory) -> None:
        self.memory = memory

    def import_journal(
        self,
        journal_path: str | Path,
        *,
        subject_id: str,
        source_id: str,
        actor: str = "journal-importer",
    ) -> dict[str, Any]:
        path = Path(journal_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            self._validate_schema(conn)
            transactions = conn.execute(
                "SELECT * FROM transactions ORDER BY created_at, txn_id"
            ).fetchall()
            imported: list[dict[str, Any]] = []
            skipped: list[str] = []
            source_digest = digest_json(source_id)
            existing = {
                (
                    event["payload"].get("source_id_digest"),
                    event["payload"].get("source_transaction_id"),
                )
                for event in self.memory.store.list_audit_events(subject_id)
                if event["event_type"] == "action.source_imported"
            }
            for transaction_row in transactions:
                transaction = dict(transaction_row)
                transaction_id = str(transaction["txn_id"])
                if (source_digest, transaction_id) in existing:
                    skipped.append(transaction_id)
                    continue
                effect_rows = conn.execute(
                    "SELECT * FROM effects WHERE txn_id = ? ORDER BY idx",
                    (transaction_id,),
                ).fetchall()
                effects = [self._effect_summary(dict(row)) for row in effect_rows]
                payload = {
                    "provider": "external_transaction_journal",
                    "evidence_status": "unverified_operational_journal",
                    "source_id_digest": source_digest,
                    "source_transaction_id": transaction_id,
                    "source_state": transaction.get("state"),
                    "created_at": transaction.get("created_at"),
                    "updated_at": transaction.get("updated_at"),
                    "replayed_from_digest": _optional_digest(
                        transaction.get("replayed_from")
                    ),
                    "client_id_digest": _optional_digest(transaction.get("client_id")),
                    "dry_run": bool(transaction.get("dry_run", 0)),
                    "effects": effects,
                    "effects_digest": digest_json(effects),
                }
                event_id = self.memory.store.append_audit_event(
                    subject_id=subject_id,
                    event_type="action.source_imported",
                    actor=actor,
                    payload=payload,
                )
                event = self.memory.store.get_audit_event(subject_id, event_id)
                imported.append(
                    {
                        "source_transaction_id": transaction_id,
                        "audit_event_id": event_id,
                        "audit_event_hash": event["event_hash"] if event else None,
                        "effect_count": len(effects),
                    }
                )
                existing.add((source_digest, transaction_id))
            return {
                "source_id_digest": source_digest,
                "imported": imported,
                "skipped_transaction_ids": skipped,
            }
        finally:
            conn.close()

    @staticmethod
    def _validate_schema(conn: sqlite3.Connection) -> None:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = {"transactions", "effects"} - tables
        if missing:
            raise ValueError(f"not a compatible transaction journal; missing tables: {sorted(missing)}")
        required_columns = {
            "transactions": {
                "txn_id", "state", "created_at", "updated_at",
                "replayed_from", "dry_run", "client_id",
            },
            "effects": {
                "txn_id", "idx", "effect_id", "tool", "resource",
                "reversible", "status", "args", "snapshot", "result",
                "read_keys", "write_keys", "actor", "ts",
            },
        }
        for table, required in required_columns.items():
            actual = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table})")
            }
            missing_columns = sorted(required - actual)
            if missing_columns:
                raise ValueError(
                    f"not a compatible transaction journal; {table} is missing "
                    f"columns: {missing_columns}"
                )

    @staticmethod
    def _effect_summary(effect: dict[str, Any]) -> dict[str, Any]:
        return {
            "index": effect.get("idx"),
            "effect_id": effect.get("effect_id"),
            "tool": effect.get("tool"),
            "resource": effect.get("resource"),
            "reversible_claim": bool(effect.get("reversible")),
            "status_claim": effect.get("status"),
            "args_digest": _json_column_digest(effect.get("args")),
            "snapshot_digest": _json_column_digest(effect.get("snapshot")),
            "result_digest": _json_column_digest(effect.get("result")),
            "read_keys_digest": _json_column_digest(effect.get("read_keys")),
            "write_keys_digest": _json_column_digest(effect.get("write_keys")),
            "claimed_actor_digest": _optional_digest(effect.get("actor")),
            "timestamp": effect.get("ts"),
        }


def _json_column_digest(value: Any) -> str | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        parsed = {"invalid_json_digest": digest_json(str(value))}
    return digest_json(parsed)


def _optional_digest(value: Any) -> str | None:
    return None if value is None else digest_json(str(value))
