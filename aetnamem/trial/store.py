from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.store.sqlite import utc_now


SCHEMA_VERSION = 1


class TrialStore:
    """Separate Safe Switch evidence store; never part of live agent recall."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._conn:
            yield

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trials (
                trial_id TEXT PRIMARY KEY,
                host TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                content TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                fact_key TEXT,
                confidence REAL NOT NULL,
                source_type TEXT NOT NULL,
                trust_tier TEXT NOT NULL,
                source_message_sha256 TEXT NOT NULL,
                source_session_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('candidate','approved','rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                UNIQUE(trial_id, content_sha256)
            );
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                session_id TEXT,
                host_run_id TEXT,
                query_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS previews (
                id TEXT PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                turn_id TEXT NOT NULL REFERENCES turns(id),
                candidate_ids_json TEXT NOT NULL,
                context_text TEXT NOT NULL,
                context_sha256 TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                context_chars INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exposures (
                id TEXT PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                turn_id TEXT NOT NULL REFERENCES turns(id),
                preview_id TEXT NOT NULL REFERENCES previews(id),
                session_id TEXT,
                mode TEXT NOT NULL CHECK(mode IN ('canary','active')),
                requested_at TEXT NOT NULL,
                shown INTEGER,
                shown_at TEXT
            );
            CREATE TABLE IF NOT EXISTS transitions (
                id TEXT PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                revision INTEGER NOT NULL,
                old_mode TEXT NOT NULL,
                new_mode TEXT NOT NULL,
                actor TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(trial_id, revision)
            );
            CREATE TABLE IF NOT EXISTS host_snapshots (
                id TEXT PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                host TEXT NOT NULL,
                config_path TEXT,
                config_sha256 TEXT,
                backup_path TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS comparisons (
                id TEXT PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                status TEXT NOT NULL,
                registration_sha256 TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                evidence_label TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
        elif int(row["value"]) != SCHEMA_VERSION:
            raise ValueError(f"unsupported trial database schema: {row['value']}")

    def create_trial(self, trial_id: str, host: str, subject_id: str) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO trials(trial_id, host, subject_id, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (trial_id, host, subject_id, utc_now()),
        )
        self._conn.commit()

    def insert_candidate(
        self,
        trial_id: str,
        *,
        content: str,
        fact_key: str | None,
        confidence: float,
        source_type: str,
        trust_tier: str,
        source_message_sha256: str,
        source_session_id: str | None,
    ) -> tuple[dict[str, Any], bool]:
        content_sha256 = sha256_hex(content)
        existing = self._conn.execute(
            "SELECT * FROM candidates WHERE trial_id = ? AND content_sha256 = ?",
            (trial_id, content_sha256),
        ).fetchone()
        if existing is not None:
            return dict(existing), True
        candidate_id = f"tc_{uuid.uuid4().hex}"
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO candidates(
                id, trial_id, content, content_sha256, fact_key, confidence,
                source_type, trust_tier, source_message_sha256,
                source_session_id, status, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
            """,
            (
                candidate_id,
                trial_id,
                content,
                content_sha256,
                fact_key,
                confidence,
                source_type,
                trust_tier,
                source_message_sha256,
                source_session_id,
                now,
            ),
        )
        self._conn.commit()
        return dict(
            self._conn.execute(
                "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        ), False

    def list_candidates(
        self, trial_id: str, *, statuses: tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM candidates WHERE trial_id = ?"
        values: list[Any] = [trial_id]
        if statuses:
            sql += f" AND status IN ({','.join('?' for _ in statuses)})"
            values.extend(statuses)
        sql += " ORDER BY created_at DESC, id"
        return [
            dict(row) for row in self._conn.execute(sql, values).fetchall()
        ]

    def review_candidates(
        self, trial_id: str, candidate_ids: list[str], *, approve: bool
    ) -> list[dict[str, Any]]:
        if not candidate_ids:
            return []
        status = "approved" if approve else "rejected"
        now = utc_now()
        placeholders = ",".join("?" for _ in candidate_ids)
        with self._conn:
            rows = self._conn.execute(
                f"""
                SELECT id FROM candidates
                WHERE trial_id = ? AND id IN ({placeholders})
                """,
                [trial_id, *candidate_ids],
            ).fetchall()
            found = {str(row["id"]) for row in rows}
            missing = sorted(set(candidate_ids) - found)
            if missing:
                raise ValueError(f"unknown trial candidate(s): {', '.join(missing)}")
            self._conn.execute(
                f"""
                UPDATE candidates SET status = ?, reviewed_at = ?
                WHERE trial_id = ? AND id IN ({placeholders})
                """,
                [status, now, trial_id, *candidate_ids],
            )
        return [
            row
            for row in self.list_candidates(trial_id)
            if row["id"] in set(candidate_ids)
        ]

    def insert_turn(
        self,
        trial_id: str,
        *,
        query_sha256: str,
        session_id: str | None,
        host_run_id: str | None,
    ) -> dict[str, Any]:
        turn_id = f"tt_{uuid.uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO turns(id, trial_id, session_id, host_run_id, query_sha256, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (turn_id, trial_id, session_id, host_run_id, query_sha256, utc_now()),
        )
        self._conn.commit()
        return dict(
            self._conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        )

    def insert_preview(
        self,
        trial_id: str,
        turn_id: str,
        *,
        candidate_ids: list[str],
        context_text: str,
        manifest_sha256: str,
    ) -> dict[str, Any]:
        preview_id = f"tp_{uuid.uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO previews(
                id, trial_id, turn_id, candidate_ids_json, context_text,
                context_sha256, manifest_sha256, context_chars, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preview_id,
                trial_id,
                turn_id,
                json.dumps(candidate_ids, separators=(",", ":")),
                context_text,
                sha256_hex(context_text),
                manifest_sha256,
                len(context_text),
                utc_now(),
            ),
        )
        self._conn.commit()
        return dict(
            self._conn.execute(
                "SELECT * FROM previews WHERE id = ?", (preview_id,)
            ).fetchone()
        )

    def insert_exposure(
        self,
        trial_id: str,
        *,
        turn_id: str,
        preview_id: str,
        session_id: str | None,
        mode: str,
    ) -> dict[str, Any]:
        exposure_id = f"tx_{uuid.uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO exposures(
                id, trial_id, turn_id, preview_id, session_id, mode, requested_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exposure_id,
                trial_id,
                turn_id,
                preview_id,
                session_id,
                mode,
                utc_now(),
            ),
        )
        self._conn.commit()
        return dict(
            self._conn.execute(
                "SELECT * FROM exposures WHERE id = ?", (exposure_id,)
            ).fetchone()
        )

    def count_exposures(self, trial_id: str, *, mode: str | None = None) -> int:
        if mode is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM exposures WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM exposures
                WHERE trial_id = ? AND mode = ?
                """,
                (trial_id, mode),
            ).fetchone()
        return int(row["n"])

    def count_shown_exposures(
        self, trial_id: str, *, mode: str | None = None
    ) -> int:
        if mode is None:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM exposures
                WHERE trial_id = ? AND shown = 1
                """,
                (trial_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM exposures
                WHERE trial_id = ? AND mode = ? AND shown = 1
                """,
                (trial_id, mode),
            ).fetchone()
        return int(row["n"])

    def mark_exposure_shown(self, trial_id: str, exposure_id: str) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE exposures SET shown = 1, shown_at = ?
                WHERE trial_id = ? AND id = ?
                """,
                (utc_now(), trial_id, exposure_id),
            )
        return cursor.rowcount == 1

    def append_transition(
        self,
        trial_id: str,
        *,
        revision: int,
        old_mode: str,
        new_mode: str,
        actor: str,
    ) -> dict[str, Any]:
        previous = self._conn.execute(
            """
            SELECT event_hash FROM transitions
            WHERE trial_id = ? ORDER BY revision DESC LIMIT 1
            """,
            (trial_id,),
        ).fetchone()
        previous_hash = str(previous["event_hash"]) if previous else "0" * 64
        payload = {
            "trial_id": trial_id,
            "revision": revision,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "actor": actor,
            "previous_hash": previous_hash,
            "created_at": utc_now(),
        }
        event_hash = sha256_hex(canonical_json(payload))
        transition_id = f"tr_{uuid.uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO transitions(
                id, trial_id, revision, old_mode, new_mode, actor,
                previous_hash, event_hash, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transition_id,
                trial_id,
                revision,
                old_mode,
                new_mode,
                actor,
                previous_hash,
                event_hash,
                payload["created_at"],
            ),
        )
        self._conn.commit()
        return {**payload, "id": transition_id, "event_hash": event_hash}

    def verify_transitions(self, trial_id: str) -> dict[str, Any]:
        rows = self._conn.execute(
            """
            SELECT * FROM transitions
            WHERE trial_id = ? ORDER BY revision, id
            """,
            (trial_id,),
        ).fetchall()
        previous = "0" * 64
        errors: list[str] = []
        for row in rows:
            payload = {
                "trial_id": row["trial_id"],
                "revision": row["revision"],
                "old_mode": row["old_mode"],
                "new_mode": row["new_mode"],
                "actor": row["actor"],
                "previous_hash": row["previous_hash"],
                "created_at": row["created_at"],
            }
            expected = sha256_hex(canonical_json(payload))
            if row["previous_hash"] != previous:
                errors.append(f"revision {row['revision']}: previous hash mismatch")
            if row["event_hash"] != expected:
                errors.append(f"revision {row['revision']}: event hash mismatch")
            previous = str(row["event_hash"])
        return {
            "valid": not errors,
            "events": len(rows),
            "head": previous,
            "errors": errors,
        }

    def add_host_snapshot(
        self,
        trial_id: str,
        *,
        host: str,
        config_path: str | None,
        config_sha256: str | None,
        backup_path: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_id = f"ths_{uuid.uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO host_snapshots(
                id, trial_id, host, config_path, config_sha256,
                backup_path, metadata_json, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                trial_id,
                host,
                config_path,
                config_sha256,
                backup_path,
                canonical_json(metadata),
                utc_now(),
            ),
        )
        self._conn.commit()
        return dict(
            self._conn.execute(
                "SELECT * FROM host_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        )

    def latest_snapshot(self, trial_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT * FROM host_snapshots
            WHERE trial_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (trial_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def summary(self, trial_id: str) -> dict[str, Any]:
        counts = {
            row["status"]: int(row["n"])
            for row in self._conn.execute(
                """
                SELECT status, COUNT(*) AS n FROM candidates
                WHERE trial_id = ? GROUP BY status
                """,
                (trial_id,),
            ).fetchall()
        }
        turn_count = int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM turns WHERE trial_id = ?", (trial_id,)
            ).fetchone()["n"]
        )
        preview_count = int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM previews WHERE trial_id = ?", (trial_id,)
            ).fetchone()["n"]
        )
        return {
            "candidates": counts,
            "turns": turn_count,
            "previews": preview_count,
            "exposures": self.count_exposures(trial_id),
            "shown_exposures": self.count_shown_exposures(trial_id),
            "shown_canary_exposures": self.count_shown_exposures(
                trial_id, mode="canary"
            ),
            "transition_chain": self.verify_transitions(trial_id),
        }
