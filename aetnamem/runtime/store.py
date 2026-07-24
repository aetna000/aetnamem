from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import uuid

from aetnamem.store.sqlite import utc_now


RUNTIME_SCHEMA_VERSION = "2"


class RuntimeStore:
    """Additive runtime tables stored beside the existing memory schema."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA foreign_keys = ON")
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

    def _migrate(self) -> None:
        with self.transaction():
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_runs (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL,
                  session_id TEXT,
                  task_id TEXT,
                  turn_id TEXT,
                  query_sha256 TEXT NOT NULL,
                  preset TEXT NOT NULL,
                  status TEXT NOT NULL,
                  degraded_planes TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL,
                  completed_at TEXT,
                  outcome_success INTEGER,
                  outcome_summary TEXT,
                  outcome_digest TEXT,
                  outcome_idempotency_key TEXT UNIQUE,
                  scope_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_runtime_runs_scope
                  ON runtime_runs(subject_id, agent_id, created_at);

                CREATE TABLE IF NOT EXISTS runtime_contributions (
                  id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  plane TEXT NOT NULL,
                  content TEXT NOT NULL,
                  content_sha256 TEXT NOT NULL,
                  item_ids TEXT NOT NULL DEFAULT '[]',
                  provenance TEXT NOT NULL DEFAULT '[]',
                  metadata TEXT NOT NULL DEFAULT '{}',
                  placement TEXT NOT NULL,
                  trust TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (run_id) REFERENCES runtime_runs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_runtime_contributions_run
                  ON runtime_contributions(run_id, plane);

                CREATE TABLE IF NOT EXISTS context_manifests (
                  run_id TEXT PRIMARY KEY,
                  manifest_sha256 TEXT NOT NULL,
                  stable_sha256 TEXT NOT NULL,
                  dynamic_sha256 TEXT NOT NULL,
                  total_chars INTEGER NOT NULL,
                  manifest_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (run_id) REFERENCES runtime_runs(id)
                );

                CREATE TABLE IF NOT EXISTS working_snapshots (
                  id TEXT PRIMARY KEY,
                  subject_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL,
                  session_id TEXT,
                  task_id TEXT,
                  state_json TEXT NOT NULL,
                  state_sha256 TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_working_scope
                  ON working_snapshots(subject_id, agent_id, session_id, task_id, created_at);

                CREATE TABLE IF NOT EXISTS experience_outcomes (
                  id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL UNIQUE,
                  subject_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL,
                  session_id TEXT,
                  task_id TEXT,
                  query_sha256 TEXT NOT NULL,
                  success INTEGER NOT NULL,
                  summary TEXT NOT NULL,
                  result_digest TEXT,
                  feedback TEXT,
                  receipt_digests TEXT NOT NULL DEFAULT '[]',
                  manifest_sha256 TEXT,
                  metrics_json TEXT NOT NULL DEFAULT '{}',
                  outcome_trust TEXT NOT NULL DEFAULT 'caller_asserted',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (run_id) REFERENCES runtime_runs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_experience_scope
                  ON experience_outcomes(subject_id, agent_id, created_at);

                CREATE TABLE IF NOT EXISTS lesson_proposals (
                  id TEXT PRIMARY KEY,
                  outcome_id TEXT NOT NULL,
                  subject_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL,
                  content TEXT NOT NULL,
                  status TEXT NOT NULL,
                  evidence_count INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (outcome_id) REFERENCES experience_outcomes(id)
                );

                CREATE INDEX IF NOT EXISTS idx_lessons_scope
                  ON lesson_proposals(subject_id, agent_id, status, created_at);

                CREATE TABLE IF NOT EXISTS procedures (
                  id TEXT PRIMARY KEY,
                  source_path TEXT NOT NULL,
                  name TEXT NOT NULL,
                  description TEXT NOT NULL,
                  scope TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(source_path, name)
                );

                CREATE TABLE IF NOT EXISTS procedure_versions (
                  id TEXT PRIMARY KEY,
                  procedure_id TEXT NOT NULL,
                  content_sha256 TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(procedure_id, content_sha256),
                  FOREIGN KEY (procedure_id) REFERENCES procedures(id)
                );

                CREATE TABLE IF NOT EXISTS procedure_evaluations (
                  id TEXT PRIMARY KEY,
                  procedure_version_id TEXT NOT NULL,
                  run_id TEXT NOT NULL,
                  success INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(procedure_version_id, run_id),
                  FOREIGN KEY (procedure_version_id) REFERENCES procedure_versions(id),
                  FOREIGN KEY (run_id) REFERENCES runtime_runs(id)
                );

                CREATE TABLE IF NOT EXISTS procedure_improvement_proposals (
                  id TEXT PRIMARY KEY,
                  procedure_version_id TEXT NOT NULL,
                  run_id TEXT NOT NULL,
                  content TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(procedure_version_id, run_id),
                  FOREIGN KEY (procedure_version_id) REFERENCES procedure_versions(id),
                  FOREIGN KEY (run_id) REFERENCES runtime_runs(id)
                );

                CREATE TABLE IF NOT EXISTS runtime_interventions (
                  decision_id TEXT NOT NULL UNIQUE,
                  experiment_id TEXT NOT NULL,
                  run_id TEXT NOT NULL,
                  plane TEXT NOT NULL,
                  candidate_contribution_id TEXT NOT NULL,
                  candidate_sha256 TEXT NOT NULL,
                  assigned INTEGER NOT NULL,
                  applied INTEGER NOT NULL,
                  propensity REAL NOT NULL,
                  arm_id TEXT NOT NULL,
                  applied_arm_id TEXT NOT NULL,
                  joint_propensity REAL NOT NULL,
                  design TEXT NOT NULL,
                  stratum TEXT NOT NULL,
                  seed_commitment TEXT NOT NULL,
                  policy_version TEXT NOT NULL,
                  policy_sha256 TEXT NOT NULL,
                  eligibility TEXT NOT NULL,
                  pinned_reason TEXT,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (run_id, plane),
                  FOREIGN KEY (run_id) REFERENCES runtime_runs(id),
                  FOREIGN KEY (candidate_contribution_id)
                    REFERENCES runtime_contributions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_runtime_interventions_experiment
                  ON runtime_interventions(experiment_id, stratum, arm_id);
                """
            )
            self._ensure_column(
                "experience_outcomes",
                "manifest_sha256",
                "TEXT",
            )
            self._ensure_column(
                "experience_outcomes",
                "metrics_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                "experience_outcomes",
                "outcome_trust",
                "TEXT NOT NULL DEFAULT 'caller_asserted'",
            )
            self._conn.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES ('runtime_schema', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (RUNTIME_SCHEMA_VERSION,),
            )

    def _ensure_column(self, table: str, column: str, declaration: str) -> None:
        columns = {
            str(row["name"])
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
            )

    def create_run(
        self,
        *,
        run_id: str,
        subject_id: str,
        agent_id: str,
        session_id: str | None,
        task_id: str | None,
        turn_id: str | None,
        query_sha256: str,
        preset: str,
        scope: dict[str, Any],
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO runtime_runs(
                  id, subject_id, agent_id, session_id, task_id, turn_id,
                  query_sha256, preset, status, created_at, scope_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'preparing', ?, ?)
                """,
                (
                    run_id,
                    subject_id,
                    agent_id,
                    session_id,
                    task_id,
                    turn_id,
                    query_sha256,
                    preset,
                    utc_now(),
                    _json(scope),
                ),
            )

    def save_contribution(
        self,
        *,
        run_id: str,
        plane: str,
        content: str,
        content_sha256: str,
        item_ids: list[str],
        provenance: list[dict[str, Any]],
        metadata: dict[str, Any],
        placement: str,
        trust: str,
    ) -> str:
        contribution_id = _new_id("contrib")
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO runtime_contributions(
                  id, run_id, plane, content, content_sha256, item_ids,
                  provenance, metadata, placement, trust, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contribution_id,
                    run_id,
                    plane,
                    content,
                    content_sha256,
                    _json(item_ids),
                    _json(provenance),
                    _json(metadata),
                    placement,
                    trust,
                    utc_now(),
                ),
            )
        return contribution_id

    def save_interventions(self, decisions: list[dict[str, Any]]) -> None:
        if not decisions:
            return
        created_at = utc_now()
        with self.transaction():
            for item in decisions:
                self._conn.execute(
                    """
                    INSERT INTO runtime_interventions(
                      decision_id, experiment_id, run_id, plane,
                      candidate_contribution_id, candidate_sha256,
                      assigned, applied, propensity, arm_id, applied_arm_id,
                      joint_propensity, design, stratum, seed_commitment,
                      policy_version, policy_sha256, eligibility, pinned_reason,
                      created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["decision_id"],
                        item["experiment_id"],
                        item["run_id"],
                        item["plane"],
                        item["candidate_contribution_id"],
                        item["candidate_sha256"],
                        int(bool(item["assigned"])),
                        int(bool(item["applied"])),
                        float(item["propensity"]),
                        item["arm_id"],
                        item["applied_arm_id"],
                        float(item["joint_propensity"]),
                        item["design"],
                        item["stratum"],
                        item["seed_commitment"],
                        item["policy_version"],
                        item["policy_sha256"],
                        item["eligibility"],
                        item.get("pinned_reason"),
                        created_at,
                    ),
                )

    def interventions_for_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM runtime_interventions
            WHERE run_id = ?
            ORDER BY CASE plane
              WHEN 'working' THEN 1
              WHEN 'semantic' THEN 2
              WHEN 'episodic' THEN 3
              WHEN 'procedural' THEN 4
              ELSE 5
            END
            """,
            (run_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["assigned"] = bool(item["assigned"])
            item["applied"] = bool(item["applied"])
            result.append(item)
        return result

    def finish_run(
        self,
        *,
        run_id: str,
        degraded_planes: list[str],
        manifest_sha256: str,
        stable_sha256: str,
        dynamic_sha256: str,
        total_chars: int,
        manifest: dict[str, Any],
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO context_manifests(
                  run_id, manifest_sha256, stable_sha256, dynamic_sha256,
                  total_chars, manifest_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    manifest_sha256,
                    stable_sha256,
                    dynamic_sha256,
                    total_chars,
                    _json(manifest),
                    utc_now(),
                ),
            )
            self._conn.execute(
                """
                UPDATE runtime_runs
                SET status = 'prepared', degraded_planes = ?
                WHERE id = ?
                """,
                (_json(degraded_planes), run_id),
            )

    def save_working_snapshot(
        self,
        *,
        subject_id: str,
        agent_id: str,
        session_id: str | None,
        task_id: str | None,
        state: dict[str, Any],
        state_sha256: str,
    ) -> str:
        snapshot_id = _new_id("work")
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO working_snapshots(
                  id, subject_id, agent_id, session_id, task_id,
                  state_json, state_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    subject_id,
                    agent_id,
                    session_id,
                    task_id,
                    _json(state),
                    state_sha256,
                    utc_now(),
                ),
            )
        return snapshot_id

    def latest_working_snapshot(
        self,
        *,
        subject_id: str,
        agent_id: str,
        session_id: str | None,
        task_id: str | None,
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT * FROM working_snapshots
            WHERE subject_id = ? AND agent_id = ?
              AND (session_id = ? OR (? IS NULL AND session_id IS NULL))
              AND (task_id = ? OR (? IS NULL AND task_id IS NULL))
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (subject_id, agent_id, session_id, session_id, task_id, task_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["state"] = json.loads(result.pop("state_json"))
        return result

    def run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM runtime_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def manifest_for_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM context_manifests WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["manifest"] = json.loads(result.pop("manifest_json"))
        return result

    def record_outcome(
        self,
        *,
        run_id: str,
        success: bool,
        summary: str,
        result_digest: str | None,
        feedback: str | None,
        receipt_digests: list[str],
        idempotency_key: str,
        manifest_sha256: str | None = None,
        metrics: dict[str, Any] | None = None,
        outcome_trust: str = "caller_asserted",
    ) -> tuple[dict[str, Any], bool]:
        existing = self._conn.execute(
            "SELECT * FROM runtime_runs WHERE outcome_idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            if str(existing["id"]) != run_id:
                raise ValueError("idempotency key already belongs to another run")
            outcome = self._conn.execute(
                "SELECT * FROM experience_outcomes WHERE run_id = ?",
                (existing["id"],),
            ).fetchone()
            return (
                self.get_outcome(str(outcome["id"])) if outcome else dict(existing)
            ), False
        run = self._conn.execute(
            "SELECT * FROM runtime_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"unknown runtime run: {run_id}")
        if run["status"] == "completed":
            raise ValueError(f"runtime run already completed: {run_id}")
        outcome_id = _new_id("outcome")
        created_at = utc_now()
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO experience_outcomes(
                  id, run_id, subject_id, agent_id, session_id, task_id,
                  query_sha256, success, summary, result_digest, feedback,
                  receipt_digests, manifest_sha256, metrics_json, outcome_trust,
                  created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome_id,
                    run_id,
                    run["subject_id"],
                    run["agent_id"],
                    run["session_id"],
                    run["task_id"],
                    run["query_sha256"],
                    int(success),
                    summary,
                    result_digest,
                    feedback,
                    _json(receipt_digests),
                    manifest_sha256,
                    _json(metrics or {}),
                    outcome_trust,
                    created_at,
                ),
            )
            self._conn.execute(
                """
                UPDATE runtime_runs
                SET status = 'completed', completed_at = ?, outcome_success = ?,
                    outcome_summary = ?, outcome_digest = ?,
                    outcome_idempotency_key = ?
                WHERE id = ?
                """,
                (
                    created_at,
                    int(success),
                    summary,
                    result_digest,
                    idempotency_key,
                    run_id,
                ),
            )
        return self.get_outcome(outcome_id), True

    def get_outcome(self, outcome_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM experience_outcomes WHERE id = ?", (outcome_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown outcome: {outcome_id}")
        result = dict(row)
        result["success"] = bool(result["success"])
        result["receipt_digests"] = json.loads(result["receipt_digests"])
        result["metrics"] = json.loads(result.pop("metrics_json"))
        return result

    def outcome_for_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id FROM experience_outcomes WHERE run_id = ?", (run_id,)
        ).fetchone()
        return self.get_outcome(str(row["id"])) if row else None

    def relevant_outcomes(
        self, *, subject_id: str, agent_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        terms = {part.lower() for part in query.split() if len(part) >= 3}
        rows = self._conn.execute(
            """
            SELECT * FROM experience_outcomes
            WHERE subject_id = ? AND agent_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 100
            """,
            (subject_id, agent_id),
        ).fetchall()
        ranked: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            item = dict(row)
            haystack = f"{item['summary']} {item.get('feedback') or ''}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score or not terms:
                item["success"] = bool(item["success"])
                ranked.append((score, item))
        ranked.sort(key=lambda pair: (pair[0], pair[1]["created_at"]), reverse=True)
        return [item for _, item in ranked[: max(0, limit)]]

    def create_lesson(
        self, *, outcome_id: str, subject_id: str, agent_id: str, content: str
    ) -> dict[str, Any]:
        lesson_id = _new_id("lesson")
        created_at = utc_now()
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO lesson_proposals(
                  id, outcome_id, subject_id, agent_id, content, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'quarantined', ?)
                """,
                (lesson_id, outcome_id, subject_id, agent_id, content, created_at),
            )
        return {
            "id": lesson_id,
            "outcome_id": outcome_id,
            "content": content,
            "status": "quarantined",
            "created_at": created_at,
        }

    def active_lessons(
        self, *, subject_id: str, agent_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM lesson_proposals
            WHERE subject_id = ? AND agent_id = ? AND status = 'active'
            ORDER BY created_at DESC, id DESC
            """,
            (subject_id, agent_id),
        ).fetchall()
        terms = {part.lower() for part in query.split() if len(part) >= 3}
        matched = [
            dict(row)
            for row in rows
            if not terms or any(term in str(row["content"]).lower() for term in terms)
        ]
        return matched[: max(0, limit)]

    def promote_lesson(self, lesson_id: str) -> dict[str, Any]:
        with self.transaction():
            self._conn.execute(
                """
                UPDATE lesson_proposals SET status = 'active'
                WHERE id = ? AND status = 'quarantined'
                """,
                (lesson_id,),
            )
        row = self._conn.execute(
            "SELECT * FROM lesson_proposals WHERE id = ?", (lesson_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown lesson: {lesson_id}")
        return dict(row)

    def upsert_procedure(
        self, *, source_path: str, name: str, description: str, content: str, digest: str
    ) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM procedures WHERE source_path = ? AND name = ?",
            (source_path, name),
        ).fetchone()
        with self.transaction():
            if row is None:
                procedure_id = _new_id("proc")
                self._conn.execute(
                    """
                    INSERT INTO procedures(
                      id, source_path, name, description, scope, status, created_at
                    ) VALUES (?, ?, ?, ?, 'project', 'active', ?)
                    """,
                    (procedure_id, source_path, name, description, utc_now()),
                )
            else:
                procedure_id = str(row["id"])
                self._conn.execute(
                    "UPDATE procedures SET description = ? WHERE id = ?",
                    (description, procedure_id),
                )
            version = self._conn.execute(
                """
                SELECT * FROM procedure_versions
                WHERE procedure_id = ? AND content_sha256 = ?
                """,
                (procedure_id, digest),
            ).fetchone()
            if version is None:
                version_id = _new_id("procver")
                self._conn.execute(
                    """
                    INSERT INTO procedure_versions(
                      id, procedure_id, content_sha256, content, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (version_id, procedure_id, digest, content, utc_now()),
                )
            else:
                version_id = str(version["id"])
        return {
            "procedure_id": procedure_id,
            "version_id": version_id,
            "name": name,
            "description": description,
            "content_sha256": digest,
            "content": content,
            "source_path": source_path,
        }

    def record_procedure_evaluation(
        self, *, procedure_version_id: str, run_id: str, success: bool
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT OR IGNORE INTO procedure_evaluations(
                  id, procedure_version_id, run_id, success, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (_new_id("proceval"), procedure_version_id, run_id, int(success), utc_now()),
            )

    def create_procedure_improvement(
        self, *, procedure_version_id: str, run_id: str
    ) -> dict[str, Any]:
        existing = self._conn.execute(
            """
            SELECT * FROM procedure_improvement_proposals
            WHERE procedure_version_id = ? AND run_id = ?
            """,
            (procedure_version_id, run_id),
        ).fetchone()
        if existing is not None:
            result = dict(existing)
            result["kind"] = "procedure_improvement"
            return result
        proposal_id = _new_id("procproposal")
        content = (
            "Review this procedure version after a failed host-attested run; "
            "do not activate changes without evaluation."
        )
        created_at = utc_now()
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO procedure_improvement_proposals(
                  id, procedure_version_id, run_id, content, status, created_at
                ) VALUES (?, ?, ?, ?, 'quarantined', ?)
                """,
                (
                    proposal_id,
                    procedure_version_id,
                    run_id,
                    content,
                    created_at,
                ),
            )
        return {
            "id": proposal_id,
            "kind": "procedure_improvement",
            "procedure_version_id": procedure_version_id,
            "run_id": run_id,
            "content": content,
            "status": "quarantined",
            "created_at": created_at,
        }

    def procedure_versions_for_run(self, run_id: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT item_ids FROM runtime_contributions
            WHERE run_id = ? AND plane = 'procedural'
            """,
            (run_id,),
        ).fetchall()
        result: list[str] = []
        for row in rows:
            result.extend(str(value) for value in json.loads(row["item_ids"]))
        return result

    def status(self) -> dict[str, Any]:
        counts = {}
        for name in (
            "runtime_runs",
            "working_snapshots",
            "experience_outcomes",
            "lesson_proposals",
            "procedures",
            "procedure_versions",
            "procedure_improvement_proposals",
            "runtime_interventions",
        ):
            counts[name] = int(
                self._conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"]
            )
        return {
            "format": "aetnamem-runtime-status-v1",
            "runtime_schema": RUNTIME_SCHEMA_VERSION,
            "counts": counts,
        }

    def purge_subject_content(
        self, *, subject_id: str, contains: str
    ) -> dict[str, list[str]]:
        """Erase runtime payloads matching a user deletion selector.

        Identifiers and existing digests remain as non-content evidence. The
        mutable payload copies are cleared so semantic deletion cannot leave a
        matching value in a previously compiled contribution.
        """
        needle = contains.lower()
        purged: dict[str, list[str]] = {
            "working_snapshot_ids": [],
            "outcome_ids": [],
            "lesson_ids": [],
            "contribution_ids": [],
            "run_ids": [],
        }
        with self.transaction():
            rows = self._conn.execute(
                "SELECT id, state_json FROM working_snapshots WHERE subject_id = ?",
                (subject_id,),
            ).fetchall()
            for row in rows:
                if needle in str(row["state_json"]).lower():
                    self._conn.execute(
                        "UPDATE working_snapshots SET state_json = '{}' WHERE id = ?",
                        (row["id"],),
                    )
                    purged["working_snapshot_ids"].append(str(row["id"]))

            rows = self._conn.execute(
                """
                SELECT id, summary, feedback FROM experience_outcomes
                WHERE subject_id = ?
                """,
                (subject_id,),
            ).fetchall()
            for row in rows:
                payload = f"{row['summary']} {row['feedback'] or ''}".lower()
                if needle in payload:
                    self._conn.execute(
                        """
                        UPDATE experience_outcomes
                        SET summary = '[purged]', feedback = NULL
                        WHERE id = ?
                        """,
                        (row["id"],),
                    )
                    purged["outcome_ids"].append(str(row["id"]))

            rows = self._conn.execute(
                "SELECT id, content FROM lesson_proposals WHERE subject_id = ?",
                (subject_id,),
            ).fetchall()
            for row in rows:
                if needle in str(row["content"]).lower():
                    self._conn.execute(
                        """
                        UPDATE lesson_proposals
                        SET content = '[purged]', status = 'tombstoned'
                        WHERE id = ?
                        """,
                        (row["id"],),
                    )
                    purged["lesson_ids"].append(str(row["id"]))

            rows = self._conn.execute(
                """
                SELECT c.id, c.content, c.metadata
                FROM runtime_contributions AS c
                JOIN runtime_runs AS r ON r.id = c.run_id
                WHERE r.subject_id = ?
                """,
                (subject_id,),
            ).fetchall()
            for row in rows:
                payload = f"{row['content']} {row['metadata']}".lower()
                if needle in payload:
                    self._conn.execute(
                        """
                        UPDATE runtime_contributions
                        SET content = '', metadata = '{}'
                        WHERE id = ?
                        """,
                        (row["id"],),
                    )
                    purged["contribution_ids"].append(str(row["id"]))

            rows = self._conn.execute(
                """
                SELECT id, outcome_summary FROM runtime_runs
                WHERE subject_id = ? AND outcome_summary IS NOT NULL
                """,
                (subject_id,),
            ).fetchall()
            for row in rows:
                if needle in str(row["outcome_summary"]).lower():
                    self._conn.execute(
                        "UPDATE runtime_runs SET outcome_summary = '[purged]' WHERE id = ?",
                        (row["id"],),
                    )
                    purged["run_ids"].append(str(row["id"]))
        return purged


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
