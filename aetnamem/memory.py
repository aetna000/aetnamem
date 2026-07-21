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
)
from aetnamem.extract import extract_facts
from aetnamem.graph import GRAPH_EXTRACTOR_VERSION, GraphIndex
from aetnamem.retrieve import (
    ScoredRecord,
    query_tokens,
    rank_records,
    token_overlap_components,
)
from aetnamem.retrieve.rank import RECENCY_WEIGHT, TEXT_WEIGHT, TRUST_WEIGHT
from aetnamem.store import SQLiteStore
from aetnamem.store.sqlite import utc_now


_T = TypeVar("_T")

_RETRIEVAL_EVIDENCE_FORMAT = "aetnamem-retrieval-evidence-v2"
_RECORD_RANKER_VERSION = "record-rank-v1"
_GRAPH_FUSION_VERSION = "weighted-rrf-v1"
_RRF_RANK_CONSTANT = 60.0
_GRAPH_RRF_WEIGHT = 2.0
_CANDIDATE_LOG_WINDOW = 50


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
        graph_recall: bool = False,
        recall_candidate_limit: int = 200,
    ) -> None:
        self.store = SQLiteStore(path)
        self.graph = GraphIndex(self.store)
        self.retain_query_text = retain_query_text
        self.graph_recall = graph_recall
        self.recall_candidate_limit = max(1, int(recall_candidate_limit))

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
            status = initial_status(candidate.trust_tier)
            # A trusted statement only dedupes against active records — a
            # quarantined copy must never swallow a user-confirmed fact.
            duplicate = self.store.find_duplicate_record(
                subject_id,
                candidate.content,
                statuses=("active",)
                if status == "active"
                else ("active", "quarantined"),
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
                self.store.active_records_for_fact_key(
                    subject_id, candidate.fact_key
                )
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
                    "confidence": candidate.confidence,
                    "scope": candidate.scope,
                    # Binds the stored content to the chain so a direct edit
                    # of the record row is detectable by an offline auditor.
                    "content_sha256": _sha256(candidate.content),
                },
            )
            stored_record = self.store.get_record(subject_id, record_id)
            assert stored_record is not None
            graph_mutations = self.graph.supersede_records(
                subject_id, old_ids, record_id
            )
            graph_mutations.extend(self.graph.index_record(stored_record))
            self._audit_graph_mutations(
                subject_id,
                graph_mutations,
                session_id=session_id,
                turn_id=turn,
                record_id=record_id,
            )
            records.append(stored_record)

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
        use_graph: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Top-k recall over bounded active record and optional graph candidates."""
        active_records, fts_scores = self.store.recall_candidates(
            subject_id,
            query_tokens(query),
            limit=self.recall_candidate_limit,
        )
        graph_result = None
        graph_by_record: dict[str, dict[str, Any]] = {}
        if self.graph_recall if use_graph is None else use_graph:
            graph_result = self.graph.recall(subject_id, query)
            for candidate in graph_result.candidates:
                record_id = str(candidate["record_id"])
                current = graph_by_record.get(record_id)
                if current is None or candidate["score"] > current["score"]:
                    graph_by_record[record_id] = candidate

            # Graph spread is allowed to nominate records outside the direct
            # FTS window; otherwise multi-hop recall would collapse back to
            # lexical recall as soon as the database exceeds the candidate cap.
            candidate_ids = {str(record["id"]) for record in active_records}
            for record_id in graph_by_record:
                if record_id in candidate_ids:
                    continue
                record = self.store.get_record(subject_id, record_id)
                if (
                    record is not None
                    and record["subject_id"] == subject_id
                    and record["status"] == "active"
                ):
                    active_records.append(record)
                    candidate_ids.add(record_id)

        lexical_scored = rank_records(
            query,
            active_records,
            fts_scores=fts_scores if fts_scores else None,
        )
        lexical_by_record = {
            str(item.record["id"]): item for item in lexical_scored
        }
        lexical_rank = {
            str(item.record["id"]): rank
            for rank, item in enumerate(lexical_scored, start=1)
        }
        graph_rank = _graph_ranks(graph_by_record)
        scored = lexical_scored
        if graph_result is not None:
            scored = _blend_graph_scores(scored, graph_by_record)
        all_scored = scored
        if min_score is not None:
            scored = [item for item in scored if item.score >= min_score]
        returned = scored[:limit]
        returned_ids = [item.record["id"] for item in returned]

        by_recency = sorted(
            active_records,
            key=lambda record: (
                str(record.get("created_at") or ""),
                str(record.get("id")),
            ),
        )
        recency_rank = {
            str(record["id"]): rank
            for rank, record in enumerate(by_recency)
        }
        recency_denominator = max(len(active_records) - 1, 1)
        fts_max_raw = max(fts_scores.values(), default=0.0)
        candidates_payload: list[dict[str, Any]] = []
        returned_id_set = set(returned_ids)
        for rank, item in enumerate(all_scored, start=1):
            record_id = str(item.record["id"])
            if rank > _CANDIDATE_LOG_WINDOW and record_id not in returned_id_set:
                continue
            lexical_item = lexical_by_record[record_id]
            graph_candidate = graph_by_record.get(record_id)
            overlap_matches, overlap_terms = token_overlap_components(
                query, str(item.record.get("content") or "")
            )
            summary: dict[str, Any] = {
                "record_id": record_id,
                "rank": rank,
                "score": item.score,
                "base_score": lexical_item.score,
                "text_score": item.text_score,
                "text_method": "fts5" if fts_scores else "token-overlap",
                "text_raw_score": round(float(fts_scores.get(record_id, 0.0)), 12),
                "text_max_raw_score": round(float(fts_max_raw), 12),
                "text_overlap_matches": overlap_matches,
                "text_overlap_terms": overlap_terms,
                "trust_score": item.trust_score,
                "trust_tier": item.record["trust_tier"],
                "recency_score": item.recency_score,
                "recency_rank": recency_rank[record_id],
                "recency_denominator": recency_denominator,
                "lexical_rank": lexical_rank[record_id],
                "graph_rank": graph_rank.get(record_id),
                "graph_score": (
                    round(float(graph_candidate["score"]), 6)
                    if graph_candidate is not None
                    else None
                ),
                "created_at": item.record["created_at"],
                "status": item.record["status"],
                "source_type": item.record["source_type"],
                "above_threshold": min_score is None or item.score >= min_score,
                "returned": record_id in returned_id_set,
            }
            if graph_candidate is not None and record_id in returned_id_set:
                summary.update(
                    {
                        "graph_depth": graph_candidate["depth"],
                        "graph_path": graph_candidate["path"],
                    }
                )
            candidates_payload.append(summary)
        graph_raw: dict[str, Any] = {}
        if graph_result is not None:
            graph_raw = {
                "algorithm": "graph-seed-spread-v1",
                "extractor_version": "graph-rules-v1",
                "seeds": list(graph_result.seeds),
                "seed_limit": graph_result.seed_limit,
                "frontier_cap": graph_result.frontier_cap,
                "max_depth": graph_result.max_depth,
                "visited_edges": graph_result.visited_edges,
                "pruned_digest": graph_result.pruned_digest,
            }
        graph_raw["replay"] = {
            "use_graph": graph_result is not None,
            "limit": limit,
            "min_score": min_score,
            "candidate_cap": self.recall_candidate_limit,
            "ranker_version": _RECORD_RANKER_VERSION,
            "record_weights": {
                "text": TEXT_WEIGHT,
                "trust": TRUST_WEIGHT,
                "recency": RECENCY_WEIGHT,
            },
            "fusion_version": (
                _GRAPH_FUSION_VERSION if graph_by_record else None
            ),
            "rrf_rank_constant": _RRF_RANK_CONSTANT,
            "graph_rrf_weight": _GRAPH_RRF_WEIGHT,
            "candidate_log_window": _CANDIDATE_LOG_WINDOW,
        }
        query_sha256 = _sha256(query)
        retained_query = query if self.retain_query_text else ""
        retrieval_id = self.store.insert_retrieval_event(
            subject_id=subject_id,
            session_id=session_id,
            query=retained_query,
            query_sha256=query_sha256,
            candidates=candidates_payload,
            returned_ids=returned_ids,
            raw=graph_raw,
        )
        # Digest over the retrieval evidence itself. The retrieval_events row
        # is not part of the hash chain; this binding makes edits to logged
        # candidate scores or paths detectable by an offline auditor.
        retrieval_sha256 = sha256_hex(
            canonical_json(
                {
                    "format": _RETRIEVAL_EVIDENCE_FORMAT,
                    "retrieval_id": retrieval_id,
                    "subject_id": subject_id,
                    "session_id": session_id,
                    "query": retained_query,
                    "query_sha256": query_sha256,
                    "candidates": candidates_payload,
                    "returned_ids": returned_ids,
                    "raw": graph_raw,
                }
            )
        )
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.recall",
            actor="system",
            session_id=session_id,
            payload={
                "retrieval_id": retrieval_id,
                "retrieval_sha256": retrieval_sha256,
                "retrieval_evidence_format": _RETRIEVAL_EVIDENCE_FORMAT,
                "returned_ids": returned_ids,
                "candidate_count": len(all_scored),
                "logged_candidate_count": len(candidates_payload),
                "min_score": min_score,
                "limit": limit,
                "algorithm": graph_raw.get("algorithm", "records-fts-v1"),
                "candidate_cap": self.recall_candidate_limit,
            },
        )
        results: list[dict[str, Any]] = []
        for item in returned:
            record = dict(item.record)
            graph_candidate = graph_by_record.get(record["id"])
            if graph_candidate is not None:
                record["graph"] = {
                    "edge_id": graph_candidate["edge_id"],
                    "relation": graph_candidate["relation"],
                    "score": graph_candidate["score"],
                    "depth": graph_candidate["depth"],
                    "path": graph_candidate["path"],
                }
            results.append(record)
        return results

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
                subject_id, statuses=("active", "quarantined", "superseded")
            )
            if needle in str(record.get("content") or "").lower()
        ]

        record_ids = [record["id"] for record in candidates]
        selector_sha256 = _sha256(needle)
        purged_ids, purged_episode_ids = self.store.tombstone_records(
            subject_id=subject_id, record_ids=record_ids
        )
        graph_mutations = self.graph.tombstone_records(subject_id, purged_ids)
        purged_graph_ids = [
            str(item["object_id"])
            for item in graph_mutations
            if item.get("object_id")
        ]
        self._audit_graph_mutations(
            subject_id,
            graph_mutations,
            session_id=session_id,
            turn_id=turn,
        )
        # The audit event carries the selector digest, never its text — the
        # needle usually names exactly the thing being erased.
        payload = {
            "selector_sha256": selector_sha256,
            "purged_record_ids": purged_ids,
            "purged_episode_ids": purged_episode_ids,
            "purged_graph_ids": purged_graph_ids,
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
            "purged_graph_ids": purged_graph_ids,
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
        use_graph: bool | None = None,
        reference_mode: str = "full",
        exclude_record_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Deterministic, bounded <relevant_memories> block for prompt injection.

        Uses recall() (so every candidate lands in retrieval_events), applies
        hard budgets, and writes a memory.context_injected audit event naming
        exactly which record IDs entered the agent's context. The default
        min_score of 0.3 requires a lexical match — trust/recency priors
        alone never inject.
        """
        if reference_mode not in {"full", "compact", "none"}:
            raise ValueError("reference_mode must be full, compact, or none")
        excluded = exclude_record_ids or set()
        records = self.recall(
            subject_id,
            query,
            session_id=session_id,
            limit=max_records + len(excluded),
            min_score=min_score,
            use_graph=use_graph,
        )
        lines: list[str] = []
        included: list[str] = []
        used = 0
        for record in records:
            if len(included) >= max_records:
                break
            if record["id"] in excluded:
                continue
            reference = _prompt_reference(str(record["id"]), reference_mode)
            line = f"- {reference}{record['content']}"
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
                "reference_mode": reference_mode,
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
        reference_mode: str = "full",
    ) -> dict[str, Any]:
        """L3: deterministic persona snapshot derived from active records.

        Keyed facts (stable slots like "preferred airport") come first,
        then unkeyed facts newest-first, under a hard character budget.
        No LLM, no stored copy — the persona is always derived live from
        L1, so it can never go stale, and every line carries the source
        record id. Building one writes a memory.persona_built audit event.
        """
        if reference_mode not in {"full", "compact", "none"}:
            raise ValueError("reference_mode must be full, compact, or none")
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
            reference = _prompt_reference(str(record["id"]), reference_mode)
            line = f"- {reference}{record['content']}"
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
                "reference_mode": reference_mode,
                "persona_sha256": _sha256(block),
            },
        )
        return {"block": block, "record_ids": included, "count": len(included)}

    @_atomic
    def build_context_pack(
        self,
        subject_id: str,
        query: str,
        *,
        session_id: str | None = None,
        persona_max_chars: int = 600,
        recall_max_records: int = 3,
        recall_max_chars: int = 1200,
        min_score: float = 0.3,
        use_graph: bool | None = None,
        reference_mode: str = "compact",
    ) -> dict[str, Any]:
        """Build a provider-neutral, cache-aware prompt context contract.

        ``stable_context`` is the deterministic persona prefix a host should
        keep in a stable system-prompt location. ``dynamic_context`` is the
        bounded, query-specific suffix a host should place close to the
        current user turn. The method does not call a model or depend on an
        agent framework, and the audit plane always retains full record IDs
        even when model-visible references are compact or omitted.
        """
        if min(persona_max_chars, recall_max_records, recall_max_chars) < 0:
            raise ValueError("context-pack budgets must be non-negative")

        persona = self.build_persona(
            subject_id,
            session_id=session_id,
            max_chars=persona_max_chars,
            reference_mode=reference_mode,
        )
        recall = self.build_recall_block(
            subject_id,
            query,
            session_id=session_id,
            max_records=recall_max_records,
            max_chars=recall_max_chars,
            min_score=min_score,
            use_graph=use_graph,
            reference_mode=reference_mode,
            exclude_record_ids=set(persona["record_ids"]),
        )
        stable = str(persona["block"])
        dynamic = str(recall["block"])
        result = {
            "format": "aetnamem-context-pack-v1",
            "stable_context": stable,
            "dynamic_context": dynamic,
            "stable_record_ids": list(persona["record_ids"]),
            "dynamic_record_ids": list(recall["record_ids"]),
            "stable_sha256": _sha256(stable),
            "dynamic_sha256": _sha256(dynamic),
            "placement": {
                "stable_context": "stable_system_prefix",
                "dynamic_context": "current_turn_tail",
            },
            "budgets": {
                "persona_max_chars": persona_max_chars,
                "recall_max_records": recall_max_records,
                "recall_max_chars": recall_max_chars,
            },
            "reference_mode": reference_mode,
        }
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.context_pack_built",
            actor="system",
            session_id=session_id,
            payload={
                "format": result["format"],
                "stable_record_ids": result["stable_record_ids"],
                "dynamic_record_ids": result["dynamic_record_ids"],
                "stable_sha256": result["stable_sha256"],
                "dynamic_sha256": result["dynamic_sha256"],
                "query_sha256": _sha256(query),
                "reference_mode": reference_mode,
            },
        )
        return result

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
            normalized_fact_key = str(fact_key).lower().strip() if fact_key else None
            confidence = float(proposal.get("confidence", 0.5))
            record_id = self.store.insert_record(
                subject_id=subject_id,
                content=content,
                source_type="derived",
                trust_tier="derived",
                source_session_id=session_id,
                source_turn_id=None,
                episode_id=None,
                confidence=confidence,
                scope="user_private",
                status="quarantined",
                fact_key=normalized_fact_key,
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
                    "fact_key": normalized_fact_key,
                    "confidence": confidence,
                    "scope": "user_private",
                    "evidence": evidence,
                    "content_sha256": _sha256(content),
                },
            )
            record = self.store.get_record(subject_id, record_id)
            assert record is not None
            self._audit_graph_mutations(
                subject_id,
                self.graph.index_record(record),
                session_id=session_id,
                record_id=record_id,
            )
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
        graph_mutations: list[dict[str, Any]] = []
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
                graph_mutations.extend(
                    self.graph.supersede_records(subject_id, older_ids, keeper["id"])
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
            graph_mutations.extend(
                self.graph.supersede_records(subject_id, older_ids, keeper["id"])
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
        self._audit_graph_mutations(
            subject_id, graph_mutations, session_id=session_id
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

        old_records = self.store.active_records_for_fact_key(
            subject_id, record.get("fact_key"), exclude_id=record_id
        )
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
        promoted = self.store.get_record(subject_id, record_id)
        assert promoted is not None
        graph_mutations = self.graph.supersede_records(subject_id, old_ids, record_id)
        graph_mutations.extend(self.graph.index_record(promoted))
        self._audit_graph_mutations(
            subject_id,
            graph_mutations,
            session_id=session_id,
            turn_id=_turn_id(turn_id),
            record_id=record_id,
        )
        return promoted

    @_atomic
    def backfill_graph(
        self,
        subject_id: str,
        *,
        rebuild: bool = False,
        session_id: str | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Populate the derived graph from canonical records.

        Backfill is idempotent. ``rebuild=True`` drops only graph index rows;
        records, episodes, retrieval events, and the audit chain are untouched.
        """
        if rebuild:
            self.graph.clear(subject_id)
        report = self.graph.backfill(subject_id)
        summary = {key: value for key, value in report.items() if key != "mutations"}
        summary["mutation_count"] = len(report["mutations"])
        summary["mutations_sha256"] = sha256_hex(canonical_json(report["mutations"]))
        self._audit_graph_mutations(
            subject_id,
            [
                mutation
                for mutation in report["mutations"]
                if mutation["event_type"] == "edge.reextracted"
            ],
            session_id=session_id,
        )
        if rebuild or report["records_indexed"]:
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="graph.rebuilt" if rebuild else "graph.backfilled",
                actor=actor,
                session_id=session_id,
                payload=summary,
            )
        return summary

    def inspect_graph(self, subject_id: str) -> dict[str, Any]:
        return self.graph.inspect(subject_id)

    @_atomic
    def consolidate_graph(
        self,
        subject_id: str,
        *,
        archive_root: str | Path | None = None,
        archive_before: str | None = None,
        prune_archive: bool = True,
        session_id: str | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Refresh derived graph state and propose only conservative merges."""
        backfill = self.graph.backfill(subject_id)
        self._audit_graph_mutations(
            subject_id,
            [
                mutation
                for mutation in backfill["mutations"]
                if mutation["event_type"] == "edge.reextracted"
            ],
            session_id=session_id,
        )
        merge_mutations = self.graph.propose_entity_merges(subject_id)
        self._audit_graph_mutations(
            subject_id, merge_mutations, session_id=session_id
        )
        archive = None
        if archive_root is not None and archive_before is not None:
            archive = self.graph.archive_history(
                subject_id,
                archive_root,
                before=archive_before,
                prune=prune_archive,
            )
            if archive["archived_edges"]:
                self.store.append_audit_event(
                    subject_id=subject_id,
                    event_type="graph.history_archived",
                    actor=actor,
                    session_id=session_id,
                    payload={
                        "before": archive_before,
                        "pruned": prune_archive,
                        "archived_edges": archive["archived_edges"],
                        "partitions": [
                            {
                                "id": item["id"],
                                "year": item["year"],
                                "row_count": item["row_count"],
                                "content_sha256": item["content_sha256"],
                                "archived_edge_ids_sha256": item[
                                    "archived_edge_ids_sha256"
                                ],
                            }
                            for item in archive["partitions"]
                        ],
                    },
                )
        report = {
            "extractor_version": GRAPH_EXTRACTOR_VERSION,
            "records_seen": backfill["records_seen"],
            "records_indexed": backfill["records_indexed"],
            "backfill_mutation_count": len(backfill["mutations"]),
            "backfill_mutations_sha256": sha256_hex(
                canonical_json(backfill["mutations"])
            ),
            "merge_proposals_created": len(merge_mutations),
            "pending_merge_proposals": len(
                self.graph.list_merge_proposals(subject_id, status="pending")
            ),
            "archive": archive,
            "counts": self.graph.counts(subject_id),
        }
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="graph.consolidated",
            actor=actor,
            session_id=session_id,
            payload={
                **report,
                "archive": (
                    {
                        "archived_edges": archive["archived_edges"],
                        "partition_ids": [item["id"] for item in archive["partitions"]],
                    }
                    if archive is not None
                    else None
                ),
            },
        )
        return report

    def list_graph_merge_proposals(
        self, subject_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        return self.graph.list_merge_proposals(subject_id, status=status)

    @_atomic
    def decide_graph_merge(
        self,
        subject_id: str,
        proposal_id: str,
        *,
        approve: bool,
        actor: str = "reviewer",
        winner_entity: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        mutation = self.graph.decide_merge(
            subject_id,
            proposal_id,
            approve=approve,
            actor=actor,
            winner_entity=winner_entity,
        )
        self._audit_graph_mutations(
            subject_id, [mutation], session_id=session_id
        )
        return next(
            item
            for item in self.graph.list_merge_proposals(subject_id)
            if item["id"] == proposal_id
        )

    @_atomic
    def revert_graph_merge(
        self,
        subject_id: str,
        proposal_id: str,
        *,
        actor: str = "reviewer",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        mutation = self.graph.revert_merge(subject_id, proposal_id, actor=actor)
        self._audit_graph_mutations(
            subject_id, [mutation], session_id=session_id
        )
        return next(
            item
            for item in self.graph.list_merge_proposals(subject_id)
            if item["id"] == proposal_id
        )

    @_atomic
    def archive_graph_history(
        self,
        subject_id: str,
        archive_root: str | Path,
        *,
        before: str,
        prune: bool = True,
        actor: str = "system",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        report = self.graph.archive_history(
            subject_id, archive_root, before=before, prune=prune
        )
        if report["archived_edges"]:
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="graph.history_archived",
                actor=actor,
                session_id=session_id,
                payload={
                    "before": before,
                    "pruned": prune,
                    "archived_edges": report["archived_edges"],
                    "partitions": [
                        {
                            key: item[key]
                            for key in (
                                "id",
                                "year",
                                "row_count",
                                "content_sha256",
                                "archived_edge_ids_sha256",
                            )
                        }
                        for item in report["partitions"]
                    ],
                },
            )
        return report

    def read_graph_archive(
        self, subject_id: str, *, partition_year: int | None = None
    ) -> list[dict[str, Any]]:
        return self.graph.read_archive(subject_id, partition_year=partition_year)

    def optimize(self) -> None:
        self.store.optimize()

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
        incremental: bool = False,
    ) -> dict[str, Any]:
        """Verify audit-chain integrity, optionally against anchored checkpoints.

        Chain verification alone detects edits and in-place tampering;
        checkpoint containment additionally detects tail truncation since the
        checkpoint was anchored.
        """
        heads = self.store.chain_heads()
        subject_ids = [subject_id] if subject_id is not None else sorted(heads)
        subjects: dict[str, Any] = {}
        for sid in subject_ids:
            incremental_report = (
                self.store.verify_audit_chain_incremental(sid)
                if incremental
                else None
            )
            subjects[sid] = {
                "chain_valid": (
                    incremental_report["valid"]
                    if incremental_report is not None
                    else self.store.verify_audit_chain(sid)
                ),
                "verification_mode": "incremental" if incremental else "full",
                "incremental": incremental_report,
                "checkpoints_checked": 0,
                "failures": (
                    [
                        {
                            "checkpoint": None,
                            "reason": incremental_report["failure"],
                        }
                    ]
                    if incremental_report is not None
                    and not incremental_report["valid"]
                    else []
                ),
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
            "graph": self.inspect_graph(subject_id),
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

    def _audit_graph_mutations(
        self,
        subject_id: str,
        mutations: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        record_id: str | None = None,
    ) -> None:
        for mutation in mutations:
            payload = {
                key: value for key, value in mutation.items() if key != "event_type"
            }
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type=str(mutation["event_type"]),
                actor="graph-indexer",
                session_id=session_id,
                turn_id=turn_id,
                record_id=str(mutation.get("record_id") or record_id or "") or None,
                payload=payload,
            )

    def reset_subject(self, subject_id: str) -> None:
        self.store.reset_subject(subject_id)


def _turn_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return f"t{value}"
    return str(value)


def _blend_graph_scores(
    lexical: list[ScoredRecord], graph_by_record: dict[str, dict[str, Any]]
) -> list[ScoredRecord]:
    """Reciprocal-rank fusion over direct record and graph rankings."""
    if not graph_by_record:
        return lexical
    lexical_rank = {
        str(item.record["id"]): rank for rank, item in enumerate(lexical, start=1)
    }
    graph_rank = _graph_ranks(graph_by_record)
    maximum = (1.0 + _GRAPH_RRF_WEIGHT) / (_RRF_RANK_CONSTANT + 1.0)
    blended: list[ScoredRecord] = []
    for item in lexical:
        record_id = str(item.record["id"])
        score = 1.0 / (_RRF_RANK_CONSTANT + lexical_rank[record_id])
        if record_id in graph_rank:
            graph_strength = max(
                0.0, min(float(graph_by_record[record_id]["score"]), 1.0)
            )
            score += (
                _GRAPH_RRF_WEIGHT
                * graph_strength
                / (_RRF_RANK_CONSTANT + graph_rank[record_id])
            )
        blended.append(
            ScoredRecord(
                record=item.record,
                score=round(score / maximum, 6),
                text_score=item.text_score,
                trust_score=item.trust_score,
                recency_score=item.recency_score,
            )
        )
    blended.sort(
        key=lambda item: (
            -item.score,
            str(item.record.get("created_at") or ""),
            str(item.record.get("id")),
        )
    )
    return blended


def _graph_ranks(
    graph_by_record: dict[str, dict[str, Any]],
) -> dict[str, int]:
    return {
        record_id: rank
        for rank, (record_id, _candidate) in enumerate(
            sorted(
                graph_by_record.items(),
                key=lambda item: (-float(item[1]["score"]), item[0]),
            ),
            start=1,
        )
    }


def _selector_contains(selector: dict[str, Any] | str | None) -> str | None:
    if selector is None:
        return None
    if isinstance(selector, str):
        return selector
    value = selector.get("contains") or selector.get("content_contains")
    return str(value) if value else None


def _sha256(value: str) -> str:
    return sha256_hex(value)


def _prompt_reference(record_id: str, mode: str) -> str:
    if mode == "none":
        return ""
    if mode == "compact":
        suffix = record_id.removeprefix("rec_")[:8]
        return f"[m:{suffix}] "
    return f"[{record_id}] "


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
