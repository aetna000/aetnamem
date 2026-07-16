"""Derived, governed graph index over canonical memory records.

The graph never owns truth: every edge cites a record, and every record cites
an episode. IDs are content-derived so dropping and rebuilding the index is
deterministic. Only active graph objects enter the FTS seeder or traversal.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.retrieve import query_tokens
from aetnamem.store import SQLiteStore


GRAPH_EXTRACTOR_VERSION = "graph-rules-v1"
DEFAULT_SEED_LIMIT = 16
DEFAULT_FRONTIER_CAP = 64
DEFAULT_MAX_DEPTH = 2

_POSSESSIVE_RE = re.compile(
    r"^(?P<src>User|[A-Z][^.!?]{0,80}?)'s\s+"
    r"(?P<relation>[^.!?]{1,80}?)\s+(?:is|are)\s+(?P<dst>.+?)[.!?]*$"
)
_USER_AVOIDS_RE = re.compile(r"^User avoids\s+(?P<dst>.+?)[.!?]*$", re.I)
_NAMED_RELATION_RE = re.compile(
    r"^(?P<src>[A-Z][A-Za-z0-9 ._-]{0,80}?)\s+"
    r"(?P<verb>prefers|lives in|works with|reports to|manages|uses|likes|dislikes)\s+"
    r"(?P<dst>.+?)[.!?]*$",
    re.I,
)

_RELATION_MAP = {
    "boss": "boss",
    "manager": "manager",
    "preferred airport": "preferred_airport",
    "favorite airport": "preferred_airport",
    "favorite color": "favorite_color",
    "home city": "home_city",
    "backup email": "backup_email",
    "email": "email",
    "phone": "phone_number",
    "phone number": "phone_number",
    "employer": "employer",
    "role": "role",
    "report file": "stored_in",
    "preferred editor": "preferred_editor",
    "dog": "pet",
    "dog name": "pet_name",
    "shoe size": "shoe_size",
    "lives in": "lives_in",
    "works with": "works_with",
    "reports to": "reports_to",
    "manages": "manages",
    "uses": "uses",
    "likes": "likes",
    "dislikes": "dislikes",
    "avoids": "avoids",
    "prefers": "prefers",
}

_MULTI_VALUED = frozenset(
    {"works_with", "manages", "likes", "dislikes", "avoids", "related_to"}
)

_RELATION_PRIORS = {
    "preferred_airport": 1.0,
    "boss": 0.98,
    "manager": 0.98,
    "reports_to": 0.95,
    "lives_in": 0.92,
    "home_city": 0.92,
    "works_with": 0.82,
    "stored_in": 0.9,
    "related_to": 0.72,
}

_TRUST_WEIGHTS = {
    "trusted_user": 1.0,
    "user_confirmed": 0.95,
    "derived": 0.65,
    "untrusted_content": 0.0,
}


@dataclass(frozen=True)
class GraphFact:
    source: str
    relation: str
    relation_label: str
    destination: str
    source_kind: str = "person"
    destination_kind: str = "other"


@dataclass(frozen=True)
class GraphRecall:
    candidates: tuple[dict[str, Any], ...]
    seeds: tuple[dict[str, Any], ...]
    pruned_digest: str
    visited_edges: int
    seed_limit: int
    frontier_cap: int
    max_depth: int


class GraphIndex:
    """Maintain and query graph tables owned by an :class:`SQLiteStore`."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.conn = store._conn  # graph is an internal index sharing the store transaction

    def index_record(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        fact = extract_graph_fact(record)
        if fact is None or record.get("status") == "tombstoned":
            return []
        subject_id = str(record["subject_id"])
        record_id = str(record["id"])
        existing = self.conn.execute(
            "SELECT * FROM edges WHERE subject_id = ? AND record_id = ?",
            (subject_id, record_id),
        ).fetchone()
        if existing is not None:
            if existing["extractor_version"] != GRAPH_EXTRACTOR_VERSION:
                return self._reindex_existing_edge(dict(existing), record)
            return self._sync_existing_edge(dict(existing), record)

        status = str(record.get("status") or "active")
        graph_status = status if status in {"active", "quarantined", "superseded"} else "tombstoned"
        entity_status = "quarantined" if graph_status == "quarantined" else "active"
        created_at = str(record.get("created_at") or "")
        mutations: list[dict[str, Any]] = []

        src = self._ensure_entity(
            subject_id,
            fact.source,
            fact.source_kind,
            status=entity_status,
            source_record=None if _normalize(fact.source) == "you" else record_id,
            created_at=created_at,
            mutations=mutations,
        )
        dst = self._ensure_entity(
            subject_id,
            fact.destination,
            fact.destination_kind,
            status=entity_status,
            source_record=record_id,
            created_at=created_at,
            mutations=mutations,
        )

        if _normalize(fact.source) == "you":
            for surface in ("user", "me", "myself"):
                self._ensure_alias(
                    subject_id,
                    src["id"],
                    surface,
                    source_record=None,
                    trust_tier="trusted_user",
                    status="active",
                    created_at=created_at,
                    mutations=mutations,
                )
            self._ensure_alias(
                subject_id,
                dst["id"],
                f"my {fact.relation_label}",
                source_record=record_id,
                trust_tier=str(record.get("trust_tier") or "derived"),
                status=entity_status,
                created_at=created_at,
                mutations=mutations,
            )

        edge_id = _stable_id(
            "edg", subject_id, record_id, src["id"], fact.relation, dst["id"]
        )
        superseded_edges: list[str] = []
        prior_record_id = record.get("supersedes_id")
        if prior_record_id:
            prior = self.conn.execute(
                "SELECT id FROM edges WHERE subject_id = ? AND record_id = ?",
                (subject_id, prior_record_id),
            ).fetchone()
            if prior is not None:
                superseded_edges.append(str(prior["id"]))
        if graph_status == "active" and fact.relation not in _MULTI_VALUED:
            rows = self.conn.execute(
                """
                SELECT id FROM edges
                WHERE subject_id = ? AND src_entity = ? AND relation = ?
                  AND status = 'active'
                ORDER BY created_at, id
                """,
                (subject_id, src["id"], fact.relation),
            ).fetchall()
            active_edge_ids = [str(row["id"]) for row in rows]
            superseded_edges.extend(
                edge_id for edge_id in active_edge_ids if edge_id not in superseded_edges
            )
            for old_id in active_edge_ids:
                self.conn.execute(
                    """
                    UPDATE edges SET status = 'superseded', updated_at = ?
                    WHERE id = ?
                    """,
                    (created_at, old_id),
                )
                self._delete_fts("edge", old_id)
                mutations.append(
                    {"event_type": "edge.superseded", "object_id": old_id, "by": edge_id}
                )

        self.conn.execute(
            """
            INSERT INTO edges (
              id, subject_id, src_entity, relation, relation_label,
              dst_entity, dst_value, record_id, trust_tier, confidence,
              status, supersedes_id, extractor_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                edge_id,
                subject_id,
                src["id"],
                fact.relation,
                fact.relation_label,
                dst["id"],
                record_id,
                record.get("trust_tier") or "derived",
                record.get("confidence"),
                graph_status,
                superseded_edges[-1] if superseded_edges else None,
                GRAPH_EXTRACTOR_VERSION,
                created_at,
            ),
        )
        if graph_status == "active":
            self._upsert_edge_fts(edge_id)
        mutations.append(
            {
                "event_type": "edge.asserted",
                "object_id": edge_id,
                "record_id": record_id,
                "src_entity": src["id"],
                "dst_entity": dst["id"],
                "relation": fact.relation,
                "status": graph_status,
            }
        )
        return mutations

    def supersede_records(
        self, subject_id: str, record_ids: list[str], superseded_by_record: str
    ) -> list[dict[str, Any]]:
        mutations: list[dict[str, Any]] = []
        superseded_edge_ids: list[str] = []
        for record_id in record_ids:
            row = self.conn.execute(
                "SELECT id FROM edges WHERE subject_id = ? AND record_id = ? AND status = 'active'",
                (subject_id, record_id),
            ).fetchone()
            if row is None:
                continue
            edge_id = str(row["id"])
            superseded_edge_ids.append(edge_id)
            self.conn.execute(
                "UPDATE edges SET status = 'superseded', updated_at = datetime('now') WHERE id = ?",
                (edge_id,),
            )
            self._delete_fts("edge", edge_id)
            aliases = self.conn.execute(
                "SELECT id FROM entity_aliases WHERE source_record = ? AND status = 'active'",
                (record_id,),
            ).fetchall()
            for alias in aliases:
                self.conn.execute(
                    "UPDATE entity_aliases SET status = 'superseded' WHERE id = ?",
                    (alias["id"],),
                )
                self._delete_fts("alias", str(alias["id"]))
            mutations.append(
                {
                    "event_type": "edge.superseded",
                    "object_id": edge_id,
                    "by_record": superseded_by_record,
                }
            )
        if superseded_edge_ids:
            self.conn.execute(
                """
                UPDATE edges SET supersedes_id = ?
                WHERE subject_id = ? AND record_id = ?
                """,
                (superseded_edge_ids[-1], subject_id, superseded_by_record),
            )
        return mutations

    def tombstone_records(
        self, subject_id: str, record_ids: list[str]
    ) -> list[dict[str, Any]]:
        if not record_ids:
            return []
        mutations: list[dict[str, Any]] = []
        for record_id in record_ids:
            edges = self.conn.execute(
                "SELECT id, src_entity, dst_entity FROM edges WHERE subject_id = ? AND record_id = ?",
                (subject_id, record_id),
            ).fetchall()
            for edge in edges:
                edge_id = str(edge["id"])
                self.conn.execute(
                    """
                    UPDATE edges
                    SET status = 'tombstoned', relation = '[purged]',
                        relation_label = '[purged]', dst_entity = NULL,
                        dst_value = NULL, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (edge_id,),
                )
                self._delete_fts("edge", edge_id)
                mutations.append({"event_type": "edge.tombstoned", "object_id": edge_id})

            aliases = self.conn.execute(
                "SELECT id FROM entity_aliases WHERE subject_id = ? AND source_record = ?",
                (subject_id, record_id),
            ).fetchall()
            for alias in aliases:
                alias_id = str(alias["id"])
                self.conn.execute(
                    """
                    UPDATE entity_aliases
                    SET status = 'tombstoned', surface = '', normalized = ?
                    WHERE id = ?
                    """,
                    (f"purged:{alias_id}", alias_id),
                )
                self._delete_fts("alias", alias_id)
                mutations.append(
                    {"event_type": "alias.tombstoned", "object_id": alias_id}
                )

            entities = self.conn.execute(
                "SELECT id FROM entities WHERE subject_id = ? AND source_record = ?",
                (subject_id, record_id),
            ).fetchall()
            for entity in entities:
                entity_id = str(entity["id"])
                referenced = self.conn.execute(
                    """
                    SELECT 1 FROM edges
                    WHERE subject_id = ? AND status IN ('active', 'quarantined')
                      AND (src_entity = ? OR dst_entity = ?)
                    LIMIT 1
                    """,
                    (subject_id, entity_id, entity_id),
                ).fetchone()
                if referenced is not None:
                    continue
                self.conn.execute(
                    """
                    UPDATE entities
                    SET status = 'tombstoned', canonical = '', normalized = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (f"purged:{entity_id}", entity_id),
                )
                self._delete_fts("entity", entity_id)
                mutations.append(
                    {"event_type": "entity.tombstoned", "object_id": entity_id}
                )
        mutations.extend(self.purge_archived_records(subject_id, record_ids))
        return mutations

    def purge_archived_records(
        self, subject_id: str, record_ids: list[str]
    ) -> list[dict[str, Any]]:
        if not record_ids:
            return []
        placeholders = ",".join("?" for _ in record_ids)
        rows = self.conn.execute(
            f"""
            SELECT m.object_id, m.partition_id, p.path, p.content_sha256
            FROM graph_archive_members m
            JOIN graph_archive_partitions p ON p.id = m.partition_id
            WHERE m.subject_id = ? AND m.source_record_id IN ({placeholders})
            ORDER BY m.partition_id, m.object_id
            """,
            (subject_id, *record_ids),
        ).fetchall()
        by_partition: dict[str, dict[str, Any]] = {}
        for row in rows:
            entry = by_partition.setdefault(
                str(row["partition_id"]),
                {
                    "path": str(row["path"]),
                    "content_sha256": str(row["content_sha256"]),
                    "object_ids": [],
                },
            )
            entry["object_ids"].append(str(row["object_id"]))

        for partition_id, partition in by_partition.items():
            path = Path(partition["path"])
            if (
                not path.is_file()
                or sha256(path.read_bytes()).hexdigest()
                != partition["content_sha256"]
            ):
                raise ValueError(
                    f"cannot purge missing or modified archive partition {partition_id}"
                )

        mutations: list[dict[str, Any]] = []
        for partition_id, partition in by_partition.items():
            path = Path(partition["path"])
            object_ids = list(partition["object_ids"])
            object_placeholders = ",".join("?" for _ in object_ids)
            archive = sqlite3.connect(path)
            try:
                archive.execute("PRAGMA secure_delete = ON")
                archive.execute(
                    f"DELETE FROM edge_history WHERE id IN ({object_placeholders})",
                    object_ids,
                )
                archive.commit()
                archive.execute("VACUUM")
                row_count = int(
                    archive.execute("SELECT COUNT(*) FROM edge_history").fetchone()[0]
                )
            finally:
                archive.close()
            digest = sha256(path.read_bytes()).hexdigest()
            self.conn.execute(
                """
                UPDATE graph_archive_partitions
                SET row_count = ?, content_sha256 = ?, created_at = datetime('now')
                WHERE id = ?
                """,
                (row_count, digest, partition_id),
            )
            self.conn.execute(
                f"""
                DELETE FROM graph_archive_members
                WHERE partition_id = ? AND object_id IN ({object_placeholders})
                """,
                (partition_id, *object_ids),
            )
            mutations.extend(
                {
                    "event_type": "edge.archive_purged",
                    "object_id": object_id,
                    "partition_id": partition_id,
                    "partition_sha256": digest,
                }
                for object_id in object_ids
            )
        return mutations

    def backfill(self, subject_id: str) -> dict[str, Any]:
        records = self.store.list_records(subject_id, statuses=None)
        before = self.counts(subject_id)
        mutations: list[dict[str, Any]] = []
        indexed = 0
        for record in records:
            if record["status"] == "tombstoned":
                continue
            archived = self.conn.execute(
                """
                SELECT 1 FROM graph_archive_members
                WHERE subject_id = ? AND source_record_id = ?
                LIMIT 1
                """,
                (subject_id, record["id"]),
            ).fetchone()
            if archived is not None:
                continue
            changes = self.index_record(record)
            if any(item["event_type"] == "edge.asserted" for item in changes):
                indexed += 1
            mutations.extend(changes)
        return {
            "extractor_version": GRAPH_EXTRACTOR_VERSION,
            "records_seen": len(records),
            "records_indexed": indexed,
            "before": before,
            "after": self.counts(subject_id),
            "mutations": mutations,
        }

    def clear(self, subject_id: str) -> None:
        if getattr(self.store, "_graph_fts_enabled", False):
            self.store._delete_graph_fts_subject(subject_id)
        self.conn.execute(
            "DELETE FROM graph_merge_proposals WHERE subject_id = ?", (subject_id,)
        )
        self.conn.execute("DELETE FROM edges WHERE subject_id = ?", (subject_id,))
        self.conn.execute("DELETE FROM entity_aliases WHERE subject_id = ?", (subject_id,))
        self.conn.execute("DELETE FROM entities WHERE subject_id = ?", (subject_id,))

    def propose_entity_merges(self, subject_id: str) -> list[dict[str, Any]]:
        """Create conservative, reviewer-gated proposals from exact names/aliases."""
        entities = {
            str(row["id"]): dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM entities
                WHERE subject_id = ? AND status = 'active'
                ORDER BY id
                """,
                (subject_id,),
            ).fetchall()
        }
        aliases = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM entity_aliases
                WHERE subject_id = ? AND status IN ('active', 'superseded')
                ORDER BY id
                """,
                (subject_id,),
            ).fetchall()
        ]
        keys: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for entity_id, entity in entities.items():
            normalized = str(entity["normalized"])
            if normalized != "you":
                keys.setdefault((str(entity["kind"]), normalized), {})[entity_id] = {
                    "canonical": True,
                    "records": {entity.get("source_record")},
                }
        for alias in aliases:
            entity = entities.get(str(alias["entity_id"]))
            normalized = str(alias["normalized"])
            if entity is None or normalized in {"user", "me", "myself"}:
                continue
            entry = keys.setdefault((str(entity["kind"]), normalized), {}).setdefault(
                str(alias["entity_id"]), {"canonical": False, "records": set()}
            )
            entry["records"].add(alias.get("source_record"))

        proposals: list[dict[str, Any]] = []
        for (kind, surface), matches in sorted(keys.items()):
            entity_ids = sorted(matches)
            for left_index, left_id in enumerate(entity_ids):
                for right_id in entity_ids[left_index + 1 :]:
                    left, right = sorted((left_id, right_id))
                    evidence = sorted(
                        str(record_id)
                        for record_id in (
                            matches[left_id]["records"] | matches[right_id]["records"]
                        )
                        if record_id
                    )
                    confidence = (
                        0.99
                        if matches[left_id]["canonical"]
                        and matches[right_id]["canonical"]
                        else 0.96
                        if matches[left_id]["canonical"]
                        or matches[right_id]["canonical"]
                        else 0.93
                    )
                    proposal_id = _stable_id("gmp", subject_id, left, right)
                    cursor = self.conn.execute(
                        """
                        INSERT OR IGNORE INTO graph_merge_proposals (
                          id, subject_id, left_entity, right_entity, confidence,
                          reason, evidence_record_ids, status, winner_entity,
                          proposed_at, decided_at, decided_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL,
                                  datetime('now'), NULL, NULL)
                        """,
                        (
                            proposal_id,
                            subject_id,
                            left,
                            right,
                            confidence,
                            f"exact {kind} name or alias: {surface}",
                            canonical_json(evidence),
                        ),
                    )
                    if cursor.rowcount:
                        proposals.append(
                            {
                                "event_type": "entity.merge_proposed",
                                "object_id": proposal_id,
                                "left_entity": left,
                                "right_entity": right,
                                "confidence": confidence,
                                "evidence_record_ids": evidence,
                            }
                        )
        return proposals

    def list_merge_proposals(
        self, subject_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        params: list[Any] = [subject_id]
        status_clause = ""
        if status:
            status_clause = "AND p.status = ?"
            params.append(status)
        rows = self.conn.execute(
            f"""
            SELECT p.*, left_e.canonical AS left_canonical,
                   right_e.canonical AS right_canonical,
                   left_e.kind AS entity_kind
            FROM graph_merge_proposals p
            JOIN entities left_e ON left_e.id = p.left_entity
            JOIN entities right_e ON right_e.id = p.right_entity
            WHERE p.subject_id = ? {status_clause}
            ORDER BY p.proposed_at, p.id
            """,
            params,
        ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["evidence_record_ids"] = json.loads(value["evidence_record_ids"])
            values.append(value)
        return values

    def decide_merge(
        self,
        subject_id: str,
        proposal_id: str,
        *,
        approve: bool,
        actor: str,
        winner_entity: str | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT * FROM graph_merge_proposals
            WHERE id = ? AND subject_id = ? AND status = 'pending'
            """,
            (proposal_id, subject_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"merge proposal {proposal_id} is not pending")
        proposal = dict(row)
        if not approve:
            self.conn.execute(
                """
                UPDATE graph_merge_proposals
                SET status = 'rejected', decided_at = datetime('now'), decided_by = ?
                WHERE id = ?
                """,
                (actor, proposal_id),
            )
            return {
                "event_type": "entity.merge_rejected",
                "object_id": proposal_id,
                "left_entity": proposal["left_entity"],
                "right_entity": proposal["right_entity"],
            }

        allowed = {str(proposal["left_entity"]), str(proposal["right_entity"])}
        winner = winner_entity or str(proposal["left_entity"])
        if winner not in allowed:
            raise ValueError("winner_entity must be one of the proposed entities")
        loser = next(entity_id for entity_id in allowed if entity_id != winner)
        entity_rows = self.conn.execute(
            "SELECT id, normalized, kind, status FROM entities WHERE id IN (?, ?)",
            (winner, loser),
        ).fetchall()
        entities = {str(item["id"]): dict(item) for item in entity_rows}
        if len(entities) != 2 or any(item["status"] != "active" for item in entities.values()):
            raise ValueError("both merge entities must still be active")
        if entities[winner]["kind"] != entities[loser]["kind"]:
            raise ValueError("entities of different kinds cannot be merged")
        if "you" in {entities[winner]["normalized"], entities[loser]["normalized"]}:
            raise ValueError("the root user entity cannot be merged")
        self.conn.execute(
            """
            UPDATE entities
            SET status = 'merged', merged_into = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (winner, loser),
        )
        self._delete_fts("entity", loser)
        self.conn.execute(
            """
            UPDATE graph_merge_proposals
            SET status = 'approved', winner_entity = ?, decided_at = datetime('now'),
                decided_by = ?
            WHERE id = ?
            """,
            (winner, actor, proposal_id),
        )
        return {
            "event_type": "entity.merged",
            "object_id": proposal_id,
            "winner_entity": winner,
            "merged_entity": loser,
        }

    def revert_merge(
        self, subject_id: str, proposal_id: str, *, actor: str
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT * FROM graph_merge_proposals
            WHERE id = ? AND subject_id = ? AND status = 'approved'
            """,
            (proposal_id, subject_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"merge proposal {proposal_id} is not approved")
        proposal = dict(row)
        winner = str(proposal["winner_entity"])
        loser = (
            str(proposal["right_entity"])
            if str(proposal["left_entity"]) == winner
            else str(proposal["left_entity"])
        )
        entity = self.conn.execute(
            "SELECT canonical, merged_into, status FROM entities WHERE id = ?",
            (loser,),
        ).fetchone()
        if (
            entity is None
            or entity["status"] != "merged"
            or entity["merged_into"] != winner
            or not entity["canonical"]
        ):
            raise ValueError("merged entity no longer points to the approved winner")
        self.conn.execute(
            """
            UPDATE entities
            SET status = 'active', merged_into = NULL, updated_at = datetime('now')
            WHERE id = ?
            """,
            (loser,),
        )
        self._upsert_fts("entity", loser, subject_id, str(entity["canonical"]))
        self.conn.execute(
            """
            UPDATE graph_merge_proposals
            SET status = 'reverted', decided_at = datetime('now'), decided_by = ?
            WHERE id = ?
            """,
            (actor, proposal_id),
        )
        return {
            "event_type": "entity.merge_reverted",
            "object_id": proposal_id,
            "winner_entity": winner,
            "restored_entity": loser,
        }

    def archive_history(
        self,
        subject_id: str,
        archive_root: str | Path,
        *,
        before: str,
        prune: bool = True,
        limit: int = 10_000,
    ) -> dict[str, Any]:
        """Partition inactive derived edges into verifiable subject/year DBs."""
        limit = max(1, min(int(limit), 100_000))
        rows = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM edges
                WHERE subject_id = ?
                  AND status IN ('superseded', 'tombstoned')
                  AND created_at < ?
                ORDER BY created_at, id
                LIMIT ?
                """,
                (subject_id, before, limit),
            ).fetchall()
        ]
        by_year: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            try:
                year = int(str(row["created_at"])[:4])
            except ValueError:
                year = 0
            by_year.setdefault(year, []).append(row)

        root = Path(archive_root).expanduser()
        subject_dir = root / sha256_hex(subject_id)[:16]
        subject_dir.mkdir(parents=True, exist_ok=True)
        partitions: list[dict[str, Any]] = []
        archived_ids: list[str] = []
        for year, partition_rows in sorted(by_year.items()):
            path = subject_dir / f"{year or 'unknown'}.db"
            archive = sqlite3.connect(path)
            try:
                archive.execute(
                    """
                    CREATE TABLE IF NOT EXISTS edge_history (
                      id TEXT PRIMARY KEY,
                      subject_id TEXT NOT NULL,
                      payload TEXT NOT NULL,
                      archived_at TEXT NOT NULL
                    )
                    """
                )
                for row in partition_rows:
                    archive.execute(
                        """
                        INSERT OR REPLACE INTO edge_history (
                          id, subject_id, payload, archived_at
                        ) VALUES (?, ?, ?, datetime('now'))
                        """,
                        (row["id"], subject_id, canonical_json(row)),
                    )
                archive.commit()
                total_rows = int(
                    archive.execute(
                        "SELECT COUNT(*) FROM edge_history WHERE subject_id = ?",
                        (subject_id,),
                    ).fetchone()[0]
                )
            finally:
                archive.close()
            digest = sha256(path.read_bytes()).hexdigest()
            partition_id = _stable_id("gap", subject_id, str(year), str(path.resolve()))
            self.conn.execute(
                """
                INSERT INTO graph_archive_partitions (
                  id, subject_id, partition_year, path, cutoff, row_count,
                  content_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(subject_id, partition_year, path) DO UPDATE SET
                  cutoff = excluded.cutoff,
                  row_count = excluded.row_count,
                  content_sha256 = excluded.content_sha256,
                  created_at = excluded.created_at
                """,
                (
                    partition_id,
                    subject_id,
                    year,
                    str(path.resolve()),
                    before,
                    total_rows,
                    digest,
                ),
            )
            ids = [str(row["id"]) for row in partition_rows]
            for row in partition_rows:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO graph_archive_members (
                      subject_id, object_type, object_id, source_record_id,
                      partition_id, archived_at
                    ) VALUES (?, 'edge', ?, ?, ?, datetime('now'))
                    """,
                    (subject_id, row["id"], row["record_id"], partition_id),
                )
            archived_ids.extend(ids)
            partitions.append(
                {
                    "id": partition_id,
                    "year": year,
                    "path": str(path.resolve()),
                    "row_count": total_rows,
                    "content_sha256": digest,
                    "archived_edge_ids_sha256": sha256_hex(canonical_json(sorted(ids))),
                }
            )

        if prune and archived_ids:
            placeholders = ",".join("?" for _ in archived_ids)
            self.conn.execute(
                f"UPDATE edges SET supersedes_id = NULL WHERE supersedes_id IN ({placeholders})",
                archived_ids,
            )
            if getattr(self.store, "_graph_fts_enabled", False):
                for edge_id in archived_ids:
                    self.store._delete_graph_fts("edge", edge_id)
            self.conn.execute(
                f"DELETE FROM edges WHERE id IN ({placeholders})", archived_ids
            )
        return {
            "before": before,
            "pruned": bool(prune),
            "batch_limit": limit,
            "archived_edges": len(archived_ids),
            "batch_full": len(rows) == limit,
            "partitions": partitions,
        }

    def list_archives(
        self, subject_id: str, *, verify: bool = False
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM graph_archive_partitions
            WHERE subject_id = ? ORDER BY partition_year, path
            """,
            (subject_id,),
        ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            path = Path(str(value["path"]))
            value["available"] = path.is_file()
            value["digest_valid"] = (
                sha256(path.read_bytes()).hexdigest() == value["content_sha256"]
                if verify and path.is_file()
                else None
            )
            values.append(value)
        return values

    def read_archive(
        self, subject_id: str, *, partition_year: int | None = None
    ) -> list[dict[str, Any]]:
        archives = self.list_archives(subject_id, verify=True)
        results: list[dict[str, Any]] = []
        for partition in archives:
            if partition_year is not None and partition["partition_year"] != partition_year:
                continue
            if not partition["digest_valid"]:
                raise ValueError(f"archive partition {partition['id']} is missing or modified")
            archive = sqlite3.connect(str(partition["path"]))
            try:
                rows = archive.execute(
                    """
                    SELECT payload FROM edge_history
                    WHERE subject_id = ? ORDER BY id
                    """,
                    (subject_id,),
                ).fetchall()
                results.extend(json.loads(row[0]) for row in rows)
            finally:
                archive.close()
        results.sort(key=lambda row: (str(row.get("created_at") or ""), str(row["id"])))
        return results

    def recall(
        self,
        subject_id: str,
        query: str,
        *,
        seed_limit: int = DEFAULT_SEED_LIMIT,
        frontier_cap: int = DEFAULT_FRONTIER_CAP,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> GraphRecall:
        seed_limit = max(1, min(int(seed_limit), 64))
        frontier_cap = max(1, min(int(frontier_cap), 256))
        max_depth = max(0, min(int(max_depth), 3))
        seed_rows = self._seed_rows(subject_id, query, seed_limit)
        entity_seeds: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        edge_candidates: dict[str, dict[str, Any]] = {}
        public_seeds: list[dict[str, Any]] = []

        for row in seed_rows:
            score = float(row["score"])
            object_type = str(row["object_type"])
            object_id = str(row["object_id"])
            public_seeds.append(
                {"object_type": object_type, "object_id": object_id, "score": round(score, 6)}
            )
            if object_type == "entity":
                entity_id = self._canonical_entity(subject_id, object_id)
                self._set_seed(entity_seeds, entity_id, score, [{"entity_id": entity_id}])
            elif object_type == "alias":
                alias = self.conn.execute(
                    "SELECT entity_id FROM entity_aliases WHERE id = ? AND status = 'active'",
                    (object_id,),
                ).fetchone()
                if alias:
                    entity_id = self._canonical_entity(
                        subject_id, str(alias["entity_id"])
                    )
                    self._set_seed(
                        entity_seeds,
                        entity_id,
                        score,
                        [{"alias_id": object_id, "entity_id": entity_id}],
                    )
            elif object_type == "edge":
                edge = self._edge(object_id)
                if edge is not None:
                    self._consider_edge(
                        edge_candidates,
                        edge,
                        score,
                        [{"edge_id": object_id, "seed": True}],
                        depth=0,
                    )
                    # Continue from the edge's destination. Seeding its source
                    # would make a hit on "my boss" activate every unrelated
                    # fact owned by the root user entity.
                    if edge.get("dst_entity"):
                        destination = self._canonical_entity(
                            subject_id, str(edge["dst_entity"])
                        )
                        self._set_seed(
                            entity_seeds,
                            destination,
                            score,
                            [
                                {
                                    "edge_id": object_id,
                                    "entity_id": destination,
                                }
                            ],
                        )

        frontier = entity_seeds
        visited_edges: set[str] = set(edge_candidates)
        for depth in range(1, max_depth + 1):
            next_frontier: dict[str, tuple[float, list[dict[str, Any]]]] = {}
            for entity_id, (activation, path) in sorted(
                frontier.items(), key=lambda item: (-item[1][0], item[0])
            )[:frontier_cap]:
                for edge in self._connected_edges(subject_id, entity_id, frontier_cap):
                    edge_id = str(edge["id"])
                    trust = _TRUST_WEIGHTS.get(str(edge["trust_tier"]), 0.4)
                    prior = _RELATION_PRIORS.get(str(edge["relation"]), 0.8)
                    score = activation * trust * prior * (0.72 ** depth)
                    step = {
                        "edge_id": edge_id,
                        "from_entity": entity_id,
                        "relation": str(edge["relation"]),
                    }
                    edge_path = [*path, step]
                    self._consider_edge(
                        edge_candidates, edge, score, edge_path, depth=depth
                    )
                    visited_edges.add(edge_id)
                    source = self._canonical_entity(
                        subject_id, str(edge["src_entity"])
                    )
                    destination = (
                        self._canonical_entity(subject_id, str(edge["dst_entity"]))
                        if edge["dst_entity"]
                        else ""
                    )
                    other = destination if source == entity_id and destination else source
                    # "you" owns most user facts and is therefore a graph
                    # supernode. It can be an explicit seed, but spreading
                    # back into it from a named entity creates an unrelated
                    # fan-out (Sarah -> boss -> you -> every preference).
                    if (
                        other
                        and other != entity_id
                        and not self._is_root_entity(subject_id, other)
                    ):
                        self._set_seed(next_frontier, other, score, edge_path)
            frontier = dict(
                sorted(next_frontier.items(), key=lambda item: (-item[1][0], item[0]))[
                    :frontier_cap
                ]
            )
            if not frontier:
                break

        candidates = list(edge_candidates.values())
        by_recency = {
            item["edge_id"]: index
            for index, item in enumerate(
                sorted(candidates, key=lambda item: (item["created_at"], item["edge_id"]))
            )
        }
        denominator = max(len(candidates) - 1, 1)
        for item in candidates:
            recency = by_recency[item["edge_id"]] / denominator
            item["recency_score"] = round(recency, 6)
            item["score"] = round(item["score"] * (0.85 + 0.15 * recency), 6)
        candidates.sort(key=lambda item: (-item["score"], item["edge_id"]))
        retained = candidates[:frontier_cap]
        pruned_ids = sorted(item["edge_id"] for item in candidates[frontier_cap:])
        return GraphRecall(
            candidates=tuple(retained),
            seeds=tuple(public_seeds),
            pruned_digest=sha256_hex(canonical_json(pruned_ids)),
            visited_edges=len(visited_edges),
            seed_limit=seed_limit,
            frontier_cap=frontier_cap,
            max_depth=max_depth,
        )

    def inspect(self, subject_id: str) -> dict[str, Any]:
        entities = [dict(row) for row in self.conn.execute(
            "SELECT * FROM entities WHERE subject_id = ? ORDER BY created_at, id",
            (subject_id,),
        ).fetchall()]
        aliases = [dict(row) for row in self.conn.execute(
            "SELECT * FROM entity_aliases WHERE subject_id = ? ORDER BY created_at, id",
            (subject_id,),
        ).fetchall()]
        edges = [dict(row) for row in self.conn.execute(
            "SELECT * FROM edges WHERE subject_id = ? ORDER BY created_at, id",
            (subject_id,),
        ).fetchall()]
        return {
            "extractor_version": GRAPH_EXTRACTOR_VERSION,
            "entities": entities,
            "aliases": aliases,
            "edges": edges,
            "merge_proposals": self.list_merge_proposals(subject_id),
            "archives": self.list_archives(subject_id),
            "counts": self.counts(subject_id),
        }

    def counts(self, subject_id: str) -> dict[str, int]:
        return {
            table: int(
                self.conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE subject_id = ?", (subject_id,)
                ).fetchone()[0]
            )
            for table in ("entities", "entity_aliases", "edges")
        }

    def _ensure_entity(
        self,
        subject_id: str,
        canonical: str,
        kind: str,
        *,
        status: str,
        source_record: str | None,
        created_at: str,
        mutations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized = _normalize(canonical)
        row = self.conn.execute(
            "SELECT * FROM entities WHERE subject_id = ? AND normalized = ? AND kind = ?",
            (subject_id, normalized, kind),
        ).fetchone()
        if row is not None:
            entity = dict(row)
            if entity["status"] == "quarantined" and status == "active":
                self.conn.execute(
                    "UPDATE entities SET status = 'active', updated_at = ? WHERE id = ?",
                    (created_at, entity["id"]),
                )
                entity["status"] = "active"
                self._upsert_fts("entity", str(entity["id"]), subject_id, canonical)
                mutations.append(
                    {"event_type": "entity.activated", "object_id": str(entity["id"])}
                )
            return entity
        entity_id = _stable_id("ent", subject_id, normalized, kind)
        tombstoned = self.conn.execute(
            "SELECT id FROM entities WHERE id = ? AND status = 'tombstoned'",
            (entity_id,),
        ).fetchone()
        if tombstoned is not None:
            self.conn.execute(
                """
                UPDATE entities
                SET canonical = ?, normalized = ?, status = ?, source_record = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (canonical.strip(), normalized, status, source_record, created_at, entity_id),
            )
            if status == "active":
                self._upsert_fts("entity", entity_id, subject_id, canonical)
            mutations.append(
                {"event_type": "entity.recreated", "object_id": entity_id, "status": status}
            )
            return {
                "id": entity_id,
                "subject_id": subject_id,
                "canonical": canonical.strip(),
                "kind": kind,
                "status": status,
            }
        self.conn.execute(
            """
            INSERT INTO entities (
              id, subject_id, canonical, normalized, kind, status,
              merged_into, source_record, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)
            """,
            (
                entity_id,
                subject_id,
                canonical.strip(),
                normalized,
                kind,
                status,
                source_record,
                created_at,
            ),
        )
        if status == "active":
            self._upsert_fts("entity", entity_id, subject_id, canonical)
        mutations.append(
            {
                "event_type": "entity.created",
                "object_id": entity_id,
                "kind": kind,
                "canonical_sha256": sha256_hex(canonical.strip()),
                "status": status,
            }
        )
        return {
            "id": entity_id,
            "subject_id": subject_id,
            "canonical": canonical.strip(),
            "kind": kind,
            "status": status,
        }

    def _ensure_alias(
        self,
        subject_id: str,
        entity_id: str,
        surface: str,
        *,
        source_record: str | None,
        trust_tier: str,
        status: str,
        created_at: str,
        mutations: list[dict[str, Any]],
    ) -> None:
        normalized = _normalize(surface)
        alias_id = _stable_id(
            "als", subject_id, entity_id, normalized, source_record or "root"
        )
        row = self.conn.execute(
            "SELECT status FROM entity_aliases WHERE id = ?", (alias_id,)
        ).fetchone()
        if row is not None:
            if row["status"] == "quarantined" and status == "active":
                self.conn.execute(
                    "UPDATE entity_aliases SET status = 'active' WHERE id = ?", (alias_id,)
                )
                self._upsert_fts("alias", alias_id, subject_id, surface)
            return
        self.conn.execute(
            """
            INSERT INTO entity_aliases (
              id, entity_id, subject_id, surface, normalized, source_record,
              trust_tier, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alias_id,
                entity_id,
                subject_id,
                surface.strip(),
                normalized,
                source_record,
                trust_tier,
                status,
                created_at,
            ),
        )
        if status == "active":
            self._upsert_fts("alias", alias_id, subject_id, surface)
        if source_record is not None:
            mutations.append(
                {
                    "event_type": "alias.learned",
                    "object_id": alias_id,
                    "entity_id": entity_id,
                    "surface_sha256": sha256_hex(surface.strip()),
                    "record_id": source_record,
                    "status": status,
                }
            )

    def _sync_existing_edge(
        self, edge: dict[str, Any], record: dict[str, Any]
    ) -> list[dict[str, Any]]:
        desired = str(record.get("status") or "active")
        if desired not in {"active", "quarantined", "superseded"}:
            desired = "tombstoned"
        if edge["status"] == desired and edge["trust_tier"] == record.get("trust_tier"):
            return []
        self.conn.execute(
            "UPDATE edges SET status = ?, trust_tier = ?, updated_at = ? WHERE id = ?",
            (desired, record.get("trust_tier"), record.get("updated_at"), edge["id"]),
        )
        if desired == "active":
            entity_ids = [str(edge["src_entity"])]
            if edge.get("dst_entity"):
                entity_ids.append(str(edge["dst_entity"]))
            for entity_id in entity_ids:
                entity = self.conn.execute(
                    "SELECT canonical, status FROM entities WHERE id = ?", (entity_id,)
                ).fetchone()
                if entity is not None and entity["status"] == "quarantined":
                    self.conn.execute(
                        "UPDATE entities SET status = 'active', updated_at = ? WHERE id = ?",
                        (record.get("updated_at"), entity_id),
                    )
                    self._upsert_fts(
                        "entity", entity_id, str(record["subject_id"]), str(entity["canonical"])
                    )
            aliases = self.conn.execute(
                "SELECT id, surface FROM entity_aliases WHERE source_record = ?",
                (record["id"],),
            ).fetchall()
            for alias in aliases:
                self.conn.execute(
                    "UPDATE entity_aliases SET status = 'active' WHERE id = ?",
                    (alias["id"],),
                )
                self._upsert_fts(
                    "alias", str(alias["id"]), str(record["subject_id"]), str(alias["surface"])
                )
            self._upsert_edge_fts(str(edge["id"]))
        else:
            self._delete_fts("edge", str(edge["id"]))
            aliases = self.conn.execute(
                "SELECT id FROM entity_aliases WHERE source_record = ?",
                (record["id"],),
            ).fetchall()
            for alias in aliases:
                self.conn.execute(
                    "UPDATE entity_aliases SET status = ? WHERE id = ?",
                    (
                        "superseded" if desired == "superseded" else desired,
                        alias["id"],
                    ),
                )
                self._delete_fts("alias", str(alias["id"]))
        return [
            {
                "event_type": "edge.status_changed",
                "object_id": str(edge["id"]),
                "status": desired,
            }
        ]

    def _reindex_existing_edge(
        self, edge: dict[str, Any], record: dict[str, Any]
    ) -> list[dict[str, Any]]:
        subject_id = str(record["subject_id"])
        record_id = str(record["id"])
        old_edge_id = str(edge["id"])
        old_entities = [str(edge["src_entity"])]
        if edge.get("dst_entity"):
            old_entities.append(str(edge["dst_entity"]))
        aliases = self.conn.execute(
            "SELECT id FROM entity_aliases WHERE subject_id = ? AND source_record = ?",
            (subject_id, record_id),
        ).fetchall()
        for alias in aliases:
            self._delete_fts("alias", str(alias["id"]))
        self.conn.execute(
            "DELETE FROM entity_aliases WHERE subject_id = ? AND source_record = ?",
            (subject_id, record_id),
        )
        self.conn.execute(
            "UPDATE edges SET supersedes_id = NULL WHERE supersedes_id = ?",
            (old_edge_id,),
        )
        self._delete_fts("edge", old_edge_id)
        self.conn.execute("DELETE FROM edges WHERE id = ?", (old_edge_id,))
        mutations = [
            {
                "event_type": "edge.reextracted",
                "object_id": old_edge_id,
                "record_id": record_id,
                "from_extractor_version": edge["extractor_version"],
                "to_extractor_version": GRAPH_EXTRACTOR_VERSION,
            }
        ]
        mutations.extend(self.index_record(record))
        for entity_id in old_entities:
            referenced = self.conn.execute(
                """
                SELECT 1 FROM edges
                WHERE subject_id = ? AND (src_entity = ? OR dst_entity = ?)
                LIMIT 1
                """,
                (subject_id, entity_id, entity_id),
            ).fetchone()
            entity = self.conn.execute(
                "SELECT source_record, normalized FROM entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if (
                referenced is None
                and entity is not None
                and entity["source_record"] == record_id
                and entity["normalized"] != "you"
            ):
                self._delete_fts("entity", entity_id)
                self.conn.execute(
                    """
                    UPDATE entities
                    SET status = 'tombstoned', canonical = '', normalized = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (f"stale:{entity_id}", entity_id),
                )
        return mutations

    def _seed_rows(
        self, subject_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        terms = query_tokens(query)
        if not terms:
            return []
        if getattr(self.store, "_graph_fts_enabled", False):
            expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
            try:
                rows = self.conn.execute(
                    """
                    SELECT object_type, object_id, -bm25(graph_fts) AS raw_score
                    FROM graph_fts
                    WHERE graph_fts MATCH ? AND subject_id = ?
                    ORDER BY bm25(graph_fts), object_type, object_id
                    LIMIT ?
                    """,
                    (expression, subject_id, limit),
                ).fetchall()
                max_score = max((float(row["raw_score"]) for row in rows), default=0.0)
                return [
                    {
                        "object_type": row["object_type"],
                        "object_id": row["object_id"],
                        "score": float(row["raw_score"]) / max_score if max_score > 0 else 1.0,
                    }
                    for row in rows
                ]
            except sqlite3.OperationalError:
                pass
        token_set = set(terms)
        fallback: list[dict[str, Any]] = []
        for object_type, table, id_column, text_column in (
            ("entity", "entities", "id", "canonical"),
            ("alias", "entity_aliases", "id", "surface"),
            ("edge", "edges", "id", "relation_label"),
        ):
            rows = self.conn.execute(
                f"SELECT {id_column} AS id, {text_column} AS text FROM {table} "
                "WHERE subject_id = ? AND status = 'active'",
                (subject_id,),
            ).fetchall()
            for row in rows:
                words = set(query_tokens(str(row["text"])))
                overlap = len(token_set & words) / max(len(token_set), 1)
                if overlap:
                    fallback.append(
                        {"object_type": object_type, "object_id": row["id"], "score": overlap}
                    )
        fallback.sort(key=lambda item: (-item["score"], item["object_type"], item["object_id"]))
        return fallback[:limit]

    def _connected_edges(
        self, subject_id: str, entity_id: str, limit: int
    ) -> list[dict[str, Any]]:
        family = self._entity_family(subject_id, entity_id)
        placeholders = ",".join("?" for _ in family)
        rows = self.conn.execute(
            f"""
            SELECT * FROM edges
            WHERE subject_id = ? AND status = 'active'
              AND (src_entity IN ({placeholders}) OR dst_entity IN ({placeholders}))
            ORDER BY created_at DESC, id
            LIMIT ?
            """,
            (subject_id, *family, *family, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def _canonical_entity(self, subject_id: str, entity_id: str) -> str:
        current = entity_id
        seen: set[str] = set()
        while current not in seen:
            seen.add(current)
            row = self.conn.execute(
                "SELECT status, merged_into FROM entities WHERE id = ? AND subject_id = ?",
                (current, subject_id),
            ).fetchone()
            if row is None or row["status"] != "merged" or not row["merged_into"]:
                return current
            current = str(row["merged_into"])
        return entity_id

    def _entity_family(self, subject_id: str, entity_id: str) -> list[str]:
        canonical = self._canonical_entity(subject_id, entity_id)
        family = {canonical}
        frontier = [canonical]
        while frontier:
            parent = frontier.pop()
            rows = self.conn.execute(
                """
                SELECT id FROM entities
                WHERE subject_id = ? AND status = 'merged' AND merged_into = ?
                """,
                (subject_id, parent),
            ).fetchall()
            for row in rows:
                child = str(row["id"])
                if child not in family:
                    family.add(child)
                    frontier.append(child)
        return sorted(family)

    def _edge(self, edge_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM edges WHERE id = ? AND status = 'active'", (edge_id,)
        ).fetchone()
        return dict(row) if row else None

    def _is_root_entity(self, subject_id: str, entity_id: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM entities
            WHERE id = ? AND subject_id = ? AND normalized = 'you'
              AND source_record IS NULL
            """,
            (entity_id, subject_id),
        ).fetchone()
        return row is not None

    def _consider_edge(
        self,
        candidates: dict[str, dict[str, Any]],
        edge: dict[str, Any],
        score: float,
        path: list[dict[str, Any]],
        *,
        depth: int,
    ) -> None:
        edge_id = str(edge["id"])
        current = candidates.get(edge_id)
        if current is not None and float(current["score"]) >= score:
            return
        candidates[edge_id] = {
            "edge_id": edge_id,
            "record_id": str(edge["record_id"]),
            "score": float(score),
            "depth": depth,
            "path": path,
            "relation": str(edge["relation"]),
            "created_at": str(edge["created_at"]),
        }

    @staticmethod
    def _set_seed(
        seeds: dict[str, tuple[float, list[dict[str, Any]]]],
        entity_id: str,
        score: float,
        path: list[dict[str, Any]],
    ) -> None:
        current = seeds.get(entity_id)
        if current is None or score > current[0]:
            seeds[entity_id] = (score, path)

    def _upsert_edge_fts(self, edge_id: str) -> None:
        row = self.conn.execute(
            """
            SELECT e.subject_id, e.relation_label, src.canonical AS src_name,
                   dst.canonical AS dst_name, e.dst_value
            FROM edges e
            JOIN entities src ON src.id = e.src_entity
            LEFT JOIN entities dst ON dst.id = e.dst_entity
            WHERE e.id = ? AND e.status = 'active'
            """,
            (edge_id,),
        ).fetchone()
        if row is None:
            return
        text = " ".join(
            part
            for part in (
                row["src_name"], row["relation_label"], row["dst_name"], row["dst_value"]
            )
            if part
        )
        self._upsert_fts("edge", edge_id, str(row["subject_id"]), text)

    def _upsert_fts(
        self, object_type: str, object_id: str, subject_id: str, text: str
    ) -> None:
        if not getattr(self.store, "_graph_fts_enabled", False):
            return
        self.store._upsert_graph_fts(
            object_type, object_id, subject_id, text
        )

    def _delete_fts(self, object_type: str, object_id: str) -> None:
        if getattr(self.store, "_graph_fts_enabled", False):
            self.store._delete_graph_fts(object_type, object_id)


def extract_graph_fact(record: dict[str, Any]) -> GraphFact | None:
    """Derive one conservative graph fact from an existing record."""
    content = " ".join(str(record.get("content") or "").split())
    if not content:
        return None
    match = _POSSESSIVE_RE.match(content)
    if match:
        source = "you" if match.group("src") == "User" else match.group("src").strip()
        label = _normalize_relation_label(match.group("relation"))
        destination = match.group("dst").strip(" .?!")
        if source and label and destination:
            relation = _canonical_relation(label)
            return GraphFact(
                source=source,
                relation=relation,
                relation_label=label,
                destination=destination,
                source_kind="person",
                destination_kind=_infer_kind(label, destination),
            )
    match = _USER_AVOIDS_RE.match(content)
    if match:
        destination = match.group("dst").strip(" .?!")
        return GraphFact("you", "avoids", "avoids", destination)
    match = _NAMED_RELATION_RE.match(content)
    if match:
        source = match.group("src").strip()
        label = _normalize_relation_label(match.group("verb"))
        destination = match.group("dst").strip(" .?!")
        return GraphFact(
            source,
            _canonical_relation(label),
            label,
            destination,
            destination_kind=_infer_kind(label, destination),
        )
    return None


def _canonical_relation(label: str) -> str:
    return _RELATION_MAP.get(label, "related_to")


def _normalize_relation_label(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())[:80]


def _normalize(value: str) -> str:
    normalized = " ".join(
        re.sub(r"[^\w@._+-]+", " ", value.casefold(), flags=re.UNICODE).split()
    )[:160]
    if normalized:
        return normalized
    return f"sha256:{sha256(value.strip().casefold().encode('utf-8')).hexdigest()}"


def _infer_kind(relation_label: str, value: str) -> str:
    relation = relation_label.lower()
    if relation in {"boss", "manager", "spouse", "partner", "friend", "doctor"}:
        return "person"
    if any(token in relation for token in ("airport", "city", "country", "location", "address")):
        return "place"
    if any(token in relation for token in ("file", "document", "report")):
        return "file"
    if "project" in relation:
        return "project"
    if "org" in relation or "employer" in relation or "company" in relation:
        return "org"
    return "other"


def _stable_id(prefix: str, *parts: str) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    return f"{prefix}_{sha256(payload.encode('utf-8')).hexdigest()[:24]}"
