from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from aetnamem.core.policy import (
    classify_source,
    find_duplicate,
    forget_needle,
    initial_status,
    records_to_supersede,
)
from aetnamem.extract import extract_facts
from aetnamem.retrieve import query_tokens, rank_records
from aetnamem.store import SQLiteStore


class Memory:
    """Embedded auditable memory engine.

    v0 keeps extraction deterministic. The invariants that matter:

    - every semantic record derives from an episode and points back to it,
    - untrusted extractions are quarantined until explicitly promoted,
    - updates supersede (keyed on the extracted fact slot), never overwrite,
    - deletion tombstones *and* purges, including the source episode,
    - every mutation and every recall lands in the hash-linked audit log.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.store = SQLiteStore(path)

    def close(self) -> None:
        self.store.close()

    def remember(
        self,
        subject_id: str,
        message: str | None = None,
        *,
        fact: str | None = None,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        source_type: str | None = None,
        actor: str = "user",
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = message if message is not None else fact
        if text is None:
            raise ValueError("remember() requires message or fact")
        turn = _turn_id(turn_id)
        source = source_type or classify_source(text)
        episode_id = self.store.insert_episode(
            subject_id=subject_id,
            session_id=session_id,
            turn_id=turn,
            message=text,
            source_type=source,
            raw=raw or {},
        )
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="episode.ingested",
            actor=actor,
            session_id=session_id,
            turn_id=turn,
            payload={
                "episode_id": episode_id,
                "source_type": source,
                "message_sha256": _sha256(text),
            },
        )

        candidates = extract_facts(text, source_type=source)
        records: list[dict[str, Any]] = []
        duplicate_ids: list[str] = []
        for candidate in candidates:
            visible = self.store.list_records(
                subject_id, statuses=("active", "quarantined")
            )
            active = [record for record in visible if record["status"] == "active"]
            status = initial_status(candidate.trust_tier)
            # A trusted statement only dedupes against active records — a
            # quarantined copy must never swallow a user-confirmed fact.
            duplicate = find_duplicate(
                candidate.content, active if status == "active" else visible
            )
            if duplicate is not None:
                duplicate_ids.append(duplicate["id"])
                self.store.append_audit_event(
                    subject_id=subject_id,
                    event_type="memory.duplicate_ignored",
                    actor="system",
                    session_id=session_id,
                    turn_id=turn,
                    record_id=duplicate["id"],
                    payload={"episode_id": episode_id, "fact_key": candidate.fact_key},
                )
                continue

            old_records = (
                records_to_supersede(candidate.fact_key, active)
                if status == "active"
                else []
            )
            record_id = self.store.insert_record(
                subject_id=subject_id,
                content=candidate.content,
                source_type=candidate.source_type,
                trust_tier=candidate.trust_tier,
                source_session_id=session_id,
                source_turn_id=turn,
                episode_id=episode_id,
                confidence=candidate.confidence,
                scope=candidate.scope,
                status=status,
                supersedes_id=old_records[0]["id"] if old_records else None,
                fact_key=candidate.fact_key,
                raw={},
            )
            old_ids = [record["id"] for record in old_records]
            self.store.supersede_records(
                subject_id=subject_id,
                record_ids=old_ids,
                superseded_by_id=record_id,
            )
            event_type = (
                "memory.record_created"
                if status == "active"
                else "memory.record_quarantined"
            )
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type=event_type,
                actor="system",
                session_id=session_id,
                turn_id=turn,
                record_id=record_id,
                payload={
                    "episode_id": episode_id,
                    "source_type": candidate.source_type,
                    "trust_tier": candidate.trust_tier,
                    "status": status,
                    "fact_key": candidate.fact_key,
                    "supersedes": old_ids,
                },
            )
            records.append(self.store.get_record(subject_id, record_id))

        if not candidates and source != "user_message":
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="memory.untrusted_source_ignored",
                actor="system",
                session_id=session_id,
                turn_id=turn,
                payload={"episode_id": episode_id, "source_type": source},
            )

        return {
            "episode_id": episode_id,
            "records": records,
            "duplicate_ids": duplicate_ids,
        }

    def recall(
        self,
        subject_id: str,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 10,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        """Top-k recall over *active* records only.

        Like a vector store, recall ranks every active record (text relevance
        + trust + recency) and returns the best `limit`; pass `min_score` to
        drop weak matches. All candidate scores are logged to the retrieval
        event, so the ranking is fully auditable.
        """
        active_records = self.list(subject_id)
        fts_scores = self.store.fts_match_scores(subject_id, query_tokens(query))
        scored = rank_records(
            query,
            active_records,
            fts_scores=fts_scores if fts_scores else None,
        )
        if min_score is not None:
            scored = [item for item in scored if item.score >= min_score]
        returned = scored[:limit]

        candidates_payload = [
            {
                "record_id": item.record["id"],
                "score": item.score,
                "text_score": item.text_score,
                "trust_score": item.trust_score,
                "recency_score": item.recency_score,
                "status": item.record["status"],
                "source_type": item.record["source_type"],
            }
            for item in scored[:50]
        ]
        returned_ids = [item.record["id"] for item in returned]
        retrieval_id = self.store.insert_retrieval_event(
            subject_id=subject_id,
            session_id=session_id,
            query=query,
            candidates=candidates_payload,
            returned_ids=returned_ids,
        )
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.recall",
            actor="system",
            session_id=session_id,
            payload={
                "retrieval_id": retrieval_id,
                "returned_ids": returned_ids,
            },
        )
        return [item.record for item in returned]

    def list(
        self,
        subject_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        statuses = None if include_inactive else ("active",)
        return self.store.list_records(subject_id, statuses=statuses)

    def forget(
        self,
        subject_id: str,
        selector: dict[str, Any] | str | None = None,
        *,
        utterance: str | None = None,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        turn = _turn_id(turn_id)
        contains = _selector_contains(selector)
        if utterance:
            episode_id = self.store.insert_episode(
                subject_id=subject_id,
                session_id=session_id,
                turn_id=turn,
                message=utterance,
                source_type="user_message",
                raw={},
            )
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="episode.ingested",
                actor=actor,
                session_id=session_id,
                turn_id=turn,
                payload={
                    "episode_id": episode_id,
                    "source_type": "user_message",
                    "message_sha256": _sha256(utterance),
                },
            )
            contains = contains or forget_needle(utterance)

        if not contains:
            # Refuse to interpret an empty selector as "delete everything".
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="memory.forget_rejected",
                actor=actor,
                session_id=session_id,
                turn_id=turn,
                payload={"reason": "empty selector"},
            )
            return {"deleted": False, "record_ids": []}

        needle = contains.lower()
        candidates = [
            record
            for record in self.store.list_records(
                subject_id, statuses=("active", "quarantined")
            )
            if needle in str(record.get("content") or "").lower()
        ]

        record_ids = [record["id"] for record in candidates]
        purged_ids = self.store.tombstone_records(
            subject_id=subject_id, record_ids=record_ids
        )
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.forget",
            actor=actor,
            session_id=session_id,
            turn_id=turn,
            payload={
                "selector": {"contains": contains},
                "purged_record_ids": purged_ids,
                "purged_count": len(purged_ids),
            },
        )
        return {"deleted": bool(purged_ids), "record_ids": purged_ids}

    def promote(
        self,
        subject_id: str,
        record_id: str,
        *,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        """Activate a quarantined record after explicit user confirmation."""
        record = self.store.promote_record(
            subject_id=subject_id, record_id=record_id
        )
        if record is None:
            raise ValueError(f"record {record_id} is not quarantined for {subject_id}")

        active = [
            item
            for item in self.list(subject_id)
            if item["id"] != record_id
        ]
        old_records = records_to_supersede(record.get("fact_key"), active)
        old_ids = [item["id"] for item in old_records]
        self.store.supersede_records(
            subject_id=subject_id,
            record_ids=old_ids,
            superseded_by_id=record_id,
        )
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.record_promoted",
            actor=actor,
            session_id=session_id,
            turn_id=_turn_id(turn_id),
            record_id=record_id,
            payload={
                "trust_tier": record["trust_tier"],
                "fact_key": record.get("fact_key"),
                "supersedes": old_ids,
            },
        )
        return self.store.get_record(subject_id, record_id)

    def inspect(self, subject_id: str) -> dict[str, Any]:
        return {
            "records": self.list(subject_id, include_inactive=True),
            "episodes": self.store.list_episodes(subject_id),
            "retrieval_events": self.store.list_retrieval_events(subject_id),
            "audit_log": self.store.list_audit_events(subject_id),
            "audit_chain_valid": self.store.verify_audit_chain(subject_id),
        }

    def audit(self, subject_id: str) -> dict[str, Any]:
        return {
            "audit_log": self.store.list_audit_events(subject_id),
            "retrieval_events": self.store.list_retrieval_events(subject_id),
            "audit_chain_valid": self.store.verify_audit_chain(subject_id),
        }

    def log_action(
        self,
        subject_id: str,
        action_type: str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        actor: str = "agent",
    ) -> str:
        event_type = action_type if "." in action_type else f"agent.{action_type}"
        return self.store.append_audit_event(
            subject_id=subject_id,
            event_type=event_type,
            actor=actor,
            session_id=session_id,
            turn_id=_turn_id(turn_id),
            payload=payload or {},
        )

    def get_retrieval_log(
        self,
        subject_id: str,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.list_retrieval_events(subject_id, session_id=session_id)

    def reset_subject(self, subject_id: str) -> None:
        self.store.reset_subject(subject_id)


def _turn_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return f"t{value}"
    return str(value)


def _selector_contains(selector: dict[str, Any] | str | None) -> str | None:
    if selector is None:
        return None
    if isinstance(selector, str):
        return selector
    value = selector.get("contains") or selector.get("content_contains")
    return str(value) if value else None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
