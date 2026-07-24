"""Read-only discovery and trace reconstruction for memory evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch
import json
from typing import Any, Iterable

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.memory import Memory


_SCOPES = {
    "memories",
    "episodes",
    "retrievals",
    "events",
    "runs",
    "actions",
}
_ID_KEYS = {
    "event_id",
    "record_id",
    "episode_id",
    "retrieval_id",
    "run_id",
    "outcome_id",
    "transaction_id",
    "operation_id",
    "manifest_sha256",
}


def search_evidence(
    memory: Memory,
    subject_id: str,
    query: str = "",
    *,
    scope: str = "all",
    statuses: Iterable[str] | None = None,
    session_id: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    plane: str | None = None,
    outcome: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    mode: str = "lexical",
    semantic_index: Any | None = None,
    embedder: Any | None = None,
    min_similarity: float = 0.2,
    audit_access: bool = False,
    access_actor: str = "unauthenticated-cli",
    access_operation: str = "search",
) -> dict[str, Any]:
    """Search evidence, optionally recording access outside the agent audit chain."""
    if mode not in {"lexical", "semantic", "hybrid"}:
        raise ValueError("search mode must be lexical, semantic, or hybrid")
    selected_scopes = _selected_scopes(scope)
    status_filter = {value.lower() for value in statuses or ()}
    since_value = _time_bound(since, end=False)
    until_value = _time_bound(until, end=True)
    terms = [term.casefold() for term in query.split() if term.strip()]
    phrase = query.strip().casefold()

    results: list[dict[str, Any]] = []
    if "memories" in selected_scopes:
        for record in memory.list(subject_id, include_inactive=True):
            if status_filter and str(record.get("status", "")).lower() not in status_filter:
                continue
            results.append(_item("memory", record["id"], record, record.get("content", "")))

    if "episodes" in selected_scopes:
        for episode in memory.store.list_episodes(subject_id):
            results.append(
                _item("episode", episode["id"], episode, episode.get("message", ""))
            )

    if "retrievals" in selected_scopes:
        for retrieval in memory.store.list_retrieval_events(subject_id):
            query_label = retrieval.get("query") or f"query digest {retrieval.get('query_sha256', '')[:12]}"
            summary = f"{query_label} · returned {len(retrieval.get('returned_ids') or [])}"
            results.append(_item("retrieval", retrieval["id"], retrieval, summary))

    if "events" in selected_scopes:
        for event in memory.store.list_audit_events(subject_id):
            if event_type and not fnmatch(str(event["event_type"]), event_type):
                continue
            if actor and str(event.get("actor", "")).casefold() != actor.casefold():
                continue
            results.append(
                _item("event", event["event_id"], event, _event_summary(event))
            )

    if "runs" in selected_scopes:
        results.extend(_runtime_items(memory, subject_id))

    if "actions" in selected_scopes:
        results.extend(_action_items(memory, subject_id))

    eligible: list[dict[str, Any]] = []
    for item in results:
        data = item["data"]
        if session_id and str(data.get("session_id") or "") != session_id:
            continue
        if not _within_time(item.get("created_at"), since_value, until_value):
            continue
        if plane and not _contains_value(data, plane, keys={"plane", "planes", "candidate_planes", "admitted_planes"}):
            continue
        if outcome and not _matches_outcome(data, outcome):
            continue
        score = _match_score(item, phrase, terms)
        item["score"] = score
        eligible.append(item)

    lexical = [item for item in eligible if not terms or item["score"] > 0]
    lexical.sort(
        key=lambda item: (
            -float(item["score"]),
            str(item.get("created_at") or ""),
            str(item["id"]),
        )
    )
    for rank, item in enumerate(lexical, start=1):
        item["retrieval"] = {
            "mode": mode,
            "lexical_rank": rank,
            "semantic_rank": None,
            "similarity": None,
            "rrf_score": None,
        }

    semantic_by_id: dict[str, dict[str, Any]] = {}
    semantic_verification: dict[str, Any] | None = None
    if mode in {"semantic", "hybrid"} and terms:
        if "memories" not in selected_scopes:
            raise ValueError("semantic search requires a scope that includes memories")
        if semantic_index is None or embedder is None:
            raise ValueError(
                "semantic search requires an index and embedder; build one with "
                "`aetnamem index build` and supply the same provider configuration"
            )
        semantic_verification = semantic_index.verify(memory, subject_id)
        if not semantic_verification["valid"]:
            raise ValueError(
                "semantic index verification failed; run `aetnamem index verify` "
                f"and rebuild the index: {semantic_verification['failures']}"
            )
        semantic_results = semantic_index.search(
            memory,
            subject_id,
            query,
            embedder,
            statuses=tuple(status_filter) if status_filter else None,
            limit=max(limit * 4, 100),
            min_similarity=min_similarity,
        )
        semantic_by_id = {
            str(item["record_id"]): item for item in semantic_results
        }

    if mode == "semantic" and terms:
        filtered = [
            item
            for item in eligible
            if item["kind"] == "memory" and item["id"] in semantic_by_id
        ]
    elif mode == "hybrid" and terms:
        lexical_keys = {item["key"] for item in lexical}
        filtered = list(lexical)
        filtered.extend(
            item
            for item in eligible
            if item["kind"] == "memory"
            and item["id"] in semantic_by_id
            and item["key"] not in lexical_keys
        )
    else:
        filtered = lexical

    lexical_rank_by_key = {
        item["key"]: rank for rank, item in enumerate(lexical, start=1)
    }
    for item in filtered:
        semantic = semantic_by_id.get(item["id"]) if item["kind"] == "memory" else None
        lexical_rank = lexical_rank_by_key.get(item["key"])
        semantic_rank = semantic.get("semantic_rank") if semantic else None
        rrf_score = (
            (1.0 / (60 + lexical_rank) if lexical_rank else 0.0)
            + (1.0 / (60 + semantic_rank) if semantic_rank else 0.0)
        )
        item["retrieval"] = {
            "mode": mode,
            "lexical_rank": lexical_rank,
            "semantic_rank": semantic_rank,
            "similarity": semantic.get("similarity") if semantic else None,
            "rrf_score": rrf_score if mode == "hybrid" else None,
            "index_epoch": semantic.get("epoch_id") if semantic else None,
            "canonical_validation": (
                semantic.get("canonical_validation") if semantic else None
            ),
        }
    if mode == "semantic" and terms:
        filtered.sort(
            key=lambda item: (
                int(item["retrieval"]["semantic_rank"] or 10**9),
                str(item["id"]),
            )
        )
    elif mode == "hybrid" and terms:
        filtered.sort(
            key=lambda item: (
                -float(item["retrieval"]["rrf_score"] or 0.0),
                str(item["id"]),
            )
        )

    limited = filtered[: max(1, int(limit))]
    counts: dict[str, int] = {}
    for item in limited:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    report = {
        "format": "aetnamem-search-v1",
        "subject_id": subject_id,
        "query": query,
        "mode": mode,
        "scope": scope,
        "filters": {
            "statuses": sorted(status_filter),
            "session_id": session_id,
            "event_type": event_type,
            "actor": actor,
            "plane": plane,
            "outcome": outcome,
            "since": since,
            "until": until,
        },
        "audit_chain_valid": memory.store.verify_audit_chain(subject_id),
        "semantic_index_verification": (
            {
                "valid": semantic_verification["valid"],
                "epoch_id": semantic_verification["epoch_id"],
                "report_sha256": semantic_verification["report_sha256"],
            }
            if semantic_verification
            else None
        ),
        "matched": len(filtered),
        "returned": len(limited),
        "counts": counts,
        "results": limited,
    }
    if audit_access:
        report["access_audit_id"] = _audit_investigation_access(
            memory,
            report,
            operation=access_operation,
            actor=access_actor,
        )
    return report


def trace_evidence(
    memory: Memory,
    subject_id: str,
    query: str = "",
    *,
    session_id: str | None = None,
    run_id: str | None = None,
    record_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 500,
    mode: str = "lexical",
    semantic_index: Any | None = None,
    embedder: Any | None = None,
    min_similarity: float = 0.2,
    audit_access: bool = False,
    access_actor: str = "unauthenticated-cli",
) -> dict[str, Any]:
    """Find a clue, expand its relationships, and return a chronological story."""
    clues = [value for value in (query, session_id, run_id, record_id, event_type) if value]
    if not clues:
        raise ValueError("trace requires a query or one of --session/--run/--record/--event-type")

    initial_query = query or run_id or record_id or ""
    initial = search_evidence(
        memory,
        subject_id,
        initial_query,
        session_id=session_id,
        event_type=event_type,
        since=since,
        until=until,
        limit=limit,
        mode=mode,
        semantic_index=semantic_index,
        embedder=embedder,
        min_similarity=min_similarity,
    )
    all_evidence = search_evidence(
        memory,
        subject_id,
        "",
        since=since,
        until=until,
        limit=max(limit * 20, 10_000),
    )["results"]

    selected = {item["key"]: item for item in initial["results"]}
    known_ids = {record_id, run_id}
    known_ids.discard(None)
    known_sessions = {session_id} if session_id else set()
    for item in selected.values():
        known_ids.update(item["links"].values())
        value = item["data"].get("session_id")
        if value:
            known_sessions.add(str(value))

    # Resolve more than one hop: memory -> retrieval -> run -> outcome/action.
    for _ in range(4):
        changed = False
        for item in all_evidence:
            if item["key"] in selected:
                continue
            links = set(item["links"].values())
            item_session = item["data"].get("session_id")
            related = bool(links & known_ids)
            if item_session and str(item_session) in known_sessions:
                related = True
            if not related:
                continue
            selected[item["key"]] = item
            before = len(known_ids)
            known_ids.add(str(item["id"]))
            known_ids.update(links)
            if item_session:
                known_sessions.add(str(item_session))
            changed = changed or len(known_ids) != before
        if not changed:
            break

    timeline = sorted(
        selected.values(),
        key=lambda item: (
            str(item.get("created_at") or ""),
            _kind_order(item["kind"]),
            str(item["id"]),
        ),
    )[: max(1, int(limit))]
    counts: dict[str, int] = {}
    for item in timeline:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    report = {
        "format": "aetnamem-trace-v1",
        "subject_id": subject_id,
        "clue": {
            "query": query,
            "mode": mode,
            "session_id": session_id,
            "run_id": run_id,
            "record_id": record_id,
            "event_type": event_type,
            "since": since,
            "until": until,
        },
        "audit_chain_valid": initial["audit_chain_valid"],
        "semantic_index_verification": initial.get(
            "semantic_index_verification"
        ),
        "initial_matches": initial["returned"],
        "counts": counts,
        "timeline": timeline,
    }
    if audit_access:
        report["access_audit_id"] = _audit_investigation_access(
            memory,
            report,
            operation="trace",
            actor=access_actor,
        )
    return report


def _audit_investigation_access(
    memory: Memory,
    report: dict[str, Any],
    *,
    operation: str,
    actor: str,
) -> str:
    query = (
        report.get("query")
        if report.get("format") == "aetnamem-search-v1"
        else report.get("clue", {}).get("query")
    ) or ""
    filters = (
        report.get("filters")
        if report.get("format") == "aetnamem-search-v1"
        else report.get("clue", {})
    ) or {}
    results = report.get("results") or report.get("timeline") or []
    result_ids = [
        {"kind": item.get("kind"), "id": item.get("id")} for item in results
    ]
    semantic = report.get("semantic_index_verification") or {}
    if not semantic and report.get("format") == "aetnamem-trace-v1":
        semantic = {}
    return memory.store.append_investigation_access(
        subject_id=str(report["subject_id"]),
        operation=operation,
        actor=actor,
        query_digest=sha256_hex(query),
        filters_digest=sha256_hex(canonical_json(filters)),
        result_digest=sha256_hex(canonical_json(result_ids)),
        result_count=len(result_ids),
        index_epoch=semantic.get("epoch_id"),
        verification_report_digest=semantic.get("report_sha256"),
    )


def format_memories(report: dict[str, Any]) -> str:
    lines = [
        "AetnaMem memories",
        f"Subject: {report['subject_id']}",
        f"Integrity: {_integrity(report['audit_chain_valid'])}",
        f"Found: {report['returned']}",
        "",
    ]
    for item in report["results"]:
        data = item["data"]
        lines.extend(
            [
                f"[{data.get('status', 'unknown').upper()}] {item['summary'] or '(content purged)'}",
                f"  ID: {item['id']}",
                "  Source: "
                f"{data.get('source_type', 'unknown')} · trust: {data.get('trust_tier', 'unknown')}"
                f" · created: {item.get('created_at') or 'unknown'}",
            ]
        )
        retrieval = item.get("retrieval") or {}
        if retrieval.get("semantic_rank") is not None:
            lines.append(
                "  Match: "
                f"semantic rank {retrieval['semantic_rank']} · "
                f"similarity {float(retrieval['similarity']):.4f}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_search(report: dict[str, Any]) -> str:
    lines = [
        f"AetnaMem search ({report.get('mode', 'lexical')}): {report['query'] or '(all evidence)'}",
        f"Subject: {report['subject_id']}",
        f"Integrity: {_integrity(report['audit_chain_valid'])}",
        f"Matches: {report['matched']} · returned: {report['returned']}",
        "",
    ]
    for item in report["results"]:
        lines.extend(_format_item(item))
    return "\n".join(lines).rstrip() + "\n"


def format_trace(report: dict[str, Any]) -> str:
    clue = report["clue"]
    label = clue["query"] or clue["run_id"] or clue["record_id"] or clue["session_id"] or clue["event_type"]
    counts = ", ".join(f"{value} {key}" for key, value in sorted(report["counts"].items()))
    lines = [
        f"AetnaMem trace ({clue.get('mode', 'lexical')}): {label}",
        f"Subject: {report['subject_id']}",
        f"Integrity: {_integrity(report['audit_chain_valid'])}",
        f"Initial matches: {report['initial_matches']}",
        f"Timeline: {counts or 'no related evidence'}",
        "",
    ]
    for item in report["timeline"]:
        lines.extend(_format_item(item, timeline=True))
    return "\n".join(lines).rstrip() + "\n"


def _selected_scopes(scope: str) -> set[str]:
    if scope == "all":
        return set(_SCOPES)
    if scope not in _SCOPES:
        raise ValueError(f"unknown search scope: {scope}")
    return {scope}


def _item(kind: str, item_id: str, data: dict[str, Any], summary: str) -> dict[str, Any]:
    links = _links(data)
    links.setdefault(f"{kind}_id", str(item_id))
    return {
        "key": f"{kind}:{item_id}",
        "kind": kind,
        "id": str(item_id),
        "created_at": data.get("created_at") or data.get("updated_at"),
        "summary": _one_line(str(summary)),
        "score": 0,
        "links": links,
        "data": data,
    }


def _runtime_items(memory: Memory, subject_id: str) -> list[dict[str, Any]]:
    conn = memory.store._conn  # Shared read connection; no runtime migrations.
    if not _table_exists(conn, "runtime_runs"):
        return []
    items: list[dict[str, Any]] = []
    runs = conn.execute(
        "SELECT * FROM runtime_runs WHERE subject_id = ? ORDER BY created_at", (subject_id,)
    ).fetchall()
    for row in runs:
        run = _decoded_row(row)
        items.append(
            _item(
                "run",
                run["id"],
                run,
                f"runtime run {run['status']} · agent {run.get('agent_id', 'unknown')}",
            )
        )
        run_id = run["id"]
        for table, kind, summary_field in (
            ("runtime_contributions", "contribution", "plane"),
            ("context_manifests", "manifest", "manifest_sha256"),
            ("runtime_interventions", "intervention", "plane"),
            ("experience_outcomes", "outcome", "summary"),
        ):
            if not _table_exists(conn, table):
                continue
            for related in conn.execute(
                f"SELECT * FROM {table} WHERE run_id = ? ORDER BY created_at", (run_id,)
            ).fetchall():
                value = _decoded_row(related)
                item_id = (
                    value.get("id")
                    or value.get("decision_id")
                    or value.get("manifest_sha256")
                    or run_id
                )
                summary = str(value.get(summary_field) or kind)
                if kind == "outcome":
                    summary = (
                        f"{'success' if bool(value.get('success')) else 'failed'}"
                        f" · {summary or 'no summary'}"
                    )
                elif kind == "contribution":
                    summary = f"{summary} memory contribution"
                elif kind == "intervention":
                    summary = (
                        f"{summary} memory · "
                        f"{'included' if bool(value.get('applied')) else 'withheld'}"
                    )
                elif kind == "manifest":
                    summary = f"context manifest {summary[:12]}"
                items.append(
                    _item(kind, str(item_id), value, summary)
                )
    return items


def _action_items(memory: Memory, subject_id: str) -> list[dict[str, Any]]:
    conn = memory.store._conn
    if not _table_exists(conn, "action_transactions"):
        return []
    items: list[dict[str, Any]] = []
    transactions = conn.execute(
        "SELECT * FROM action_transactions WHERE subject_id = ? ORDER BY created_at",
        (subject_id,),
    ).fetchall()
    for row in transactions:
        transaction = _decoded_row(row)
        transaction_id = str(transaction["id"])
        items.append(
            _item(
                "action",
                transaction_id,
                transaction,
                f"{transaction.get('mode', 'action')} {transaction.get('state', '')}",
            )
        )
        if not _table_exists(conn, "action_operations"):
            continue
        for operation_row in conn.execute(
            "SELECT * FROM action_operations WHERE transaction_id = ? ORDER BY ordinal",
            (transaction_id,),
        ).fetchall():
            operation = _decoded_row(operation_row)
            items.append(
                _item(
                    "operation",
                    operation["id"],
                    operation,
                    f"{operation.get('adapter', '')}.{operation.get('operation', '')} {operation.get('state', '')}",
                )
            )
    return items


def _table_exists(conn: Any, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _decoded_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, str) and value[:1] in {"{", "["}:
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return result


def _links(value: Any, *, parent_key: str = "") -> dict[str, str]:
    links: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _ID_KEYS and child:
                _add_link(links, key, child)
            elif key in {"returned_ids", "memory_ids", "item_ids", "receipt_digests"}:
                for index, item in enumerate(child or []):
                    _add_link(links, f"{key}.{index}", item)
            for nested_key, nested_value in _links(child, parent_key=key).items():
                _add_link(links, nested_key, nested_value)
    elif isinstance(value, list):
        for child in value:
            for nested_key, nested_value in _links(child, parent_key=parent_key).items():
                _add_link(links, nested_key, nested_value)
    return links


def _add_link(links: dict[str, str], key: str, value: Any) -> None:
    text = str(value)
    if text in links.values():
        return
    candidate = key
    index = 1
    while candidate in links:
        candidate = f"{key}.{index}"
        index += 1
    links[candidate] = text


def _match_score(item: dict[str, Any], phrase: str, terms: list[str]) -> int:
    if not terms:
        return 0
    haystack = json.dumps(
        {
            "id": item["id"],
            "kind": item["kind"],
            "summary": item["summary"],
            "data": item["data"],
        },
        sort_keys=True,
        default=str,
    ).casefold()
    matched = sum(1 for term in terms if term in haystack)
    if matched != len(terms):
        return 0
    return matched * 10 + (20 if phrase and phrase in haystack else 0)


def _event_summary(event: dict[str, Any]) -> str:
    event_type = str(event["event_type"])
    payload = event.get("payload") or {}
    if event_type == "memory.record_created":
        return f"{event_type} · {payload.get('fact_key') or 'unkeyed memory'}"
    if event_type == "memory.record_quarantined":
        return f"{event_type} · source {payload.get('source_type', 'unknown')}"
    if event_type == "memory.recall":
        returned = payload.get("returned_ids") or []
        return f"{event_type} · returned {len(returned)}"
    if event_type == "runtime.prepare_turn":
        planes = ", ".join(payload.get("admitted_planes") or payload.get("planes") or [])
        return f"{event_type} · context from {planes or 'no memory planes'}"
    if event_type == "runtime.record_outcome":
        return (
            f"{event_type} · "
            f"{'success' if bool(payload.get('success')) else 'failed'}"
            f" · {payload.get('outcome_trust', 'unknown trust')}"
        )
    if event_type in {"agent.tool_call", "agent.model_call", "agent.response_shown"}:
        name = payload.get("tool") or payload.get("model") or payload.get("status")
        return f"{event_type}{f' · {name}' if name else ''}"
    if event_type == "memory.forget":
        purged = payload.get("purged_record_ids") or payload.get("record_ids") or []
        return f"{event_type} · purged {len(purged)} records"
    return event_type


def _contains_value(data: dict[str, Any], needle: str, *, keys: set[str]) -> bool:
    wanted = needle.casefold()
    for key in keys:
        value = data.get(key)
        if isinstance(value, list) and any(str(item).casefold() == wanted for item in value):
            return True
        if value is not None and str(value).casefold() == wanted:
            return True
    return False


def _matches_outcome(data: dict[str, Any], outcome: str) -> bool:
    wanted = outcome.casefold()
    success = data.get("success")
    if wanted in {"failed", "failure", "false"}:
        return success in {False, 0, "false"}
    if wanted in {"success", "succeeded", "true"}:
        return success in {True, 1, "true"}
    return str(data.get("status") or data.get("state") or "").casefold() == wanted


def _time_bound(value: str | None, *, end: bool) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if len(text) == 10:
        text += "T23:59:59.999999+00:00" if end else "T00:00:00+00:00"
    text = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _within_time(
    value: Any, since: datetime | None, until: datetime | None
) -> bool:
    if not value or (since is None and until is None):
        return True
    try:
        parsed = _time_bound(str(value), end=False)
    except ValueError:
        return False
    assert parsed is not None
    return (since is None or parsed >= since) and (until is None or parsed <= until)


def _one_line(value: str, limit: int = 160) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_item(item: dict[str, Any], *, timeline: bool = False) -> list[str]:
    prefix = f"{item.get('created_at') or 'unknown time'}  " if timeline else ""
    lines = [
        f"{prefix}{item['kind'].upper()}  {item['summary'] or '(no retained content)'}",
        f"  ID: {item['id']}",
    ]
    if item["links"]:
        visible = [f"{key}={value}" for key, value in sorted(item["links"].items()) if value != item["id"]]
        if visible:
            lines.append(f"  Links: {', '.join(visible[:8])}")
    retrieval = item.get("retrieval") or {}
    if retrieval.get("semantic_rank") is not None:
        parts = [
            f"semantic rank {retrieval['semantic_rank']}",
            f"similarity {float(retrieval['similarity']):.4f}",
        ]
        if retrieval.get("lexical_rank") is not None:
            parts.insert(0, f"lexical rank {retrieval['lexical_rank']}")
        if retrieval.get("rrf_score") is not None:
            parts.append(f"RRF {float(retrieval['rrf_score']):.6f}")
        lines.append(f"  Why matched: {' · '.join(parts)}")
        validation = retrieval.get("canonical_validation") or {}
        lines.append(
            "  Canonical: "
            f"subject={'yes' if validation.get('subject_matched') else 'no'} · "
            f"status={validation.get('status')} · "
            f"digest={'verified' if validation.get('digest_matched') else 'failed'}"
        )
    lines.append("")
    return lines


def _kind_order(kind: str) -> int:
    return {
        "episode": 1,
        "memory": 2,
        "retrieval": 3,
        "event": 4,
        "contribution": 5,
        "intervention": 6,
        "manifest": 7,
        "run": 8,
        "action": 9,
        "operation": 10,
        "outcome": 11,
    }.get(kind, 99)


def _integrity(valid: bool) -> str:
    return "VERIFIED (local hash chain)" if valid else "FAILED"
