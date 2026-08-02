from __future__ import annotations

from functools import wraps
import json
from pathlib import Path
from typing import Any, Callable, TypeVar

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.core.policy import (
    TRUST_TIER_UNTRUSTED,
    classify_source,
    find_duplicate,
    forget_needle,
    initial_status,
    normalize_content,
    trust_tier_for_source,
)
from aetnamem.extract import extract_facts
from aetnamem.extract.rules import CandidateFact
from aetnamem.graph import GRAPH_EXTRACTOR_VERSION, GraphIndex
from aetnamem.media import MediaObservationEnvelope, normalize_media_sha256
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

    Core extraction stays deterministic. A trusted host may instead submit an
    explicit model-interpreted fact together with the exact typed user source;
    AetnaMem records that interpreter and the source/fact digests rather than
    running a hidden model of its own. The invariants that matter:

    - every semantic record derives from an episode and points back to it,
    - untrusted extractions are quarantined until explicitly promoted,
    - media bytes stay host-controlled while typed text observations retain
      exact-byte artifact, segment, and extractor provenance,
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
        interpreted_fact: str | None = None,
        interpreted_fact_key: str | None = None,
    ) -> dict[str, Any]:
        text = message if message is not None else fact
        if text is None:
            raise ValueError("remember() requires message or fact")
        turn = _turn_id(turn_id)
        source = source_type or classify_source(text)
        interpreted_candidate: CandidateFact | None = None
        if interpreted_fact is not None:
            if source != "user_message":
                raise ValueError("interpreted facts require a trusted user message")
            content = _explicit_note(interpreted_fact)
            if len(content) > 2_000:
                raise ValueError("interpreted fact exceeds 2,000 characters")
            interpreted_candidate = CandidateFact(
                content=content,
                confidence=1.0,
                source_type=source,
                trust_tier=trust_tier_for_source(source),
                fact_key=(
                    normalize_content(interpreted_fact_key)
                    if interpreted_fact_key
                    else None
                ),
                scope="host_agent_interpreted",
            )
            duplicate = self.store.find_duplicate_record(
                subject_id, content, statuses=("active",)
            )
            if duplicate is not None:
                self.store.append_audit_event(
                    subject_id=subject_id,
                    event_type="memory.semantic_interpretation_duplicate",
                    actor=actor,
                    session_id=session_id,
                    turn_id=turn,
                    record_id=duplicate["id"],
                    payload={
                        "interpreter": (raw or {}).get("interpreter"),
                        "interpretation_assurance": (raw or {}).get(
                            "interpretation_assurance", "caller_asserted"
                        ),
                        "source_binding": (raw or {}).get(
                            "source_binding", "caller_supplied"
                        ),
                        "source_message_sha256": _sha256(text),
                        "interpreted_fact_sha256": _sha256(content),
                        "fact_key": interpreted_candidate.fact_key,
                    },
                )
                return {
                    "episode_id": None,
                    "records": [],
                    "duplicate_ids": [duplicate["id"]],
                }
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

        if interpreted_fact is not None:
            assert interpreted_candidate is not None
            content = interpreted_candidate.content
            candidates = [interpreted_candidate]
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="memory.semantic_interpretation_received",
                actor=actor,
                session_id=session_id,
                turn_id=turn,
                payload={
                    "episode_id": episode_id,
                    "interpreter": (raw or {}).get("interpreter"),
                    "interpretation_assurance": (raw or {}).get(
                        "interpretation_assurance", "caller_asserted"
                    ),
                    "source_binding": (raw or {}).get(
                        "source_binding", "caller_supplied"
                    ),
                    "source_message_sha256": _sha256(text),
                    "interpreted_fact_sha256": _sha256(content),
                    "fact_key": interpreted_candidate.fact_key,
                },
            )
        else:
            candidates = extract_facts(text, source_type=source)
        if force and not candidates and source == "user_message":
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
                statuses=(
                    ("active",) if status == "active" else ("active", "quarantined")
                ),
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
                self.store.active_records_for_fact_key(subject_id, candidate.fact_key)
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
    def remember_observation(
        self,
        subject_id: str,
        envelope: dict[str, Any],
        *,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        actor: str = "media-observer",
        forced_assurance: str | None = None,
    ) -> dict[str, Any]:
        """Admit one typed, quarantined text observation of external media."""
        observation = MediaObservationEnvelope.from_mapping(
            envelope, forced_assurance=forced_assurance
        )
        turn = _turn_id(turn_id)
        artifact = None
        if observation.artifact_id:
            artifact = self.store.get_media_artifact(
                subject_id, artifact_id=observation.artifact_id
            )
            if artifact is None:
                raise ValueError(
                    f"media artifact not found: {observation.artifact_id!r}"
                )
            if artifact["media_sha256"] != observation.media_sha256:
                raise ValueError(
                    "artifact digest mismatch: the supplied artifact_id names "
                    "a different byte stream"
                )
        if artifact is None:
            artifact = self.store.get_media_artifact(
                subject_id, media_sha256=observation.media_sha256
            )
        if artifact is not None:
            if artifact["status"] != "active":
                raise ValueError(
                    "media artifact digest was previously tombstoned; "
                    "restoration is not implicit"
                )
            if artifact["modality"] != observation.modality:
                raise ValueError(
                    "media artifact modality mismatch: "
                    f"stored={artifact['modality']!r}, "
                    f"submitted={observation.modality!r}"
                )
        else:
            artifact = self.store.insert_media_artifact(
                subject_id=subject_id,
                media_sha256=observation.media_sha256,
                modality=observation.modality,
                host_reference=observation.host_reference,
                host_reference_sha256=observation.host_reference_sha256,
                digest_assurance=observation.digest_assurance,
            )

        duplicate = self.store.find_media_observation_by_envelope(
            subject_id, observation.envelope_sha256
        )
        if duplicate is not None and duplicate["status"] != "tombstoned":
            event_id = self.store.append_audit_event(
                subject_id=subject_id,
                event_type="media.observation_duplicate",
                actor=actor,
                session_id=session_id,
                turn_id=turn,
                record_id=duplicate["record_id"],
                payload={
                    "artifact_id": artifact["id"],
                    "observation_id": duplicate["id"],
                    "envelope_sha256": observation.envelope_sha256,
                },
            )
            record = self.store.get_record(subject_id, str(duplicate["record_id"]))
            assert record is not None
            return {
                "format": "aetnamem-media-admission-v1",
                "artifact": artifact,
                "observation": duplicate,
                "record": self._attach_media_provenance(subject_id, [record])[0],
                "duplicate": True,
                "audit_event_id": event_id,
            }

        previous = self.store.current_media_observations(
            subject_id, observation.lineage_sha256
        )
        episode_id = self.store.insert_episode(
            subject_id=subject_id,
            session_id=session_id,
            turn_id=turn,
            message=observation.text,
            source_type="tool_output",
            raw={
                "format": "aetnamem-media-observation-source-v1",
                "artifact_id": artifact["id"],
                "media_sha256": observation.media_sha256,
                "envelope_sha256": observation.envelope_sha256,
            },
        )
        record_id = self.store.insert_record(
            subject_id=subject_id,
            content=observation.text,
            source_type="tool_output",
            trust_tier=TRUST_TIER_UNTRUSTED,
            source_session_id=session_id,
            source_turn_id=turn,
            episode_id=episode_id,
            # Extractor confidence is retained on the evidence envelope only.
            # It must not influence memory ranking, trust, or promotion policy.
            confidence=None,
            scope="media_observation",
            status="quarantined",
            supersedes_id=None,
            fact_key=None,
            raw={
                "artifact_id": artifact["id"],
                "media_sha256": observation.media_sha256,
                "envelope_sha256": observation.envelope_sha256,
            },
        )
        stored_observation = self.store.insert_media_observation(
            subject_id=subject_id,
            artifact_id=str(artifact["id"]),
            episode_id=episode_id,
            record_id=record_id,
            text_sha256=observation.text_sha256,
            segment=observation.segment,
            segment_sha256=observation.segment_sha256,
            extractor=observation.extractor,
            extractor_sha256=observation.extractor_sha256,
            confidence=observation.confidence,
            digest_assurance=observation.digest_assurance,
            lineage_sha256=observation.lineage_sha256,
            envelope_sha256=observation.envelope_sha256,
            observed_at=observation.observed_at,
            supersedes_observation_id=(str(previous[-1]["id"]) if previous else None),
        )
        previous_ids = [str(item["id"]) for item in previous]
        superseded_record_ids = self.store.supersede_media_observations(
            subject_id,
            previous_ids,
            str(stored_observation["id"]),
        )
        stored_record = self.store.get_record(subject_id, record_id)
        assert stored_record is not None
        graph_mutations = self.graph.supersede_records(
            subject_id, superseded_record_ids, record_id
        )
        graph_mutations.extend(self.graph.index_record(stored_record))
        self._audit_graph_mutations(
            subject_id,
            graph_mutations,
            session_id=session_id,
            turn_id=turn,
            record_id=record_id,
        )
        event_id = self.store.append_audit_event(
            subject_id=subject_id,
            event_type="media.observation_admitted",
            actor=actor,
            session_id=session_id,
            turn_id=turn,
            record_id=record_id,
            payload={
                "artifact_id": artifact["id"],
                "media_sha256": observation.media_sha256,
                "modality": observation.modality,
                "observation_id": stored_observation["id"],
                "episode_id": episode_id,
                "record_id": record_id,
                "text_sha256": observation.text_sha256,
                "segment_sha256": observation.segment_sha256,
                "extractor_identity_sha256": observation.extractor_sha256,
                "host_reference_sha256": observation.host_reference_sha256,
                "lineage_sha256": observation.lineage_sha256,
                "envelope_sha256": observation.envelope_sha256,
                "digest_assurance": observation.digest_assurance,
                "confidence": observation.confidence,
                "status": "quarantined",
                "supersedes_observation_ids": previous_ids,
                "superseded_record_ids": superseded_record_ids,
            },
        )
        return {
            "format": "aetnamem-media-admission-v1",
            "artifact": artifact,
            "observation": stored_observation,
            "record": self._attach_media_provenance(subject_id, [stored_record])[0],
            "duplicate": False,
            "audit_event_id": event_id,
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
        include_scores: bool = False,
        _evidence: dict[str, Any] | None = None,
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
        lexical_by_record = {str(item.record["id"]): item for item in lexical_scored}
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
            str(record["id"]): rank for rank, record in enumerate(by_recency)
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
            "fusion_version": (_GRAPH_FUSION_VERSION if graph_by_record else None),
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
        if _evidence is not None:
            _evidence.update(
                {
                    "retrieval_id": retrieval_id,
                    "retrieval_sha256": retrieval_sha256,
                    "query_sha256": query_sha256,
                }
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
            if include_scores:
                # Compatibility surfaces such as OpenClaw's memory_search
                # need the actual audited rank score. Keep it opt-in so the
                # long-standing Python API result shape remains unchanged.
                record["score"] = item.score
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
        return self._attach_media_provenance(subject_id, results)

    def list(
        self,
        subject_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        statuses = None if include_inactive else ("active",)
        return self._attach_media_provenance(
            subject_id, self.store.list_records(subject_id, statuses=statuses)
        )

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
        cleanup = self._purge_record_ids(
            subject_id,
            record_ids,
            session_id=session_id,
            turn_id=turn,
        )
        purged_ids = cleanup["purged_record_ids"]
        purged_episode_ids = cleanup["purged_episode_ids"]
        purged_graph_ids = cleanup["purged_graph_ids"]
        semantic_index_cleanup = cleanup["semantic_index_cleanup"]
        # The audit event carries the selector digest, never its text — the
        # needle usually names exactly the thing being erased.
        payload = {
            "selector_sha256": selector_sha256,
            "purged_record_ids": purged_ids,
            "purged_episode_ids": purged_episode_ids,
            "purged_graph_ids": purged_graph_ids,
            "purged_count": len(purged_ids),
        }
        if cleanup["media_cleanup"]["observation_ids"]:
            payload["media_cleanup"] = cleanup["media_cleanup"]
        if semantic_index_cleanup is not None:
            payload["semantic_index_cleanup"] = semantic_index_cleanup
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
            "format": (
                "aetnamem-deletion-receipt-v2"
                if semantic_index_cleanup is not None
                else "aetnamem-deletion-receipt-v1"
            ),
            "subject_id": subject_id,
            "created_at": event["created_at"],
            "selector_sha256": selector_sha256,
            "purged_record_ids": purged_ids,
            "purged_episode_ids": purged_episode_ids,
            "purged_graph_ids": purged_graph_ids,
            "audit_event_id": event_id,
            "audit_event_hash": event["event_hash"],
        }
        if semantic_index_cleanup is not None:
            receipt["semantic_index_cleanup"] = semantic_index_cleanup
        if cleanup["media_cleanup"]["observation_ids"]:
            receipt["media_cleanup"] = cleanup["media_cleanup"]
        receipt["receipt_sha256"] = sha256_hex(canonical_json(receipt))
        return {
            "deleted": bool(purged_ids),
            "record_ids": purged_ids,
            "receipt": receipt,
        }

    @_atomic
    def forget_artifact(
        self,
        subject_id: str,
        media_sha256: str,
        *,
        artifact_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        """Purge AetnaMem objects linked to one exact media byte-stream digest."""
        digest = normalize_media_sha256(media_sha256)
        turn = _turn_id(turn_id)
        artifact = self.store.get_media_artifact(
            subject_id,
            artifact_id=artifact_id,
            media_sha256=None if artifact_id else digest,
        )
        if artifact is None:
            self.store.append_audit_event(
                subject_id=subject_id,
                event_type="media.artifact_forget_rejected",
                actor=actor,
                session_id=session_id,
                turn_id=turn,
                payload={
                    "media_sha256": digest,
                    "reason": "artifact not found",
                },
            )
            return {"deleted": False, "record_ids": [], "receipt": None}
        if artifact["media_sha256"] != digest:
            raise ValueError(
                "artifact digest mismatch: artifact_id and media_sha256 "
                "do not name the same byte stream"
            )
        if artifact["status"] == "tombstoned":
            return {"deleted": False, "record_ids": [], "receipt": None}

        observations = self.store.list_media_observations(
            subject_id,
            artifact_id=str(artifact["id"]),
            include_tombstoned=True,
        )
        observation_ids = [str(item["id"]) for item in observations]
        record_ids = list(
            dict.fromkeys(str(item["record_id"]) for item in observations)
        )
        episode_ids = list(
            dict.fromkeys(str(item["episode_id"]) for item in observations)
        )
        cleanup = self._purge_record_ids(
            subject_id,
            record_ids,
            session_id=session_id,
            turn_id=turn,
        )
        media_cleanup = self.store.tombstone_media_artifact(
            subject_id, str(artifact["id"])
        )
        records = self.store.get_records(subject_id, record_ids)
        records_tombstoned = all(
            record_id in records
            and records[record_id]["status"] == "tombstoned"
            and records[record_id]["content"] == ""
            for record_id in record_ids
        )
        episodes = {
            str(item["id"]): item
            for item in self.store.list_episodes(subject_id)
            if str(item["id"]) in episode_ids
        }
        episodes_purged = all(
            episode_id in episodes and episodes[episode_id]["message"] == "[purged]"
            for episode_id in episode_ids
        )
        verification = {
            "artifact_tombstoned": media_cleanup["artifact_tombstoned"],
            "observations_tombstoned": media_cleanup["observations_tombstoned"],
            "records_tombstoned": records_tombstoned,
            "episodes_purged": episodes_purged,
            "vectors_verified_absent": (
                cleanup["semantic_index_cleanup"] is None
                or cleanup["semantic_index_cleanup"]["verified_absent"]
            ),
            "verified_at": utc_now(),
        }
        verification["valid"] = all(
            value for key, value in verification.items() if key != "verified_at"
        )
        verification["report_sha256"] = sha256_hex(canonical_json(verification))
        if not verification["valid"]:
            raise RuntimeError(
                "artifact deletion could not be verified; transaction rolled back"
            )

        payload = {
            "artifact_id": artifact["id"],
            "media_sha256": digest,
            "host_reference_sha256": artifact["host_reference_sha256"],
            "digest_assurance": artifact["digest_assurance"],
            "purged_observation_ids": observation_ids,
            "linked_record_ids": record_ids,
            "linked_episode_ids": episode_ids,
            **{
                key: value
                for key, value in cleanup.items()
                if key != "semantic_index_cleanup"
            },
            "verification_report_sha256": verification["report_sha256"],
            "host_file_deleted": False,
        }
        if cleanup["semantic_index_cleanup"] is not None:
            payload["semantic_index_cleanup"] = cleanup["semantic_index_cleanup"]
        event_id = self.store.append_audit_event(
            subject_id=subject_id,
            event_type="media.artifact_forgotten",
            actor=actor,
            session_id=session_id,
            turn_id=turn,
            payload=payload,
        )
        event = self.store.get_audit_event(subject_id, event_id)
        receipt = {
            "format": "aetnamem-artifact-deletion-receipt-v1",
            "subject_id": subject_id,
            "created_at": event["created_at"],
            "artifact_id": artifact["id"],
            "media_sha256": digest,
            "digest_identity": "sha256-of-exact-byte-stream",
            "host_reference_sha256": artifact["host_reference_sha256"],
            "digest_assurance": artifact["digest_assurance"],
            "claim": (
                "All live AetnaMem objects linked through recorded observations "
                "to this exact byte-stream digest were purged or tombstoned."
            ),
            "host_file_deleted": False,
            "host_boundary": (
                "The host-controlled original, unregistered copies, "
                "re-encodings, backups, and unlinked observations are outside "
                "this receipt."
            ),
            "purged_observation_ids": observation_ids,
            "linked_record_ids": record_ids,
            "linked_episode_ids": episode_ids,
            "purged_record_ids": cleanup["purged_record_ids"],
            "purged_episode_ids": cleanup["purged_episode_ids"],
            "purged_graph_ids": cleanup["purged_graph_ids"],
            "verification": verification,
            "audit_event_id": event_id,
            "audit_event_hash": event["event_hash"],
        }
        if cleanup["semantic_index_cleanup"] is not None:
            receipt["semantic_index_cleanup"] = cleanup["semantic_index_cleanup"]
        receipt["receipt_sha256"] = sha256_hex(canonical_json(receipt))
        return {
            "deleted": True,
            "record_ids": cleanup["purged_record_ids"],
            "receipt": receipt,
        }

    def _purge_record_ids(
        self,
        subject_id: str,
        record_ids: list[str],
        *,
        session_id: str | None,
        turn_id: str | None,
    ) -> dict[str, Any]:
        cleanup_ids = list(dict.fromkeys(str(value) for value in record_ids))
        purged_ids, purged_episode_ids = self.store.tombstone_records(
            subject_id=subject_id, record_ids=cleanup_ids
        )
        graph_mutations = self.graph.tombstone_records(subject_id, purged_ids)
        purged_graph_ids = [
            str(item["object_id"]) for item in graph_mutations if item.get("object_id")
        ]
        self._audit_graph_mutations(
            subject_id,
            graph_mutations,
            session_id=session_id,
            turn_id=turn_id,
        )
        media_cleanup = self.store.tombstone_media_observations_for_records(
            subject_id, cleanup_ids
        )
        semantic_index_cleanup = None
        if cleanup_ids and self.store.path != ":memory:":
            from aetnamem.semantic import SemanticIndex, default_index_path

            registered = self.store.semantic_index_paths(subject_id)
            registered_by_path = {
                str(Path(item["index_path"]).expanduser().resolve()): item
                for item in registered
            }
            default_path = str(default_index_path(self.store.path).resolve())
            if Path(default_path).exists() and default_path not in registered_by_path:
                registered_by_path[default_path] = {
                    "index_path": default_path,
                    "index_path_sha256": sha256_hex(default_path),
                    "active_epoch_id": None,
                }
            cleanup_results: list[dict[str, Any]] = []
            for path_text, registry in sorted(registered_by_path.items()):
                index_path = Path(path_text)
                if not index_path.exists():
                    raise RuntimeError(
                        "registered semantic index is missing; deletion cannot "
                        f"verify vector cleanup ({registry['index_path_sha256']})"
                    )
                semantic_index = SemanticIndex(index_path)
                try:
                    if semantic_index.active_epoch(subject_id) is not None:
                        index_cleanup = semantic_index.purge(subject_id, cleanup_ids)
                        index_verification = semantic_index.verify(self, subject_id)
                        semantic_index.checkpoint_storage()
                        result = {
                            **index_cleanup,
                            "index_path_sha256": registry["index_path_sha256"],
                            "index_verification_valid": index_verification["valid"],
                            "verification_report_sha256": index_verification[
                                "report_sha256"
                            ],
                        }
                        cleanup_results.append(result)
                        if (
                            not index_cleanup["verified_absent"]
                            or not index_verification["valid"]
                        ):
                            raise RuntimeError(
                                "semantic index purge could not be verified; "
                                "canonical deletion was not committed"
                            )
                finally:
                    semantic_index.close()
            if cleanup_results:
                semantic_index_cleanup = {
                    "status": "verified_absent",
                    "verified_absent": True,
                    "indexes": cleanup_results,
                    "verified_at": utc_now(),
                }
                semantic_index_cleanup["result_sha256"] = sha256_hex(
                    canonical_json(semantic_index_cleanup)
                )
        return {
            "purged_record_ids": purged_ids,
            "purged_episode_ids": purged_episode_ids,
            "purged_graph_ids": purged_graph_ids,
            "media_cleanup": media_cleanup,
            "semantic_index_cleanup": semantic_index_cleanup,
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
        recall_evidence: dict[str, Any] = {}
        records = self.recall(
            subject_id,
            query,
            session_id=session_id,
            limit=max_records + len(excluded),
            min_score=min_score,
            use_graph=use_graph,
            _evidence=recall_evidence,
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
            return {
                "block": "",
                "record_ids": [],
                "count": 0,
                "retrieval_id": recall_evidence.get("retrieval_id"),
                "context_event_id": None,
            }

        block = "<relevant_memories>\n" + "\n".join(lines) + "\n</relevant_memories>"
        context_event_id = self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.context_injected",
            actor="system",
            session_id=session_id,
            payload={
                "record_ids": included,
                "reference_mode": reference_mode,
                "block_sha256": _sha256(block),
                "query_sha256": _sha256(query),
                "retrieval_id": recall_evidence.get("retrieval_id"),
                "retrieval_sha256": recall_evidence.get("retrieval_sha256"),
            },
        )
        return {
            "block": block,
            "record_ids": included,
            "count": len(included),
            "retrieval_id": recall_evidence.get("retrieval_id"),
            "context_event_id": context_event_id,
        }

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
        record_ids = {r["id"] for r in self.list(subject_id, include_inactive=True)}
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
        self._audit_graph_mutations(subject_id, graph_mutations, session_id=session_id)
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
        """Activate a quarantined record after explicit user confirmation.

        Media promotion is the deliberate trust boundary that closes an
        extraction lineage: an admitted rerun cannot displace active memory,
        but promoting it supersedes older active records from the exact same
        artifact + segment + extractor lineage.
        """
        media_observation = self.store.get_media_observation_for_record(
            subject_id, record_id
        )
        record = self.store.promote_record(subject_id=subject_id, record_id=record_id)
        if record is None:
            raise ValueError(f"record {record_id} is not quarantined for {subject_id}")

        old_records = self.store.active_records_for_fact_key(
            subject_id, record.get("fact_key"), exclude_id=record_id
        )
        lineage_records: list[dict[str, Any]] = []
        if media_observation is not None:
            lineage_records = self.store.active_media_records_for_lineage(
                subject_id,
                str(media_observation["lineage_sha256"]),
                exclude_record_id=record_id,
            )
        old_ids = list(
            dict.fromkeys(str(item["id"]) for item in [*old_records, *lineage_records])
        )
        superseded_observation_ids = [
            str(item["media_observation_id"]) for item in lineage_records
        ]
        self.store.supersede_records(
            subject_id=subject_id,
            record_ids=old_ids,
            superseded_by_id=record_id,
        )
        promotion_payload = {
            "trust_tier": record["trust_tier"],
            "fact_key": record.get("fact_key"),
            "supersedes": old_ids,
        }
        if media_observation is not None:
            promotion_payload.update(
                {
                    "media_lineage_sha256": media_observation["lineage_sha256"],
                    "superseded_observation_ids": superseded_observation_ids,
                }
            )
        self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.record_promoted",
            actor=actor,
            session_id=session_id,
            turn_id=_turn_id(turn_id),
            record_id=record_id,
            payload=promotion_payload,
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
        return self._attach_media_provenance(subject_id, [promoted])[0]

    @_atomic
    def reject(
        self,
        subject_id: str,
        record_id: str,
        *,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        """Reject and purge one quarantined record after human review.

        Rejection is deliberately narrower than free-form forgetting: the
        reviewer must name an exact quarantined record. Its content and any
        linked derived indexes are purged while a digest-only audit event
        preserves who made the decision and what record it covered.
        """
        turn = _turn_id(turn_id)
        record = self.store.get_record(subject_id, record_id)
        if record is None or record.get("status") != "quarantined":
            raise ValueError(f"record {record_id} is not quarantined for {subject_id}")
        content_sha256 = _sha256(str(record.get("content") or ""))
        cleanup = self._purge_record_ids(
            subject_id,
            [record_id],
            session_id=session_id,
            turn_id=turn,
        )
        event_id = self.store.append_audit_event(
            subject_id=subject_id,
            event_type="memory.record_rejected",
            actor=actor,
            session_id=session_id,
            turn_id=turn,
            record_id=record_id,
            payload={
                "content_sha256": content_sha256,
                "prior_status": "quarantined",
                "purged_record_ids": cleanup["purged_record_ids"],
                "purged_episode_ids": cleanup["purged_episode_ids"],
                "purged_graph_ids": cleanup["purged_graph_ids"],
                "media_cleanup": cleanup["media_cleanup"],
                "semantic_index_cleanup": cleanup["semantic_index_cleanup"],
            },
        )
        rejected = self.store.get_record(subject_id, record_id)
        assert rejected is not None
        return {
            "record": rejected,
            "decision": "rejected",
            "audit_event_id": event_id,
            "purged": record_id in cleanup["purged_record_ids"],
        }

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
        self._audit_graph_mutations(subject_id, merge_mutations, session_id=session_id)
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
        self._audit_graph_mutations(subject_id, [mutation], session_id=session_id)
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
        self._audit_graph_mutations(subject_id, [mutation], session_id=session_id)
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
                self.store.verify_audit_chain_incremental(sid) if incremental else None
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
                        {
                            "checkpoint": document.get("created_at"),
                            "reason": "checkpoint digest mismatch",
                        }
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
            "media_artifacts": self.store.list_media_artifacts(
                subject_id, include_tombstoned=True
            ),
            "media_observations": self.store.list_media_observations(
                subject_id, include_tombstoned=True
            ),
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

    def _attach_media_provenance(
        self, subject_id: str, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        provenance = self.store.media_provenance_for_records(
            subject_id, [str(record["id"]) for record in records]
        )
        return [
            (
                {
                    **record,
                    "media_observation": provenance[str(record["id"])],
                }
                if str(record["id"]) in provenance
                else record
            )
            for record in records
        ]

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
