from __future__ import annotations

from functools import wraps
import json
from pathlib import Path
from typing import Any, Callable, TypeVar

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.core.policy import (
    classify_source,
    find_duplicate,
    forget_needle,
    initial_status,
    normalize_content,
    records_to_supersede,
)
from aetnamem.extract import extract_facts
from aetnamem.retrieve import query_tokens, rank_records
from aetnamem.store import SQLiteStore
from aetnamem.store.sqlite import utc_now


_T = TypeVar("_T")


def _atomic(method: Callable[..., _T]) -> Callable[..., _T]:
    """Make one public memory operation and all its audit writes atomic."""

    @wraps(method)
    def wrapped(self: "Memory", *args: Any, **kwargs: Any) -> _T:
        with self.store.transaction(immediate=True):
            return method(self, *args, **kwargs)

    return wrapped


class Memory:
    """Embedded auditable memory engine.

    v0 keeps extraction deterministic. The invariants that matter:

    - every semantic record derives from an episode and points back to it,
    - untrusted extractions are quarantined until explicitly promoted,
    - updates supersede (keyed on the extracted fact slot), never overwrite,
    - deletion tombstones *and* purges, including the source episode,
    - every mutation and every recall lands in the hash-linked audit log,
    - the audit plane stores digests and structural metadata, never message
      text, fact values, or query text (unless `retain_query_text=True`).
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        retain_query_text: bool = False,
    ) -> None:
        self.store = SQLiteStore(path)
        self.retain_query_text = retain_query_text

    def close(self) -> None:
        self.store.close()

    @_atomic
    def remember(
        self,
        subject_id: str,
        message: str | None = None,
        *,
        fact: str | None = None,
        force: bool = False,
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
        if force and not candidates and source == "user_message":
            from aetnamem.core.policy import trust_tier_for_source
            from aetnamem.extract.rules import CandidateFact

            candidates = [
                CandidateFact(
                    content=_explicit_note(text),
                    confidence=0.7,
                    source_type=source,
                    trust_tier=trust_tier_for_source(source),
                    fact_key=None,
                    scope="user_note",
                )
            ]
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

    @_atomic
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
        all_scored = scored
        if min_score is not None:
            scored = [item for item in scored if item.score >= min_score]
        returned = scored[:limit]
        returned_ids = [item.record["id"] for item in returned]

        candidates_payload = [
            {
                "record_id": item.record["id"],
                "score": item.score,
                "text_score": item.text_score,
                "trust_score": item.trust_score,
                "recency_score": item.recency_score,
                "status": item.record["status"],
                "source_type": item.record["source_type"],
                "above_threshold": min_score is None or item.score >= min_score,
                "returned": item.record["id"] in returned_ids,
            }
            for item in all_scored[:50]
        ]
        retrieval_id = self.store.insert_retrieval_event(
            subject_id=subject_id,
            session_id=session_id,
            query=query if self.retain_query_text else "",
            query_sha256=_sha256(query),
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
                "candidate_count": len(all_scored),
                "min_score": min_score,
                "limit": limit,
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

    @_atomic
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
        utterance_sha256 = _sha256(utterance) if utterance else None
        if utterance:
            contains = contains or forget_needle(utterance)

        if not contains:
            # Refuse to interpret an empty selector as "delete everything".
            payload = {"reason": "empty selector"}
            if utterance_sha256 is not None:
                payload["utterance_sha256"] = utterance_sha256
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="memory.forget_rejected",
                actor=actor,
                session_id=session_id,
                turn_id=turn,
                payload=payload,
            )
            return {"deleted": False, "record_ids": [], "receipt": None}

        needle = contains.lower()
        candidates = [
            record
            for record in self.store.list_records(
                subject_id, statuses=("active", "quarantined")
            )
            if needle in str(record.get("content") or "").lower()
        ]

        record_ids = [record["id"] for record in candidates]
        selector_sha256 = _sha256(needle)
        purged_ids, purged_episode_ids = self.store.tombstone_records(
            subject_id=subject_id, record_ids=record_ids
        )
        # The audit event carries the selector digest, never its text — the
        # needle usually names exactly the thing being erased.
        payload = {
            "selector_sha256": selector_sha256,
            "purged_record_ids": purged_ids,
            "purged_episode_ids": purged_episode_ids,
            "purged_count": len(purged_ids),
        }
        if utterance_sha256 is not None:
            payload["utterance_sha256"] = utterance_sha256
        event_id = self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.forget",
            actor=actor,
            session_id=session_id,
            turn_id=turn,
            payload=payload,
        )
        event = self.store.get_audit_event(subject_id, event_id)
        receipt = {
            "format": "aetnamem-deletion-receipt-v1",
            "subject_id": subject_id,
            "created_at": event["created_at"],
            "selector_sha256": selector_sha256,
            "purged_record_ids": purged_ids,
            "purged_episode_ids": purged_episode_ids,
            "audit_event_id": event_id,
            "audit_event_hash": event["event_hash"],
        }
        receipt["receipt_sha256"] = sha256_hex(canonical_json(receipt))
        return {
            "deleted": bool(purged_ids),
            "record_ids": purged_ids,
            "receipt": receipt,
        }

    @_atomic
    def capture(
        self,
        subject_id: str,
        role: str,
        content: str,
        *,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        """Host-adapter entry point for automatic conversation capture.

        User turns run the full write pipeline (extraction + policy gates).
        Assistant output and tool traffic are agent-generated — they are
        logged to the audit chain as digests, never stored as memory records,
        so auto-capture cannot become a self-poisoning loop.
        """
        if role == "user":
            result = self.remember(
                subject_id, content, session_id=session_id, turn_id=turn_id
            )
            return {"kind": "remembered", **result}
        if role == "assistant":
            event_id = self.log_action(
                subject_id,
                "agent.response_shown",
                {"response_sha256": _sha256(content), "chars": len(content)},
                session_id=session_id,
                turn_id=turn_id,
            )
            return {"kind": "logged", "event_id": event_id}
        if role == "tool_call":
            event_id = self.log_action(
                subject_id,
                "agent.tool_call",
                {"tool": tool_name, "args_sha256": _sha256(content)},
                session_id=session_id,
                turn_id=turn_id,
            )
            return {"kind": "logged", "event_id": event_id}
        if role == "tool_result":
            event_id = self.log_action(
                subject_id,
                "agent.tool_result",
                {
                    "tool": tool_name,
                    "result_sha256": _sha256(content),
                    "chars": len(content),
                },
                session_id=session_id,
                turn_id=turn_id,
            )
            return {"kind": "logged", "event_id": event_id}
        raise ValueError(f"unknown capture role: {role}")

    @_atomic
    def build_recall_block(
        self,
        subject_id: str,
        query: str,
        *,
        session_id: str | None = None,
        max_records: int = 5,
        max_chars: int = 2000,
        min_score: float = 0.3,
    ) -> dict[str, Any]:
        """Deterministic, bounded <relevant_memories> block for prompt injection.

        Uses recall() (so every candidate lands in retrieval_events), applies
        hard budgets, and writes a memory.context_injected audit event naming
        exactly which record IDs entered the agent's context. The default
        min_score of 0.3 requires a lexical match — trust/recency priors
        alone never inject.
        """
        records = self.recall(
            subject_id,
            query,
            session_id=session_id,
            limit=max_records,
            min_score=min_score,
        )
        lines: list[str] = []
        included: list[str] = []
        used = 0
        for record in records:
            line = f"- [{record['id']}] {record['content']}"
            if used + len(line) + 1 > max_chars:
                break
            lines.append(line)
            included.append(record["id"])
            used += len(line) + 1

        if not lines:
            return {"block": "", "record_ids": [], "count": 0}

        block = "<relevant_memories>\n" + "\n".join(lines) + "\n</relevant_memories>"
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.context_injected",
            actor="system",
            session_id=session_id,
            payload={
                "record_ids": included,
                "block_sha256": _sha256(block),
                "query_sha256": _sha256(query),
            },
        )
        return {"block": block, "record_ids": included, "count": len(included)}

    @_atomic
    def build_persona(
        self,
        subject_id: str,
        *,
        session_id: str | None = None,
        max_chars: int = 1500,
    ) -> dict[str, Any]:
        """L3: deterministic persona snapshot derived from active records.

        Keyed facts (stable slots like "preferred airport") come first,
        then unkeyed facts newest-first, under a hard character budget.
        No LLM, no stored copy — the persona is always derived live from
        L1, so it can never go stale, and every line carries the source
        record id. Building one writes a memory.persona_built audit event.
        """
        active = self.list(subject_id)
        keyed = sorted(
            (r for r in active if r.get("fact_key")),
            key=lambda r: (str(r["fact_key"]), str(r["created_at"])),
        )
        unkeyed = sorted(
            (r for r in active if not r.get("fact_key")),
            key=lambda r: str(r["created_at"]),
            reverse=True,
        )

        lines: list[str] = []
        included: list[str] = []
        used = 0
        for record in [*keyed, *unkeyed]:
            line = f"- [{record['id']}] {record['content']}"
            if used + len(line) + 1 > max_chars:
                break
            lines.append(line)
            included.append(record["id"])
            used += len(line) + 1

        if not lines:
            return {"block": "", "record_ids": [], "count": 0}

        block = "<user_persona>\n" + "\n".join(lines) + "\n</user_persona>"
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.persona_built",
            actor="system",
            session_id=session_id,
            payload={
                "record_ids": included,
                "persona_sha256": _sha256(block),
            },
        )
        return {"block": block, "record_ids": included, "count": len(included)}

    def scenes(self, subject_id: str) -> list[dict[str, Any]]:
        """L2: deterministic scene view — one scene per session.

        Groups the episodic log by session with the records each session
        produced. Purely derived (nothing stored), provenance is the
        episode/record ids themselves. LLM-clustered scenes can layer on
        later via propose_facts-style derivation.
        """
        episodes = self.store.list_episodes(subject_id)
        records = self.list(subject_id, include_inactive=True)

        by_session: dict[str, dict[str, Any]] = {}
        for episode in episodes:
            key = episode.get("session_id") or "(no session)"
            scene = by_session.setdefault(
                key,
                {
                    "scene_id": f"session:{key}",
                    "session_id": episode.get("session_id"),
                    "started_at": episode["created_at"],
                    "ended_at": episode["created_at"],
                    "episode_ids": [],
                    "record_ids": [],
                },
            )
            scene["episode_ids"].append(episode["id"])
            scene["started_at"] = min(scene["started_at"], episode["created_at"])
            scene["ended_at"] = max(scene["ended_at"], episode["created_at"])
        for record in records:
            key = record.get("source_session_id") or "(no session)"
            if key in by_session:
                by_session[key]["record_ids"].append(record["id"])

        return sorted(
            by_session.values(), key=lambda scene: str(scene["ended_at"]), reverse=True
        )

    @_atomic
    def propose_facts(
        self,
        subject_id: str,
        proposals: list[dict[str, Any]],
        *,
        proposer: str = "llm",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Entry point for async LLM consolidation jobs.

        Any external job (an LLM batch, a human review, a migration) may
        propose candidate facts, but they land as *quarantined* derived
        records, each required to cite evidence — existing episode or
        record ids for this subject. Proposals without valid evidence are
        rejected. Nothing becomes active except through promote().
        """
        episodes = {e["id"] for e in self.store.list_episodes(subject_id)}
        record_ids = {
            r["id"] for r in self.list(subject_id, include_inactive=True)
        }
        visible = self.store.list_records(
            subject_id, statuses=("active", "quarantined")
        )

        quarantined: list[dict[str, Any]] = []
        duplicates: list[str] = []
        rejected: list[dict[str, Any]] = []
        for proposal in proposals:
            content = str(proposal.get("content") or "").strip()
            evidence = list(proposal.get("evidence") or [])
            if not content:
                rejected.append({"proposal": proposal, "reason": "empty content"})
                continue
            unknown = [
                item
                for item in evidence
                if item not in episodes and item not in record_ids
            ]
            if not evidence or unknown:
                rejected.append(
                    {
                        "proposal": proposal,
                        "reason": "missing or unknown evidence"
                        + (f": {unknown}" if unknown else ""),
                    }
                )
                continue
            duplicate = find_duplicate(content, visible)
            if duplicate is not None:
                duplicates.append(duplicate["id"])
                continue

            fact_key = proposal.get("fact_key")
            record_id = self.store.insert_record(
                subject_id=subject_id,
                content=content,
                source_type="derived",
                trust_tier="derived",
                source_session_id=session_id,
                source_turn_id=None,
                episode_id=None,
                confidence=float(proposal.get("confidence", 0.5)),
                scope="user_private",
                status="quarantined",
                fact_key=str(fact_key).lower().strip() if fact_key else None,
                raw={"evidence": evidence, "proposer": proposer},
            )
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="memory.record_quarantined",
                actor=proposer,
                session_id=session_id,
                record_id=record_id,
                payload={
                    "source_type": "derived",
                    "trust_tier": "derived",
                    "status": "quarantined",
                    "evidence": evidence,
                    "content_sha256": _sha256(content),
                },
            )
            record = self.store.get_record(subject_id, record_id)
            quarantined.append(record)
            visible.append(record)

        return {
            "quarantined": quarantined,
            "duplicate_ids": duplicates,
            "rejected": rejected,
        }

    @_atomic
    def consolidate(
        self,
        subject_id: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Deterministic consolidation pass (no LLM).

        1. Exact-duplicate active contents collapse: the newest copy stays
           active, older copies become superseded (provenance intact).
        2. fact_key repair: if several active records share a fact slot, the
           newest supersedes the rest.

        Every change is recorded in a memory.consolidated audit event.
        """
        active = self.list(subject_id)

        duplicate_ids: list[str] = []
        survivors: list[dict[str, Any]] = []
        by_content: dict[str, list[dict[str, Any]]] = {}
        for record in active:
            key = normalize_content(str(record.get("content") or ""))
            by_content.setdefault(key, []).append(record)
        for group in by_content.values():
            group.sort(key=lambda r: (str(r["created_at"]), str(r["id"])))
            keeper = group[-1]
            older_ids = [record["id"] for record in group[:-1]]
            if older_ids:
                self.store.supersede_records(
                    subject_id=subject_id,
                    record_ids=older_ids,
                    superseded_by_id=keeper["id"],
                )
                duplicate_ids.extend(older_ids)
            survivors.append(keeper)

        repaired_ids: list[str] = []
        by_key: dict[str, list[dict[str, Any]]] = {}
        for record in survivors:
            if record.get("fact_key"):
                by_key.setdefault(str(record["fact_key"]), []).append(record)
        for group in by_key.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda r: (str(r["created_at"]), str(r["id"])))
            keeper = group[-1]
            older_ids = [record["id"] for record in group[:-1]]
            self.store.supersede_records(
                subject_id=subject_id,
                record_ids=older_ids,
                superseded_by_id=keeper["id"],
            )
            repaired_ids.extend(older_ids)

        report = {
            "duplicates_superseded": duplicate_ids,
            "fact_key_repaired": repaired_ids,
            "active_before": len(active),
            "active_after": len(self.list(subject_id)),
        }
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.consolidated",
            actor="system",
            session_id=session_id,
            payload=report,
        )
        return report

    @_atomic
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

    def checkpoint(
        self,
        *,
        sink_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Snapshot every subject's audit-chain head for external anchoring.

        The checkpoint pins each chain's latest (sequence, event_hash), so any
        later tail truncation is detectable — the chain alone cannot prove
        events were not deleted from its end. Write the returned document (or
        the JSONL `sink_path`) somewhere the database owner cannot rewrite:
        WORM/object-lock storage, a transparency log, or an RFC 3161
        timestamping service.
        """
        document = {
            "format": "aetnamem-checkpoint-v1",
            "created_at": utc_now(),
            "subjects": self.store.chain_heads(),
        }
        document["checkpoint_sha256"] = sha256_hex(canonical_json(document))
        if sink_path is not None:
            with Path(sink_path).open("a", encoding="utf-8") as sink:
                sink.write(canonical_json(document) + "\n")
        return document

    def verify(
        self,
        subject_id: str | None = None,
        *,
        checkpoints_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Verify audit-chain integrity, optionally against anchored checkpoints.

        Chain verification alone detects edits and in-place tampering;
        checkpoint containment additionally detects tail truncation since the
        checkpoint was anchored.
        """
        heads = self.store.chain_heads()
        subject_ids = [subject_id] if subject_id is not None else sorted(heads)
        subjects: dict[str, Any] = {
            sid: {
                "chain_valid": self.store.verify_audit_chain(sid),
                "checkpoints_checked": 0,
                "failures": [],
            }
            for sid in subject_ids
        }

        for document in _load_checkpoints(checkpoints_path):
            recomputed = dict(document)
            claimed_digest = recomputed.pop("checkpoint_sha256", None)
            if sha256_hex(canonical_json(recomputed)) != claimed_digest:
                for sid in subjects:
                    subjects[sid]["failures"].append(
                        {"checkpoint": document.get("created_at"), "reason": "checkpoint digest mismatch"}
                    )
                continue
            for sid, pinned in document.get("subjects", {}).items():
                if sid not in subjects:
                    continue
                subjects[sid]["checkpoints_checked"] += 1
                event = self.store.event_at_sequence(sid, pinned["sequence"])
                if event is None:
                    subjects[sid]["failures"].append(
                        {
                            "checkpoint": document.get("created_at"),
                            "reason": f"pinned event at sequence {pinned['sequence']} is missing (tail truncated?)",
                        }
                    )
                elif event["event_hash"] != pinned["event_hash"]:
                    subjects[sid]["failures"].append(
                        {
                            "checkpoint": document.get("created_at"),
                            "reason": f"event hash at sequence {pinned['sequence']} does not match checkpoint",
                        }
                    )

        valid = all(
            item["chain_valid"] and not item["failures"] for item in subjects.values()
        )
        return {"valid": valid, "subjects": subjects}

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

    @_atomic
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
    return sha256_hex(value)


def _explicit_note(value: str) -> str:
    text = " ".join(value.strip().split())
    if not text:
        return "User asked to remember an empty note."
    if text[0].islower():
        text = text[0].upper() + text[1:]
    if text[-1] not in ".?!":
        text += "."
    return text


def _load_checkpoints(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    documents: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                documents.append(json.loads(line))
    return documents
