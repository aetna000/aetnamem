"""Versioned-epoch exact vector index derived from canonical memory records."""

from __future__ import annotations

from array import array
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterator, Sequence
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.memory import Memory
from aetnamem.semantic.providers import Embedder
from aetnamem.store.sqlite import utc_now


INDEX_SCHEMA_VERSION = "2"
INDEX_FORMAT = "aetnamem-semantic-index-v1"
INDEXABLE_STATUSES = ("active", "quarantined", "superseded")


class SemanticIndexIntegrityError(ValueError):
    """The derived index is inconsistent with its declared epoch."""


def default_index_path(memory_path: str | Path) -> Path:
    path = str(memory_path)
    if path == ":memory:":
        raise ValueError("semantic indexing requires a persistent memory database")
    return Path(f"{path}.vectors.db")


class SemanticIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA secure_delete = ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def build(
        self,
        memory: Memory,
        subject_id: str,
        embedder: Embedder,
        *,
        batch_size: int = 64,
    ) -> dict[str, Any]:
        # Register before embedding starts. A crash or provider failure can
        # then leave an empty sidecar, but never an untracked sidecar that a
        # later deletion would silently miss.
        memory.store.register_semantic_index(subject_id, self.path)
        verify_identity = getattr(embedder, "verify_identity", None)
        if callable(verify_identity):
            verify_identity()
        records = memory.store.list_records(subject_id, statuses=INDEXABLE_STATUSES)
        if not records:
            raise ValueError(f"no indexable memory records for subject {subject_id!r}")
        identity = dict(embedder.identity)
        epoch_id = f"vidx_{uuid.uuid4().hex}"
        created_at = utc_now()
        dimensions: int | None = None
        prepared: list[tuple[dict[str, Any], list[float]]] = []
        for start in range(0, len(records), max(1, int(batch_size))):
            batch = records[start : start + max(1, int(batch_size))]
            vectors = embedder.embed_documents([str(record["content"]) for record in batch])
            if len(vectors) != len(batch):
                raise ValueError("embedder returned the wrong number of vectors")
            for record, vector in zip(batch, vectors):
                normalized = _normalize(vector)
                dimensions = dimensions or len(normalized)
                if len(normalized) != dimensions:
                    raise ValueError("embedder returned inconsistent dimensions")
                prepared.append((record, normalized))
        dimensions = dimensions or 0
        identity_sha256 = sha256_hex(canonical_json(identity))
        prepared_snapshot = {
            (
                str(record["id"]),
                str(record["status"]),
                sha256_hex(str(record["content"])),
            )
            for record, _ in prepared
        }
        current_snapshot = {
            (
                str(record["id"]),
                str(record["status"]),
                sha256_hex(str(record["content"])),
            )
            for record in memory.store.list_records(
                subject_id, statuses=INDEXABLE_STATUSES
            )
        }
        if prepared_snapshot != current_snapshot:
            raise RuntimeError(
                "canonical memory changed while embeddings were built; retry the index build"
            )

        previous = self.active_epoch(subject_id)
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO vector_epochs(
                  epoch_id, subject_id, format, provider, model, model_version,
                  identity_json, identity_sha256, dimensions, status, dirty,
                  entry_count, created_at, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'building', 0, ?, ?, NULL)
                """,
                (
                    epoch_id,
                    subject_id,
                    INDEX_FORMAT,
                    str(identity.get("provider", "unknown")),
                    str(identity.get("model", "unknown")),
                    str(identity.get("version", "unknown")),
                    json.dumps(identity, sort_keys=True, separators=(",", ":")),
                    identity_sha256,
                    dimensions,
                    len(prepared),
                    created_at,
                ),
            )
            for record, vector in prepared:
                self._conn.execute(
                    """
                    INSERT INTO vector_entries(
                      epoch_id, subject_id, object_type, object_id,
                      content_sha256, status_at_index, dimensions, vector,
                      created_at
                    ) VALUES (?, ?, 'memory', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        epoch_id,
                        subject_id,
                        record["id"],
                        sha256_hex(str(record["content"])),
                        record["status"],
                        dimensions,
                        _pack(vector),
                        created_at,
                    ),
                )
            if previous is not None:
                self._conn.execute(
                    "UPDATE vector_epochs SET status = 'retired', retired_at = ? WHERE epoch_id = ?",
                    (created_at, previous["epoch_id"]),
                )
            self._conn.execute(
                """
                INSERT INTO vector_subjects(subject_id, active_epoch_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(subject_id) DO UPDATE SET
                  active_epoch_id = excluded.active_epoch_id,
                  updated_at = excluded.updated_at
                """,
                (subject_id, epoch_id, created_at),
            )
            self._conn.execute(
                "UPDATE vector_epochs SET status = 'active', activated_at = ? WHERE epoch_id = ?",
                (created_at, epoch_id),
            )
        pre_cleanup_report = self.verify(
            memory, subject_id, _allow_retired_entries=True
        )
        if not pre_cleanup_report["valid"]:
            with self.transaction():
                if previous is None:
                    self._conn.execute(
                        "DELETE FROM vector_subjects WHERE subject_id = ?",
                        (subject_id,),
                    )
                else:
                    self._conn.execute(
                        """
                        UPDATE vector_subjects SET active_epoch_id = ?, updated_at = ?
                        WHERE subject_id = ?
                        """,
                        (previous["epoch_id"], utc_now(), subject_id),
                    )
                    self._conn.execute(
                        """
                        UPDATE vector_epochs
                        SET status = 'active', retired_at = NULL
                        WHERE epoch_id = ?
                        """,
                        (previous["epoch_id"],),
                    )
                self._conn.execute(
                    "DELETE FROM vector_entries WHERE epoch_id = ?", (epoch_id,)
                )
                self._conn.execute(
                    "DELETE FROM vector_epochs WHERE epoch_id = ?", (epoch_id,)
                )
            raise ValueError(
                "new semantic index failed verification: "
                f"{pre_cleanup_report['failures']}"
            )
        with self.transaction():
            # Retired vectors are disposable. Removing them also ensures a
            # previous epoch cannot retain later-purged personal information.
            self._conn.execute(
                """
                DELETE FROM vector_entries
                WHERE subject_id = ? AND epoch_id <> ?
                """,
                (subject_id, epoch_id),
            )
        verification_report = self.verify(memory, subject_id)
        if not verification_report["valid"]:
            raise ValueError(
                "semantic index failed post-cleanup verification: "
                f"{verification_report['failures']}"
            )
        self.checkpoint_storage()
        memory.store.register_semantic_index(
            subject_id, self.path, active_epoch_id=epoch_id
        )
        report = {
            "format": "aetnamem-index-build-v1",
            "subject_id": subject_id,
            "index_path": self.path,
            "epoch_id": epoch_id,
            "entry_count": len(prepared),
            "dimensions": dimensions,
            "embedder": identity,
            "identity_sha256": identity_sha256,
            "verification_report_sha256": verification_report["report_sha256"],
        }
        report["audit_event_id"] = memory.log_action(
            subject_id,
            "semantic.index_built",
            {
                "epoch_id": epoch_id,
                "entry_count": len(prepared),
                "dimensions": dimensions,
                "identity_sha256": identity_sha256,
                "index_path_sha256": sha256_hex(self.path),
                "verification_report_sha256": report[
                    "verification_report_sha256"
                ],
            },
            actor="indexer",
        )
        return report

    def search(
        self,
        memory: Memory,
        subject_id: str,
        query: str,
        embedder: Embedder,
        *,
        statuses: Sequence[str] | None = None,
        limit: int = 100,
        min_similarity: float = 0.2,
    ) -> list[dict[str, Any]]:
        epoch = self.active_epoch(subject_id)
        if epoch is None:
            raise ValueError(f"no active semantic index for subject {subject_id!r}")
        verify_identity = getattr(embedder, "verify_identity", None)
        if callable(verify_identity):
            verify_identity()
        self._assert_embedder(epoch, embedder)
        query_vector = _normalize(embedder.embed_query(query))
        if len(query_vector) != int(epoch["dimensions"]):
            raise ValueError(
                f"query embedding has {len(query_vector)} dimensions; "
                f"index expects {epoch['dimensions']}"
            )
        rows = self._conn.execute(
            """
            SELECT * FROM vector_entries
            WHERE epoch_id = ? AND subject_id = ?
            ORDER BY object_id
            """,
            (epoch["epoch_id"], subject_id),
        ).fetchall()
        epoch_dimensions = int(epoch["dimensions"])
        records = memory.store.get_records(
            subject_id, [str(row["object_id"]) for row in rows]
        )
        status_filter = set(statuses or INDEXABLE_STATUSES)
        eligible: list[tuple[sqlite3.Row, dict[str, Any]]] = []
        for row in rows:
            record_id = str(row["object_id"])
            row_dimensions = int(row["dimensions"])
            if row_dimensions != epoch_dimensions:
                raise SemanticIndexIntegrityError(
                    "stored vector dimensions do not match the active epoch: "
                    f"record={record_id!r}, stored={row_dimensions}, "
                    f"epoch={epoch_dimensions}"
                )
            record = records.get(record_id)
            validation = _canonical_validation(row, record, subject_id, status_filter)
            if not validation["eligible"]:
                continue
            eligible.append((row, validation))

        similarities = _exact_similarities(
            query_vector,
            [row["vector"] for row, _ in eligible],
            epoch_dimensions,
        )
        candidates: list[dict[str, Any]] = []
        for (row, validation), similarity in zip(eligible, similarities):
            if similarity < float(min_similarity):
                continue
            candidates.append(
                {
                    "record_id": row["object_id"],
                    "similarity": float(similarity),
                    "epoch_id": epoch["epoch_id"],
                    "content_sha256": row["content_sha256"],
                    "canonical_validation": validation,
                }
            )
        candidates.sort(key=lambda item: (-item["similarity"], str(item["record_id"])))
        return [
            {**item, "semantic_rank": rank}
            for rank, item in enumerate(candidates[: max(1, int(limit))], start=1)
        ]

    def active_epoch(self, subject_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT e.* FROM vector_subjects s
            JOIN vector_epochs e ON e.epoch_id = s.active_epoch_id
            WHERE s.subject_id = ?
            """,
            (subject_id,),
        ).fetchone()
        return _epoch(row) if row else None

    def status(self, subject_id: str | None = None) -> dict[str, Any]:
        if subject_id:
            rows = self._conn.execute(
                "SELECT * FROM vector_epochs WHERE subject_id = ? ORDER BY created_at",
                (subject_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM vector_epochs ORDER BY subject_id, created_at"
            ).fetchall()
        return {
            "format": "aetnamem-index-status-v1",
            "index_path": self.path,
            "subjects": {
                str(row["subject_id"]): self.active_epoch(str(row["subject_id"]))
                for row in rows
                if self.active_epoch(str(row["subject_id"])) is not None
            },
            "epochs": [_epoch(row) for row in rows],
        }

    def verify(
        self,
        memory: Memory,
        subject_id: str,
        *,
        _allow_retired_entries: bool = False,
    ) -> dict[str, Any]:
        epoch = self.active_epoch(subject_id)
        if epoch is not None and not _allow_retired_entries:
            canonical_generation = memory.store.record_generation(subject_id)
            index_generation = self._index_generation(subject_id)
            cached = self._conn.execute(
                """
                SELECT report_json FROM verification_cache
                WHERE subject_id = ? AND epoch_id = ?
                  AND canonical_generation = ? AND index_generation = ?
                """,
                (
                    subject_id,
                    epoch["epoch_id"],
                    canonical_generation,
                    index_generation,
                ),
            ).fetchone()
            if cached is not None:
                return json.loads(str(cached["report_json"]))
        failures: list[str] = []
        orphaned: list[str] = []
        tombstoned: list[str] = []
        stale: list[str] = []
        cross_subject: list[str] = []
        coverage_gaps: list[str] = []
        retired_entries: list[str] = []
        if epoch is None:
            failures.append("no active epoch")
            entries: list[sqlite3.Row] = []
        else:
            entries = self._conn.execute(
                "SELECT * FROM vector_entries WHERE epoch_id = ? ORDER BY object_id",
                (epoch["epoch_id"],),
            ).fetchall()
        records = memory.store.get_records(
            subject_id, [str(row["object_id"]) for row in entries]
        )
        indexed_ids: set[str] = set()
        for row in entries:
            record_id = str(row["object_id"])
            indexed_ids.add(record_id)
            record = records.get(record_id)
            if str(row["subject_id"]) != subject_id:
                cross_subject.append(record_id)
                continue
            if record is None:
                orphaned.append(record_id)
                continue
            if record["subject_id"] != subject_id:
                cross_subject.append(record_id)
            if record["status"] == "tombstoned":
                tombstoned.append(record_id)
            if record["status"] != "tombstoned" and sha256_hex(str(record["content"])) != row["content_sha256"]:
                stale.append(record_id)
            if epoch and int(row["dimensions"]) != int(epoch["dimensions"]):
                stale.append(record_id)
        expected = {
            str(record["id"])
            for record in memory.store.list_records(subject_id, statuses=INDEXABLE_STATUSES)
        }
        coverage_gaps = sorted(expected - indexed_ids)
        retired_rows = self._conn.execute(
            """
            SELECT v.object_id FROM vector_entries v
            JOIN vector_epochs e ON e.epoch_id = v.epoch_id
            WHERE v.subject_id = ? AND e.status <> 'active'
            ORDER BY v.object_id
            """,
            (subject_id,),
        ).fetchall()
        retired_entries = [str(row["object_id"]) for row in retired_rows]
        categories = {
            "orphaned_vectors": sorted(set(orphaned)),
            "tombstoned_vectors": sorted(set(tombstoned)),
            "stale_vectors": sorted(set(stale)),
            "cross_subject_vectors": sorted(set(cross_subject)),
            "coverage_gaps": coverage_gaps,
            "retired_epoch_vectors": sorted(set(retired_entries)),
        }
        for name, values in categories.items():
            if name == "retired_epoch_vectors" and _allow_retired_entries:
                continue
            if values:
                failures.append(f"{name}: {len(values)}")
        body = {
            "format": "aetnamem-index-verification-v1",
            "subject_id": subject_id,
            "index_path": self.path,
            "epoch_id": epoch["epoch_id"] if epoch else None,
            "valid": not failures,
            **categories,
            "failures": failures,
            "verified_at": utc_now(),
        }
        body["report_sha256"] = sha256_hex(canonical_json(body))
        if epoch is not None and not _allow_retired_entries:
            # Re-read both counters after verification. If either changed
            # during the scan, do not cache a report for a mixed snapshot.
            ending_canonical_generation = memory.store.record_generation(subject_id)
            ending_index_generation = self._index_generation(subject_id)
            if (
                ending_canonical_generation == canonical_generation
                and ending_index_generation == index_generation
            ):
                self._conn.execute(
                    """
                    INSERT INTO verification_cache(
                      subject_id, epoch_id, canonical_generation,
                      index_generation, report_json, report_sha256, verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                      subject_id, epoch_id, canonical_generation, index_generation
                    ) DO UPDATE SET
                      report_json = excluded.report_json,
                      report_sha256 = excluded.report_sha256,
                      verified_at = excluded.verified_at
                    """,
                    (
                        subject_id,
                        epoch["epoch_id"],
                        canonical_generation,
                        index_generation,
                        json.dumps(body, sort_keys=True, separators=(",", ":")),
                        body["report_sha256"],
                        body["verified_at"],
                    ),
                )
        return body

    def purge(self, subject_id: str, record_ids: Sequence[str]) -> dict[str, Any]:
        ids = sorted({str(value) for value in record_ids})
        if not ids:
            return {
                "status": "not_required",
                "removed_entries": 0,
                "record_ids": [],
                "epochs_touched": [],
                "verified_absent": True,
            }
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"""
            SELECT DISTINCT epoch_id FROM vector_entries
            WHERE subject_id = ? AND object_id IN ({placeholders})
            ORDER BY epoch_id
            """,
            (subject_id, *ids),
        ).fetchall()
        epochs = [str(row["epoch_id"]) for row in rows]
        with self.transaction():
            cursor = self._conn.execute(
                f"""
                DELETE FROM vector_entries
                WHERE subject_id = ? AND object_id IN ({placeholders})
                """,
                (subject_id, *ids),
            )
            if epochs:
                epoch_placeholders = ",".join("?" for _ in epochs)
                self._conn.execute(
                    f"""
                    UPDATE vector_epochs SET dirty = 1,
                      entry_count = (
                        SELECT COUNT(*) FROM vector_entries
                        WHERE vector_entries.epoch_id = vector_epochs.epoch_id
                      )
                    WHERE epoch_id IN ({epoch_placeholders})
                    """,
                    epochs,
                )
        remaining = self._conn.execute(
            f"""
            SELECT COUNT(*) AS count FROM vector_entries
            WHERE subject_id = ? AND object_id IN ({placeholders})
            """,
            (subject_id, *ids),
        ).fetchone()
        result = {
            "status": "verified_absent" if int(remaining["count"]) == 0 else "failed",
            "removed_entries": int(cursor.rowcount),
            "record_ids": ids,
            "epochs_touched": epochs,
            "verified_absent": int(remaining["count"]) == 0,
            "verified_at": utc_now(),
        }
        result["result_sha256"] = sha256_hex(canonical_json(result))
        return result

    def checkpoint_storage(self) -> None:
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _assert_embedder(self, epoch: dict[str, Any], embedder: Embedder) -> None:
        current = dict(embedder.identity)
        stored = epoch["identity"]
        for key in (
            "provider",
            "model",
            "version",
            "model_digest",
            "endpoint",
            "normalization",
        ):
            if str(current.get(key)) != str(stored.get(key)):
                raise ValueError(
                    f"embedder {key} mismatch: index={stored.get(key)!r}, "
                    f"query={current.get(key)!r}"
                )

    def _index_generation(self, subject_id: str) -> int:
        row = self._conn.execute(
            "SELECT generation FROM vector_generations WHERE subject_id = ?",
            (subject_id,),
        ).fetchone()
        return int(row["generation"]) if row else 0

    def _migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vector_epochs (
              epoch_id TEXT PRIMARY KEY,
              subject_id TEXT NOT NULL,
              format TEXT NOT NULL,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              model_version TEXT NOT NULL,
              identity_json TEXT NOT NULL,
              identity_sha256 TEXT NOT NULL,
              dimensions INTEGER NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('building', 'active', 'retired')),
              dirty INTEGER NOT NULL DEFAULT 0,
              entry_count INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              activated_at TEXT,
              retired_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_vector_epochs_subject
              ON vector_epochs(subject_id, status, created_at);

            CREATE TABLE IF NOT EXISTS vector_subjects (
              subject_id TEXT PRIMARY KEY,
              active_epoch_id TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(active_epoch_id) REFERENCES vector_epochs(epoch_id)
            );

            CREATE TABLE IF NOT EXISTS vector_entries (
              epoch_id TEXT NOT NULL,
              subject_id TEXT NOT NULL,
              object_type TEXT NOT NULL,
              object_id TEXT NOT NULL,
              content_sha256 TEXT NOT NULL,
              status_at_index TEXT NOT NULL,
              dimensions INTEGER NOT NULL,
              vector BLOB NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(epoch_id, object_type, object_id),
              FOREIGN KEY(epoch_id) REFERENCES vector_epochs(epoch_id)
            );

            CREATE INDEX IF NOT EXISTS idx_vector_entries_subject
              ON vector_entries(subject_id, epoch_id, object_id);

            CREATE TABLE IF NOT EXISTS vector_generations (
              subject_id TEXT PRIMARY KEY,
              generation INTEGER NOT NULL DEFAULT 0
            );

            CREATE TRIGGER IF NOT EXISTS vector_generation_insert
            AFTER INSERT ON vector_entries BEGIN
              INSERT INTO vector_generations(subject_id, generation)
              VALUES (NEW.subject_id, 1)
              ON CONFLICT(subject_id) DO UPDATE
                SET generation = generation + 1;
            END;

            CREATE TRIGGER IF NOT EXISTS vector_generation_delete
            AFTER DELETE ON vector_entries BEGIN
              INSERT INTO vector_generations(subject_id, generation)
              VALUES (OLD.subject_id, 1)
              ON CONFLICT(subject_id) DO UPDATE
                SET generation = generation + 1;
            END;

            CREATE TRIGGER IF NOT EXISTS vector_generation_update_same_subject
            AFTER UPDATE ON vector_entries
            WHEN OLD.subject_id = NEW.subject_id BEGIN
              INSERT INTO vector_generations(subject_id, generation)
              VALUES (NEW.subject_id, 1)
              ON CONFLICT(subject_id) DO UPDATE
                SET generation = generation + 1;
            END;

            CREATE TRIGGER IF NOT EXISTS vector_generation_update_subject
            AFTER UPDATE ON vector_entries
            WHEN OLD.subject_id <> NEW.subject_id BEGIN
              INSERT INTO vector_generations(subject_id, generation)
              VALUES (OLD.subject_id, 1)
              ON CONFLICT(subject_id) DO UPDATE
                SET generation = generation + 1;
              INSERT INTO vector_generations(subject_id, generation)
              VALUES (NEW.subject_id, 1)
              ON CONFLICT(subject_id) DO UPDATE
                SET generation = generation + 1;
            END;

            CREATE TABLE IF NOT EXISTS verification_cache (
              subject_id TEXT NOT NULL,
              epoch_id TEXT NOT NULL,
              canonical_generation INTEGER NOT NULL,
              index_generation INTEGER NOT NULL,
              report_json TEXT NOT NULL,
              report_sha256 TEXT NOT NULL,
              verified_at TEXT NOT NULL,
              PRIMARY KEY(
                subject_id, epoch_id, canonical_generation, index_generation
              ),
              FOREIGN KEY(epoch_id) REFERENCES vector_epochs(epoch_id)
            );
            """
        )
        self._conn.execute(
            """
            INSERT INTO schema_meta(key, value) VALUES ('semantic_index_schema', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (INDEX_SCHEMA_VERSION,),
        )


def _canonical_validation(
    row: sqlite3.Row,
    record: dict[str, Any] | None,
    subject_id: str,
    statuses: set[str],
) -> dict[str, Any]:
    exists = record is not None
    subject_matched = bool(record and record.get("subject_id") == subject_id)
    status = str(record.get("status")) if record else None
    status_eligible = status in statuses if status is not None else False
    digest_matched = bool(
        record
        and status != "tombstoned"
        and sha256_hex(str(record.get("content") or "")) == row["content_sha256"]
    )
    return {
        "exists": exists,
        "subject_matched": subject_matched,
        "status": status,
        "status_eligible": status_eligible,
        "digest_matched": digest_matched,
        "eligible": exists and subject_matched and status_eligible and digest_matched,
    }


def _epoch(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["dirty"] = bool(value["dirty"])
    value["identity"] = json.loads(value.pop("identity_json"))
    return value


def _pack(vector: Sequence[float]) -> bytes:
    values = array("f", [float(value) for value in vector])
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def _unpack(blob: bytes, dimensions: int) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != dimensions:
        raise ValueError("stored vector dimensions do not match its payload")
    result = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result):
        raise ValueError("stored vector contains a non-finite value")
    return result


def _normalize(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("embedding must be a finite, non-empty vector")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        raise ValueError("embedding vector has zero magnitude")
    return [value / norm for value in values]


def _exact_similarities(
    query_vector: Sequence[float],
    blobs: Sequence[bytes],
    dimensions: int,
) -> list[float]:
    """Compute exact dot products, using an optional vectorized block at scale."""
    if len(blobs) >= 256:
        try:
            import numpy as np
        except ImportError:
            pass
        else:
            matrix = np.frombuffer(b"".join(blobs), dtype="<f4")
            expected = len(blobs) * dimensions
            if int(matrix.size) != expected:
                raise SemanticIndexIntegrityError(
                    "stored vector payload length does not match the active epoch"
                )
            matrix = matrix.reshape((len(blobs), dimensions))
            if not bool(np.isfinite(matrix).all()):
                raise SemanticIndexIntegrityError(
                    "stored vector contains a non-finite value"
                )
            query = np.asarray(query_vector, dtype=np.float64)
            return [float(value) for value in matrix.dot(query)]
    return [
        sum(
            left * right
            for left, right in zip(query_vector, _unpack(blob, dimensions))
        )
        for blob in blobs
    ]
