#!/usr/bin/env python3
"""Generate the recall-forensics evidence reported by the governed-memory paper.

The workload and optional engine re-execution use aetnamem. The forensic
checks themselves use only Python's standard library and the durable SQLite
database. They verify a published evidence format instead of calling ranking,
graph, lifecycle, or audit helpers from the package under test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[2]
SUBJECT = "forensics"
EVIDENCE_FORMAT = "aetnamem-retrieval-evidence-v2"

TEXT_WEIGHT = 0.75
TRUST_WEIGHT = 0.15
RECENCY_WEIGHT = 0.10
TRUST_SCORES = {"trusted_user": 1.0, "user_confirmed": 0.9}
RRF_RANK_CONSTANT = 60.0
GRAPH_RRF_WEIGHT = 2.0
RANKER_VERSION = "record-rank-v1"
FUSION_VERSION = "weighted-rrf-v1"


QUERIES: list[dict[str, object]] = [
    # Three turns precede correction, deletion, and a later graph rebuild.
    {
        "query": "Which airport do I prefer?",
        "use_graph": False,
        "limit": 5,
        "min_score": None,
        "phase": "historical",
    },
    {
        "query": "What is my gate code?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "historical",
    },
    {
        "query": "What does my boss use for flights?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "historical",
    },
    # These turns run after the final canonical-record mutation. They are also
    # eligible for independent engine re-execution against the final store.
    {
        "query": "What does my boss use for flights?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "What does my boss use for flights?",
        "use_graph": False,
        "limit": 4,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "Which airport do I prefer?",
        "use_graph": True,
        "limit": 6,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "Which airport do I prefer?",
        "use_graph": False,
        "limit": 5,
        "min_score": 0.25,
        "phase": "stable",
    },
    {
        "query": "Where does my weekly report live?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "Where does my weekly report live?",
        "use_graph": False,
        "limit": 3,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "Who is my boss?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "What is my gate code?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "What airport did the webpage claim?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "What is my review day?",
        "use_graph": True,
        "limit": 5,
        "min_score": None,
        "phase": "stable",
    },
    {
        "query": "What is synthetic setting 137?",
        "use_graph": False,
        "limit": 7,
        "min_score": None,
        "phase": "stable",
    },
]


# ---------------------------------------------------------------------------
# Standard-library auditor
# ---------------------------------------------------------------------------


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def loads(value: str | None, default: object) -> object:
    return json.loads(value) if value else default


def open_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def chain_events(connection: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM audit_log WHERE subject_id = ? ORDER BY sequence",
            (SUBJECT,),
        )
    ]


def event_payload(event: dict) -> dict:
    return dict(loads(event["payload"], {}))


def event_hash(event: dict, previous_hash: str | None) -> str:
    preimage = {
        "event_id": event["event_id"],
        "subject_id": event["subject_id"],
        "event_type": event["event_type"],
        "created_at": event["created_at"],
        "actor": event["actor"],
        "session_id": event["session_id"],
        "turn_id": event["turn_id"],
        "record_id": event["record_id"],
        "payload": event_payload(event),
        "prev_hash": previous_hash,
    }
    return sha256_hex(canonical_json(preimage))


def verify_chain(connection: sqlite3.Connection) -> list[str]:
    failures: list[str] = []
    previous_hash = None
    previous_sequence = None
    for event in chain_events(connection):
        if previous_sequence is not None and event["sequence"] <= previous_sequence:
            failures.append(f"sequence {event['sequence']}: non-increasing sequence")
        if event["prev_hash"] != previous_hash:
            failures.append(f"sequence {event['sequence']}: prev_hash break")
        if event["event_hash"] != event_hash(event, previous_hash):
            failures.append(f"sequence {event['sequence']}: event_hash mismatch")
        previous_hash = event["event_hash"]
        previous_sequence = event["sequence"]
    return failures


def retrieval_preimage(row: sqlite3.Row | dict) -> dict:
    return {
        "format": EVIDENCE_FORMAT,
        "retrieval_id": row["id"],
        "subject_id": row["subject_id"],
        "session_id": row["session_id"],
        "query": row["query"],
        "query_sha256": row["query_sha256"],
        "candidates": loads(row["candidates"], []),
        "returned_ids": loads(row["returned_ids"], []),
        "raw": loads(row["raw"], {}),
    }


def verify_cross_digests(connection: sqlite3.Connection) -> list[str]:
    """Verify chain-bound retrieval, record, and episode commitments."""
    failures: list[str] = []
    for event in chain_events(connection):
        payload = event_payload(event)
        event_type = event["event_type"]
        if event_type == "memory.recall":
            retrieval_id = payload.get("retrieval_id")
            if payload.get("retrieval_evidence_format") != EVIDENCE_FORMAT:
                failures.append(f"{retrieval_id}: unsupported retrieval evidence format")
                continue
            row = connection.execute(
                "SELECT * FROM retrieval_events WHERE id = ?", (retrieval_id,)
            ).fetchone()
            if row is None:
                failures.append(f"{retrieval_id}: retrieval row missing")
                continue
            recomputed = sha256_hex(canonical_json(retrieval_preimage(row)))
            if recomputed != payload.get("retrieval_sha256"):
                failures.append(f"{retrieval_id}: retrieval digest mismatch")
            returned_ids = list(loads(row["returned_ids"], []))
            if returned_ids != payload.get("returned_ids"):
                failures.append(f"{retrieval_id}: returned ids disagree with audit event")
            if row["query"] and sha256_hex(row["query"]) != row["query_sha256"]:
                failures.append(f"{retrieval_id}: retained query does not match digest")
            raw = dict(loads(row["raw"], {}))
            replay = dict(raw.get("replay") or {})
            for audit_key, replay_key in (
                ("limit", "limit"),
                ("min_score", "min_score"),
                ("candidate_cap", "candidate_cap"),
            ):
                if payload.get(audit_key) != replay.get(replay_key):
                    failures.append(
                        f"{retrieval_id}: {audit_key} disagrees with replay envelope"
                    )
            if payload.get("logged_candidate_count") != len(
                list(loads(row["candidates"], []))
            ):
                failures.append(f"{retrieval_id}: logged candidate count mismatch")
        elif event_type in {"memory.record_created", "memory.record_quarantined"}:
            expected = payload.get("content_sha256")
            if not expected:
                failures.append(f"{event['record_id']}: missing admission content digest")
                continue
            row = connection.execute(
                "SELECT content, status FROM records WHERE id = ?",
                (event["record_id"],),
            ).fetchone()
            if row is None:
                failures.append(f"{event['record_id']}: admitted record row missing")
            elif row["status"] == "tombstoned":
                if row["content"] != "":
                    failures.append(f"{event['record_id']}: tombstone retained content")
            elif sha256_hex(row["content"]) != expected:
                failures.append(f"{event['record_id']}: record content digest mismatch")
        elif event_type == "episode.ingested":
            episode_id = payload.get("episode_id")
            row = connection.execute(
                "SELECT message FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone()
            if row is None:
                failures.append(f"{episode_id}: episode row missing")
            elif row["message"] not in {"", "[purged]"} and sha256_hex(
                row["message"]
            ) != payload.get("message_sha256"):
                failures.append(f"{episode_id}: episode message digest mismatch")
    return failures


def recall_turns(connection: sqlite3.Connection) -> list[dict]:
    turns: list[dict] = []
    for event in chain_events(connection):
        if event["event_type"] != "memory.recall":
            continue
        payload = event_payload(event)
        row = connection.execute(
            "SELECT * FROM retrieval_events WHERE id = ?",
            (payload.get("retrieval_id"),),
        ).fetchone()
        turns.append(
            {
                "sequence": event["sequence"],
                "event": event,
                "payload": payload,
                "retrieval": dict(row) if row is not None else None,
            }
        )
    return turns


def _mark_superseded(
    states: dict[str, dict], record_ids: list[str], sequence: int, failures: list[str]
) -> None:
    for record_id in record_ids:
        state = states.get(record_id)
        if state is None:
            failures.append(f"{record_id}: superseded before admission")
            continue
        if state["status"] not in {"active", "superseded"}:
            failures.append(
                f"{record_id}: invalid {state['status']} -> superseded transition"
            )
        state["status"] = "superseded"
        state["transitions"].append((sequence, "superseded"))


def lifecycle_states(
    events: list[dict], *, before_sequence: int | None = None
) -> tuple[dict[str, dict], list[str]]:
    """Replay record lifecycle events, optionally stopping before one turn."""
    states: dict[str, dict] = {}
    failures: list[str] = []
    for event in events:
        sequence = int(event["sequence"])
        if before_sequence is not None and sequence >= before_sequence:
            break
        event_type = event["event_type"]
        payload = event_payload(event)
        record_id = event.get("record_id")
        if event_type in {"memory.record_created", "memory.record_quarantined"}:
            if not record_id:
                failures.append(f"sequence {sequence}: admission without record id")
                continue
            if record_id in states:
                failures.append(f"{record_id}: duplicate admission")
                continue
            expected_status = (
                "active" if event_type == "memory.record_created" else "quarantined"
            )
            if payload.get("status") != expected_status:
                failures.append(f"{record_id}: admission event/status disagreement")
            states[record_id] = {
                "record_id": record_id,
                "subject_id": event["subject_id"],
                "status": expected_status,
                "source_type": payload.get("source_type"),
                "trust_tier": payload.get("trust_tier"),
                "episode_id": payload.get("episode_id"),
                "fact_key": payload.get("fact_key"),
                "confidence": payload.get("confidence"),
                "scope": payload.get("scope"),
                "content_sha256": payload.get("content_sha256"),
                "admission_sequence": sequence,
                "transitions": [(sequence, expected_status)],
            }
            _mark_superseded(
                states, list(payload.get("supersedes") or []), sequence, failures
            )
        elif event_type == "memory.record_promoted":
            state = states.get(str(record_id))
            if state is None:
                failures.append(f"{record_id}: promotion without admission")
                continue
            if state["status"] != "quarantined":
                failures.append(f"{record_id}: promotion from {state['status']}")
            state["status"] = "active"
            state["trust_tier"] = payload.get("trust_tier")
            state["transitions"].append((sequence, "active"))
            _mark_superseded(
                states, list(payload.get("supersedes") or []), sequence, failures
            )
        elif event_type == "memory.consolidated":
            superseded = list(payload.get("duplicates_superseded") or [])
            superseded.extend(list(payload.get("fact_key_repaired") or []))
            _mark_superseded(states, superseded, sequence, failures)
        elif event_type == "memory.forget":
            for forgotten_id in list(payload.get("purged_record_ids") or []):
                state = states.get(forgotten_id)
                if state is None:
                    failures.append(f"{forgotten_id}: forgotten before admission")
                    continue
                if state["status"] == "tombstoned":
                    failures.append(f"{forgotten_id}: duplicate tombstone transition")
                state["status"] = "tombstoned"
                state["fact_key"] = None
                state["transitions"].append((sequence, "tombstoned"))
    return states, failures


def verify_current_lifecycle(
    connection: sqlite3.Connection, events: list[dict]
) -> list[str]:
    states, failures = lifecycle_states(events)
    rows = {
        str(row["id"]): dict(row)
        for row in connection.execute(
            "SELECT * FROM records WHERE subject_id = ?", (SUBJECT,)
        )
    }
    for record_id, state in states.items():
        row = rows.get(record_id)
        if row is None:
            failures.append(f"{record_id}: canonical record row missing")
            continue
        for key in ("subject_id", "status", "source_type", "trust_tier", "episode_id"):
            if row.get(key) != state.get(key):
                failures.append(
                    f"{record_id}: current {key}={row.get(key)!r}, "
                    f"replayed={state.get(key)!r}"
                )
        if state["status"] == "tombstoned":
            if row["content"] != "" or row["fact_key"] is not None:
                failures.append(f"{record_id}: tombstone did not purge payload fields")
        else:
            for key in ("fact_key", "scope"):
                if row.get(key) != state.get(key):
                    failures.append(f"{record_id}: current {key} disagrees with admission")
            expected_confidence = state.get("confidence")
            if expected_confidence is None or row.get("confidence") is None:
                if expected_confidence != row.get("confidence"):
                    failures.append(f"{record_id}: confidence disagrees with admission")
            elif not math.isclose(
                float(row["confidence"]), float(expected_confidence), abs_tol=1e-12
            ):
                failures.append(f"{record_id}: confidence disagrees with admission")
    for record_id in sorted(set(rows) - set(states)):
        failures.append(f"{record_id}: canonical record has no admission event")

    purged_episode_ids = {
        episode_id
        for event in events
        if event["event_type"] == "memory.forget"
        for episode_id in event_payload(event).get("purged_episode_ids", [])
    }
    ingested = {
        event_payload(event).get("episode_id"): event
        for event in events
        if event["event_type"] == "episode.ingested"
    }
    episode_rows = {
        str(row["id"]): dict(row)
        for row in connection.execute(
            "SELECT * FROM episodes WHERE subject_id = ?", (SUBJECT,)
        )
    }
    for episode_id, event in ingested.items():
        row = episode_rows.get(str(episode_id))
        if row is None:
            failures.append(f"{episode_id}: canonical episode row missing")
            continue
        payload = event_payload(event)
        for key, expected in (
            ("subject_id", event["subject_id"]),
            ("session_id", event["session_id"]),
            ("turn_id", event["turn_id"]),
            ("source_type", payload.get("source_type")),
        ):
            if row.get(key) != expected:
                failures.append(f"{episode_id}: episode {key} disagrees with ingestion")
        if episode_id in purged_episode_ids:
            if row["message"] != "[purged]":
                failures.append(f"{episode_id}: deletion receipt without episode purge")
        elif sha256_hex(row["message"]) != payload.get("message_sha256"):
            failures.append(f"{episode_id}: episode content disagrees with ingestion")
    return failures


def _close(left: object, right: object, tolerance: float = 0.000002) -> bool:
    try:
        return math.isclose(float(left), float(right), abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def recompute_candidate(candidate: dict, replay: dict) -> list[str]:
    """Recompute lexical components, record score, and optional graph fusion."""
    failures: list[str] = []
    record_id = candidate.get("record_id")
    if candidate.get("text_method") == "fts5":
        raw = float(candidate.get("text_raw_score", 0.0))
        maximum = float(candidate.get("text_max_raw_score", 0.0))
        expected_text = raw / maximum if maximum > 0 else 0.0
    elif candidate.get("text_method") == "token-overlap":
        matches = int(candidate.get("text_overlap_matches", 0))
        terms = int(candidate.get("text_overlap_terms", 0))
        expected_text = matches / terms if terms > 0 else 0.0
    else:
        failures.append(f"{record_id}: unknown text-score method")
        expected_text = 0.0
    if not _close(candidate.get("text_score"), expected_text):
        failures.append(f"{record_id}: text score does not match recorded inputs")

    expected_trust = TRUST_SCORES.get(str(candidate.get("trust_tier")), 0.4)
    if not _close(candidate.get("trust_score"), expected_trust):
        failures.append(f"{record_id}: trust score does not match trust tier")

    denominator = int(candidate.get("recency_denominator", 0))
    recency_rank = int(candidate.get("recency_rank", -1))
    expected_recency = recency_rank / denominator if denominator > 0 else 0.0
    if not _close(candidate.get("recency_score"), expected_recency):
        failures.append(f"{record_id}: recency score does not match rank")

    expected_base = round(
        TEXT_WEIGHT * expected_text
        + TRUST_WEIGHT * expected_trust
        + RECENCY_WEIGHT * expected_recency,
        6,
    )
    if not _close(candidate.get("base_score"), expected_base):
        failures.append(f"{record_id}: record-score equation mismatch")

    expected_final = expected_base
    if replay.get("fusion_version") == FUSION_VERSION:
        lexical_rank = int(candidate.get("lexical_rank", 0))
        graph_rank = candidate.get("graph_rank")
        numerator = 1.0 / (RRF_RANK_CONSTANT + lexical_rank)
        if graph_rank is not None:
            strength = max(0.0, min(float(candidate.get("graph_score")), 1.0))
            numerator += (
                GRAPH_RRF_WEIGHT
                * strength
                / (RRF_RANK_CONSTANT + int(graph_rank))
            )
        maximum = (1.0 + GRAPH_RRF_WEIGHT) / (RRF_RANK_CONSTANT + 1.0)
        expected_final = round(numerator / maximum, 6)
    if not _close(candidate.get("score"), expected_final):
        failures.append(f"{record_id}: final ranking score mismatch")
    return failures


def verify_turn_evidence(turn: dict) -> list[str]:
    failures: list[str] = []
    row = turn.get("retrieval")
    if row is None:
        return [f"sequence {turn['sequence']}: retrieval row missing"]
    raw = dict(loads(row["raw"], {}))
    replay = dict(raw.get("replay") or {})
    expected_replay = {
        "ranker_version": RANKER_VERSION,
        "record_weights": {
            "text": TEXT_WEIGHT,
            "trust": TRUST_WEIGHT,
            "recency": RECENCY_WEIGHT,
        },
        "rrf_rank_constant": RRF_RANK_CONSTANT,
        "graph_rrf_weight": GRAPH_RRF_WEIGHT,
    }
    for key, expected in expected_replay.items():
        if replay.get(key) != expected:
            failures.append(f"{row['id']}: replay specification mismatch for {key}")

    candidates = list(loads(row["candidates"], []))
    returned_ids = list(loads(row["returned_ids"], []))
    if len({candidate.get("record_id") for candidate in candidates}) != len(candidates):
        failures.append(f"{row['id']}: duplicate candidate id")
    for index, candidate in enumerate(candidates, start=1):
        if candidate.get("rank") != index:
            failures.append(f"{row['id']}: non-contiguous logged rank at {index}")
        failures.extend(recompute_candidate(candidate, replay))
        threshold = replay.get("min_score")
        expected_above = threshold is None or float(candidate["score"]) >= float(
            threshold
        )
        if candidate.get("above_threshold") is not expected_above:
            failures.append(f"{candidate.get('record_id')}: threshold decision mismatch")
        expected_returned = candidate.get("record_id") in returned_ids
        if candidate.get("returned") is not expected_returned:
            failures.append(f"{candidate.get('record_id')}: returned flag mismatch")
        if index > 1:
            previous = candidates[index - 2]
            previous_key = (
                -float(previous["score"]),
                str(previous.get("created_at") or ""),
                str(previous.get("record_id") or ""),
            )
            current_key = (
                -float(candidate["score"]),
                str(candidate.get("created_at") or ""),
                str(candidate.get("record_id") or ""),
            )
            if previous_key > current_key:
                failures.append(f"{row['id']}: candidate ordering mismatch")

    eligible = [
        candidate["record_id"]
        for candidate in candidates
        if candidate.get("above_threshold")
    ]
    expected_ids = eligible[: int(replay.get("limit", 0))]
    if expected_ids != returned_ids:
        failures.append(f"{row['id']}: limit/threshold replay changed returned order")
    if turn["payload"].get("candidate_count", 0) < len(candidates):
        failures.append(f"{row['id']}: candidate count smaller than evidence ledger")
    return failures


def graph_states(events: list[dict], before_sequence: int) -> dict[str, dict]:
    states: dict[str, dict] = {}
    for event in events:
        if int(event["sequence"]) >= before_sequence:
            break
        event_type = event["event_type"]
        payload = event_payload(event)
        object_id = payload.get("object_id")
        if not object_id:
            continue
        if event_type in {"entity.created", "entity.recreated"}:
            states[object_id] = {
                "type": "entity",
                "status": payload.get("status", "active"),
            }
        elif event_type == "entity.activated":
            states.setdefault(object_id, {"type": "entity"})["status"] = "active"
        elif event_type in {"entity.tombstoned", "entity.merged"}:
            states.setdefault(object_id, {"type": "entity"})["status"] = event_type
        elif event_type == "alias.learned":
            states[object_id] = {
                "type": "alias",
                "status": payload.get("status"),
                "entity_id": payload.get("entity_id"),
            }
        elif event_type.startswith("alias.") and event_type != "alias.learned":
            states.setdefault(object_id, {"type": "alias"})["status"] = event_type
        elif event_type == "edge.asserted":
            states[object_id] = {
                "type": "edge",
                "status": payload.get("status"),
                "relation": payload.get("relation"),
                "src_entity": payload.get("src_entity"),
                "dst_entity": payload.get("dst_entity"),
                "record_id": payload.get("record_id") or event.get("record_id"),
            }
        elif event_type == "edge.status_changed":
            states.setdefault(object_id, {"type": "edge"})["status"] = payload.get(
                "status"
            )
        elif event_type.startswith("edge.") and event_type != "edge.asserted":
            if event_type in {
                "edge.superseded",
                "edge.tombstoned",
                "edge.reextracted",
                "edge.archive_purged",
            }:
                states.setdefault(object_id, {"type": "edge"})["status"] = event_type
    return states


def verify_historical_path(
    events: list[dict], turn: dict, candidate: dict
) -> tuple[bool, bool]:
    path = candidate.get("graph_path")
    if candidate.get("graph_rank") is None:
        return False, True
    if not isinstance(path, list) or not path:
        return True, False
    states = graph_states(events, int(turn["sequence"]))
    for step in path:
        if "alias_id" in step:
            state = states.get(step["alias_id"])
            if (
                state is None
                or state.get("type") != "alias"
                or state.get("status") != "active"
                or state.get("entity_id") != step.get("entity_id")
            ):
                return True, False
        elif "edge_id" in step:
            state = states.get(step["edge_id"])
            if state is None or state.get("type") != "edge" or state.get(
                "status"
            ) != "active":
                return True, False
            if step.get("relation") and state.get("relation") != step.get("relation"):
                return True, False
            entity_id = step.get("entity_id")
            if entity_id and entity_id not in {
                state.get("src_entity"),
                state.get("dst_entity"),
            }:
                return True, False
        elif "entity_id" in step:
            state = states.get(step["entity_id"])
            if state is None or state.get("type") != "entity" or state.get(
                "status"
            ) != "active":
                return True, False
        else:
            return True, False
    return True, True


def reconstruct_provenance(
    connection: sqlite3.Connection,
    events: list[dict],
    state: dict,
    turn_sequence: int,
) -> dict:
    episode_id = state.get("episode_id")
    if not episode_id:
        return {"complete": False, "payload_available": False}
    ingestion = next(
        (
            event
            for event in events
            if event["event_type"] == "episode.ingested"
            and event_payload(event).get("episode_id") == episode_id
            and int(event["sequence"]) < turn_sequence
        ),
        None,
    )
    if ingestion is None:
        return {"complete": False, "payload_available": False}
    ingestion_payload = event_payload(ingestion)
    row = connection.execute(
        "SELECT * FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()
    if row is None:
        return {"complete": False, "payload_available": False}
    purging_event = next(
        (
            event
            for event in events
            if event["event_type"] == "memory.forget"
            and episode_id in event_payload(event).get("purged_episode_ids", [])
        ),
        None,
    )
    payload_available = row["message"] != "[purged]"
    content_valid = (
        sha256_hex(row["message"]) == ingestion_payload.get("message_sha256")
        if payload_available
        else purging_event is not None
    )
    complete = (
        content_valid
        and ingestion_payload.get("source_type") == state.get("source_type")
        and row["source_type"] == state.get("source_type")
        and state.get("admission_sequence", turn_sequence) < turn_sequence
    )
    return {"complete": complete, "payload_available": payload_available}


def live_path_resolves(connection: sqlite3.Connection, candidate: dict) -> bool:
    path = candidate.get("graph_path")
    if not path:
        return True
    for step in path:
        if "alias_id" in step:
            row = connection.execute(
                "SELECT 1 FROM entity_aliases WHERE id = ? AND entity_id = ?",
                (step["alias_id"], step.get("entity_id")),
            ).fetchone()
        elif "edge_id" in step:
            row = connection.execute(
                "SELECT relation FROM edges WHERE id = ?", (step["edge_id"],)
            ).fetchone()
            if row is not None and step.get("relation") and row["relation"] != step.get(
                "relation"
            ):
                row = None
        elif "entity_id" in step:
            row = connection.execute(
                "SELECT 1 FROM entities WHERE id = ?", (step["entity_id"],)
            ).fetchone()
        else:
            row = None
        if row is None:
            return False
    return True


def verify_database(connection: sqlite3.Connection) -> list[str]:
    events = chain_events(connection)
    failures = verify_chain(connection)
    failures.extend(verify_cross_digests(connection))
    failures.extend(verify_current_lifecycle(connection, events))
    for turn in recall_turns(connection):
        failures.extend(verify_turn_evidence(turn))
    return failures


# ---------------------------------------------------------------------------
# Workload and engine re-execution
# ---------------------------------------------------------------------------


def load_memory_class():
    sys.path.insert(0, str(ROOT))
    from aetnamem import Memory

    return Memory


def build_workload(db_path: Path, filler: int) -> dict[str, object]:
    Memory = load_memory_class()
    memory = Memory(db_path, graph_recall=True, recall_candidate_limit=200)

    memory.remember(SUBJECT, "My boss is Sarah.", session_id="s1")
    memory.remember(SUBJECT, "Sarah's preferred airport is SEA.", session_id="s1")
    memory.remember(SUBJECT, "My preferred airport is SFO.", session_id="s1")
    memory.remember(SUBJECT, "My weekly report lives in report.md.", session_id="s2")
    memory.remember(SUBJECT, "My preferred meeting day is Tuesday.", session_id="s2")
    memory.remember(SUBJECT, "My espresso order is a double ristretto.", session_id="s2")

    quarantined = memory.remember(
        SUBJECT,
        "<webpage>My preferred airport is DEN.</webpage>",
        session_id="s2",
        source_type="webpage",
        actor="tool",
    )["records"][0]
    gate = memory.remember(
        SUBJECT, "My temporary gate code is 4471.", session_id="s2"
    )["records"][0]
    review = memory.remember(
        SUBJECT,
        "<webpage>My review day is Thursday.</webpage>",
        session_id="s2",
        source_type="webpage",
        actor="tool",
    )["records"][0]
    memory.promote(SUBJECT, review["id"], session_id="s2", actor="user")

    for index in range(filler):
        memory.remember(
            SUBJECT,
            f"My synthetic setting {index} is synthetic-value-{index}.",
            session_id="s3",
        )

    for query in [item for item in QUERIES if item["phase"] == "historical"]:
        memory.recall(
            SUBJECT,
            str(query["query"]),
            limit=int(query["limit"]),
            min_score=query["min_score"],
            use_graph=bool(query["use_graph"]),
            session_id="historical",
        )

    memory.remember(
        SUBJECT,
        "Actually, use OAK as my preferred airport going forward.",
        session_id="s4",
    )
    forget_receipt = memory.forget(
        SUBJECT, utterance="Forget my temporary gate code.", session_id="s4"
    )
    stable_start = memory.store.chain_heads()[SUBJECT]["sequence"] + 1

    for query in [item for item in QUERIES if item["phase"] == "stable"]:
        memory.recall(
            SUBJECT,
            str(query["query"]),
            limit=int(query["limit"]),
            min_score=query["min_score"],
            use_graph=bool(query["use_graph"]),
            session_id="stable",
        )

    # This destroys and reconstructs the live graph after all measured turns.
    # Historical path verification must therefore use the audit history rather
    # than require the old live graph row to survive.
    memory.backfill_graph(SUBJECT, rebuild=True, session_id="maintenance")
    checkpoint = memory.checkpoint()
    memory.close()
    return {
        "scenario_records_before_correction": 9,
        "quarantined_record_id": quarantined["id"],
        "promoted_record_id": review["id"],
        "forgotten_record_id": gate["id"],
        "stable_replay_start_sequence": stable_start,
        "forget_receipt_sha256": (forget_receipt.get("receipt") or {}).get(
            "receipt_sha256", ""
        ),
        "checkpoint_sha256": checkpoint.get("checkpoint_sha256", ""),
    }


def replay_stable_turns(db_path: Path, workdir: Path) -> dict[str, int]:
    """Re-execute only turns whose canonical inputs still exist unchanged."""
    source = open_db(db_path)
    turns = [
        turn
        for turn in recall_turns(source)
        if turn["retrieval"] is not None and turn["retrieval"]["session_id"] == "stable"
    ]
    source.close()
    query_by_digest = {
        sha256_hex(str(query["query"])): str(query["query"]) for query in QUERIES
    }
    candidate_caps = {
        int(dict(loads(turn["retrieval"]["raw"], {}))["replay"]["candidate_cap"])
        for turn in turns
    }
    if len(candidate_caps) != 1:
        raise AssertionError("stable turns use different candidate caps")

    copy = workdir / "stable-replay.db"
    shutil.copy(db_path, copy)
    Memory = load_memory_class()
    memory = Memory(
        copy,
        graph_recall=True,
        recall_candidate_limit=candidate_caps.pop(),
    )
    query_confirmed = 0
    returned_exact = 0
    ledgers_exact = 0
    for turn in turns:
        original = turn["retrieval"]
        digest = original["query_sha256"]
        query = query_by_digest.get(digest)
        if query is None:
            continue
        query_confirmed += 1
        replay = dict(dict(loads(original["raw"], {}))["replay"])
        rows = memory.recall(
            SUBJECT,
            query,
            limit=int(replay["limit"]),
            min_score=replay["min_score"],
            use_graph=bool(replay["use_graph"]),
            session_id="stable",
        )
        if [row["id"] for row in rows] == list(loads(original["returned_ids"], [])):
            returned_exact += 1
        regenerated = memory.get_retrieval_log(SUBJECT)[-1]
        if (
            regenerated["candidates"] == list(loads(original["candidates"], []))
            and regenerated["raw"] == dict(loads(original["raw"], {}))
        ):
            ledgers_exact += 1
    memory.close()
    return {
        "eligible_turns": len(turns),
        "query_confirmed": query_confirmed,
        "returned_exact": returned_exact,
        "candidate_ledgers_exact": ledgers_exact,
        "excluded_historical_turns": len(QUERIES) - len(turns),
    }


# ---------------------------------------------------------------------------
# Tamper trials
# ---------------------------------------------------------------------------


def tamper_trials(db_path: Path, workdir: Path, seed: int) -> dict[str, dict]:
    rng = random.Random(seed)
    connection = open_db(db_path)
    events = chain_events(connection)
    recall_sequences = [
        event["sequence"] for event in events if event["event_type"] == "memory.recall"
    ]
    active_records = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM records WHERE subject_id = ? AND status = 'active'",
            (SUBJECT,),
        )
    ]
    episodes = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM episodes WHERE subject_id = ? AND message != '[purged]'",
            (SUBJECT,),
        )
    ]
    retrieval_ids = [
        row["id"]
        for row in connection.execute(
            "SELECT id FROM retrieval_events WHERE subject_id = ?", (SUBJECT,)
        )
    ]
    connection.close()

    def mutate(name: str, sql: str, params: tuple) -> bool:
        copy = workdir / f"tamper-{name}-{rng.randrange(1 << 30)}.db"
        shutil.copy(db_path, copy)
        tampered = sqlite3.connect(str(copy))
        tampered.execute(sql, params)
        tampered.commit()
        tampered.close()
        checked = open_db(copy)
        detected = bool(verify_database(checked))
        checked.close()
        copy.unlink()
        return detected

    classes: dict[str, dict] = {}

    def run_class(name: str, sql: str, params_factory) -> None:
        trials = 5
        detected = sum(
            mutate(name, sql, tuple(params_factory())) for _ in range(trials)
        )
        classes[name] = {"trials": trials, "detected": detected}

    middle_sequences = [event["sequence"] for event in events[1:-1]]
    run_class(
        "audit_payload_edit",
        "UPDATE audit_log SET payload = json_set(payload, '$.forged', 1) "
        "WHERE subject_id = ? AND sequence = ?",
        lambda: (SUBJECT, rng.choice(middle_sequences)),
    )
    run_class(
        "audit_event_deletion",
        "DELETE FROM audit_log WHERE subject_id = ? AND sequence = ?",
        lambda: (SUBJECT, rng.choice(middle_sequences)),
    )
    run_class(
        "audit_returned_set_edit",
        "UPDATE audit_log SET payload = json_set(payload, '$.returned_ids[0]', "
        "'rec_forged') WHERE subject_id = ? AND sequence = ?",
        lambda: (SUBJECT, rng.choice(recall_sequences)),
    )
    run_class(
        "retrieval_candidate_score_edit",
        "UPDATE retrieval_events SET candidates = json_set(candidates, '$[0].score', 9.9) "
        "WHERE id = ?",
        lambda: (rng.choice(retrieval_ids),),
    )
    run_class(
        "retrieval_returned_set_edit",
        "UPDATE retrieval_events SET returned_ids = json_set(returned_ids, '$[0]', "
        "'rec_forged') WHERE id = ?",
        lambda: (rng.choice(retrieval_ids),),
    )
    run_class(
        "retrieval_parameter_edit",
        "UPDATE retrieval_events SET raw = json_set(raw, '$.replay.limit', 999) "
        "WHERE id = ?",
        lambda: (rng.choice(retrieval_ids),),
    )
    run_class(
        "retrieval_query_edit",
        "UPDATE retrieval_events SET query = 'forged query' WHERE id = ?",
        lambda: (rng.choice(retrieval_ids),),
    )
    run_class(
        "retrieval_subject_edit",
        "UPDATE retrieval_events SET subject_id = 'forged-subject' WHERE id = ?",
        lambda: (rng.choice(retrieval_ids),),
    )
    run_class(
        "record_content_edit",
        "UPDATE records SET content = 'forged fact' WHERE id = ?",
        lambda: (rng.choice(active_records)["id"],),
    )
    run_class(
        "record_status_edit",
        "UPDATE records SET status = 'quarantined' WHERE id = ?",
        lambda: (rng.choice(active_records)["id"],),
    )
    run_class(
        "record_trust_edit",
        "UPDATE records SET trust_tier = 'derived' WHERE id = ?",
        lambda: (rng.choice(active_records)["id"],),
    )
    run_class(
        "record_source_edit",
        "UPDATE records SET source_type = 'forged-source' WHERE id = ?",
        lambda: (rng.choice(active_records)["id"],),
    )
    run_class(
        "record_confidence_edit",
        "UPDATE records SET confidence = confidence + 0.123 WHERE id = ?",
        lambda: (rng.choice(active_records)["id"],),
    )
    run_class(
        "record_scope_edit",
        "UPDATE records SET scope = 'forged-scope' WHERE id = ?",
        lambda: (rng.choice(active_records)["id"],),
    )
    run_class(
        "episode_message_edit",
        "UPDATE episodes SET message = 'forged statement' WHERE id = ?",
        lambda: (rng.choice(episodes)["id"],),
    )

    def truncation_detected(with_checkpoint: bool) -> bool:
        copy = workdir / f"tamper-tail-{rng.randrange(1 << 30)}.db"
        shutil.copy(db_path, copy)
        tampered = sqlite3.connect(str(copy))
        cut = int(events[-3]["sequence"])
        tampered.execute(
            "DELETE FROM audit_log WHERE subject_id = ? AND sequence >= ?",
            (SUBJECT, cut),
        )
        tampered.commit()
        tampered.close()
        checked = open_db(copy)
        detected = bool(verify_chain(checked))
        if with_checkpoint and not detected:
            remaining = chain_events(checked)
            head = remaining[-1] if remaining else None
            anchor = events[-1]
            detected = (
                head is None
                or head["sequence"] < anchor["sequence"]
                or head["event_hash"] != anchor["event_hash"]
            )
        checked.close()
        copy.unlink()
        return detected

    classes["tail_truncation_chain_only"] = {
        "trials": 5,
        "detected": sum(truncation_detected(False) for _ in range(5)),
    }
    classes["tail_truncation_with_checkpoint"] = {
        "trials": 5,
        "detected": sum(truncation_detected(True) for _ in range(5)),
    }
    return classes


# ---------------------------------------------------------------------------
# Artifact identity and harness
# ---------------------------------------------------------------------------


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def source_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def source_snapshot() -> dict[str, object]:
    paths = sorted(ROOT.glob("aetnamem/**/*.py"))
    paths.extend([ROOT / "pyproject.toml", Path(__file__).resolve()])
    digests = {
        str(path.relative_to(ROOT)): file_sha256(path)
        for path in sorted(set(paths))
    }
    return {
        "base_commit": git_commit(),
        "package_version": source_version(),
        "state": "content-addressed post-v0.3.0 development snapshot",
        "source_files_sha256": digests,
        "source_manifest_sha256": sha256_hex(canonical_json(digests)),
    }


def run(filler: int, seed: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="aetnamem-forensics-") as temporary:
        workdir = Path(temporary)
        db_path = workdir / "memories.db"
        workload = build_workload(db_path, filler)

        started = perf_counter()
        connection = open_db(db_path)
        events = chain_events(connection)
        chain_failures = verify_chain(connection)
        digest_failures = verify_cross_digests(connection)
        lifecycle_failures = verify_current_lifecycle(connection, events)
        turns = recall_turns(connection)

        turn_failures: list[str] = []
        returned_pairs = 0
        attribution_complete = 0
        provenance_complete = 0
        lifecycle_complete = 0
        graph_paths = 0
        historical_paths_valid = 0
        current_graph_paths_missing = 0
        deleted_source_payload_pairs = 0
        promoted_pairs = 0
        states_by_turn: dict[int, dict[str, dict]] = {}

        for turn in turns:
            failures = verify_turn_evidence(turn)
            turn_failures.extend(failures)
            states, state_failures = lifecycle_states(
                events, before_sequence=int(turn["sequence"])
            )
            turn_failures.extend(state_failures)
            states_by_turn[int(turn["sequence"])] = states
            candidates = {
                candidate["record_id"]: candidate
                for candidate in loads(turn["retrieval"]["candidates"], [])
            }
            returned_ids = list(loads(turn["retrieval"]["returned_ids"], []))
            for record_id in returned_ids:
                returned_pairs += 1
                candidate = candidates.get(record_id)
                state = states.get(record_id)
                if candidate is None or state is None:
                    continue
                graph_nominated, path_valid = verify_historical_path(
                    events, turn, candidate
                )
                if graph_nominated:
                    graph_paths += 1
                    historical_paths_valid += int(path_valid)
                    current_graph_paths_missing += int(
                        not live_path_resolves(connection, candidate)
                    )
                pair_attribution = not failures and (
                    not graph_nominated or path_valid
                )
                attribution_complete += int(pair_attribution)

                provenance = reconstruct_provenance(
                    connection, events, state, int(turn["sequence"])
                )
                provenance_complete += int(provenance["complete"])
                deleted_source_payload_pairs += int(
                    provenance["complete"] and not provenance["payload_available"]
                )

                lifecycle_ok = (
                    state["status"] == "active"
                    and candidate.get("status") == "active"
                    and candidate.get("trust_tier") == state.get("trust_tier")
                    and candidate.get("source_type") == state.get("source_type")
                )
                lifecycle_complete += int(lifecycle_ok)
                if record_id == workload["promoted_record_id"]:
                    promoted_pairs += 1

        final_states, _ = lifecycle_states(events)
        quarantined_id = str(workload["quarantined_record_id"])
        forgotten_id = str(workload["forgotten_record_id"])
        quarantined_returned = sum(
            quarantined_id in loads(turn["retrieval"]["returned_ids"], [])
            for turn in turns
        )
        forgotten_after_transition = sum(
            forgotten_id in loads(turn["retrieval"]["returned_ids"], [])
            and states_by_turn[int(turn["sequence"])].get(forgotten_id, {}).get(
                "status"
            ) == "tombstoned"
            for turn in turns
        )
        forgotten_content_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE subject_id = ? "
                "AND status = 'tombstoned' AND content != ''",
                (SUBJECT,),
            ).fetchone()[0]
        )
        promoted_transition_verified = (
            final_states.get(str(workload["promoted_record_id"]), {}).get("status")
            == "active"
            and any(
                event["event_type"] == "memory.record_promoted"
                and event["record_id"] == workload["promoted_record_id"]
                for event in events
            )
        )
        connection.close()
        reconstruction_ms = (perf_counter() - started) * 1000

        replay = replay_stable_turns(db_path, workdir)
        tamper = tamper_trials(db_path, workdir, seed)

    return {
        "artifact": {
            **source_snapshot(),
            "script": "paper/scripts/run_recall_forensics_eval.py",
            "seed": seed,
        },
        "host": {
            "operating_system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "workload": {
            "scenario_records_before_correction": workload[
                "scenario_records_before_correction"
            ],
            "filler_records": filler,
            "recall_turns": len(QUERIES),
            "historical_turns": sum(
                query["phase"] == "historical" for query in QUERIES
            ),
            "stable_replay_turns": sum(query["phase"] == "stable" for query in QUERIES),
            "graph_recall_turns": sum(bool(query["use_graph"]) for query in QUERIES),
            "limits_tested": sorted({int(query["limit"]) for query in QUERIES}),
            "min_scores_tested": sorted(
                {
                    float(query["min_score"])
                    for query in QUERIES
                    if query["min_score"] is not None
                }
            ),
            "candidate_cap": 200,
            "stable_replay_start_sequence": workload[
                "stable_replay_start_sequence"
            ],
            "forget_receipt_sha256": workload["forget_receipt_sha256"],
            "checkpoint_sha256": workload["checkpoint_sha256"],
        },
        "results": {
            "baseline_chain_failures": len(chain_failures),
            "baseline_digest_failures": len(digest_failures),
            "baseline_lifecycle_failures": len(lifecycle_failures),
            "baseline_turn_semantic_failures": len(turn_failures),
            "returned_pairs": returned_pairs,
            "f1_attribution_recomputed": attribution_complete,
            "f1_ranking_turns_recomputed": len(turns)
            - sum(bool(verify_turn_evidence(turn)) for turn in turns),
            "f1_graph_paths": graph_paths,
            "f1_historical_paths_valid": historical_paths_valid,
            "f1_paths_missing_from_current_graph": current_graph_paths_missing,
            "f2_provenance_commitments_complete": provenance_complete,
            "f2_deleted_source_payload_pairs": deleted_source_payload_pairs,
            "f3_lifecycle_admissible": lifecycle_complete,
            "f3_promoted_record_pairs": promoted_pairs,
            "f3_promotion_transition_verified": promoted_transition_verified,
            "f4_stable_engine_reexecution": replay,
            "f5_tamper": tamper,
            "quarantined_results_returned": quarantined_returned,
            "forgotten_results_returned_after_deletion": forgotten_after_transition,
            "forgotten_content_rows_remaining": forgotten_content_rows,
            "reconstruction_ms_total": round(reconstruction_ms, 3),
        },
        "interpretation_limits": [
            "Single host, synthetic workload, fixed query list.",
            "Ranking arithmetic is recomputed from the bounded, digest-bound candidate "
            "ledger; candidate generation outside that ledger is not independently rerun.",
            "Three historical turns precede correction or deletion. Their decisions and "
            "paths remain reconstructable, but engine re-execution is intentionally "
            "excluded because deletion removes canonical plaintext by design.",
            "For a later-deleted source, the auditor verifies its ingestion digest, "
            "origin metadata, and deletion transition but cannot recover the plaintext.",
            "With query retention disabled, a query hypothesis can be checked against "
            "its digest; an unknown query cannot be recovered.",
            "Tamper trials cover the named single-row mutation classes. Whole-database "
            "rewriting and chain recomputation require an external checkpoint to detect.",
            "The source identity is a file-digest manifest over the exact development "
            "snapshot, not a claim that base release v0.3.0 contains these changes.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filler", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    document = json.dumps(run(args.filler, args.seed), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(document, encoding="utf-8")
    else:
        sys.stdout.write(document)


if __name__ == "__main__":
    main()
