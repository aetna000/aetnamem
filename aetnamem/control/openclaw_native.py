from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Iterable

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.memory import Memory
from aetnamem.store.sqlite import utc_now
from aetnamem.control.models import ControlState
from aetnamem.control.store import ControlStore

MIRROR_DB_NAME = "openclaw-mirror.db"
MIRROR_MANIFEST_NAME = "openclaw-mirror.json"
CUTOVER_NAME = "openclaw-cutover.json"
NATIVE_SNAPSHOT_MANIFEST_NAME = "openclaw-native-snapshot.json"
NATIVE_BASELINE_NAME = "openclaw-native-baseline"
NATIVE_BASELINE_MANIFEST_NAME = "openclaw-native-baseline.json"
SHADOW_HISTORY_NAME = "openclaw-shadow-history"
DEFAULT_RECALL_CHARS = 1200
NATIVE_MEMORY_ROOTS = (
    "MEMORY.md",
    "memory",
    "USER.md",
    "AGENTS.md",
    "TOOLS.md",
    "SOUL.md",
    "IDENTITY.md",
    "HEARTBEAT.md",
    "skills",
)
SUPPLEMENTAL_MEMORY_ROOTS = ("MEMORY.md", "memory")
ProgressReporter = Callable[[int, int, str], None]
MAX_REVIEW_IMAGE_BYTES = 25 * 1024 * 1024
MAX_REVIEW_MEDIA_FILES = 20_000


@dataclass(frozen=True)
class NativeSource:
    path: Path
    relative_path: str
    plane: str
    pinned: bool


def discover_workspace(openclaw: str | None = None) -> Path:
    executable = openclaw or shutil.which("openclaw")
    if executable:
        result = subprocess.run(
            [executable, "memory", "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                rows = payload if isinstance(payload, list) else [payload]
                for row in rows:
                    status = row.get("status") if isinstance(row, dict) else None
                    workspace = (
                        status.get("workspaceDir") if isinstance(status, dict) else None
                    )
                    if isinstance(workspace, str) and workspace.strip():
                        return Path(workspace).expanduser().resolve()
            except json.JSONDecodeError:
                pass
    return (Path.home() / ".openclaw" / "workspace").resolve()


def discover_sources(workspace: str | Path) -> list[NativeSource]:
    root = Path(workspace).expanduser().resolve()
    sources: list[NativeSource] = []

    def add(path: Path, plane: str, *, pinned: bool = False) -> None:
        if path.is_file() and not path.is_symlink():
            sources.append(
                NativeSource(
                    path=path,
                    relative_path=path.relative_to(root).as_posix(),
                    plane=plane,
                    pinned=pinned,
                )
            )

    add(root / "MEMORY.md", "semantic")
    add(root / "USER.md", "semantic", pinned=True)
    for path in sorted((root / "memory").glob("**/*.md")):
        add(path, "episodic")
    for name in ("AGENTS.md", "TOOLS.md", "SOUL.md", "IDENTITY.md", "HEARTBEAT.md"):
        add(root / name, "procedural", pinned=True)
    for path in sorted((root / "skills").glob("**/SKILL.md")):
        add(path, "procedural", pinned=True)
    return sources


def sync_mirror(
    state: ControlState,
    *,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    root = (
        Path(workspace).expanduser().resolve()
        if workspace is not None
        else discover_workspace()
    )
    control_dir = Path(state.control_dir)
    mirror_path = control_dir / MIRROR_DB_NAME
    manifest_path = control_dir / MIRROR_MANIFEST_NAME
    baseline = _ensure_native_baseline(control_dir, root)
    shadow_history = _record_shadow_version(control_dir, root, baseline)
    snapshot_root = Path(str(shadow_history["snapshot_root"]))
    sources = discover_sources(snapshot_root)
    source_rows = [_source_row(source) for source in sources]
    for source_row in source_rows:
        relative_path = str(source_row["relative_path"])
        source_row["snapshot_path"] = source_row["path"]
        source_row["path"] = str(root / relative_path)
    manifest_sha256 = sha256_hex(
        canonical_json(
            {
                "format": "aetnamem-openclaw-native-manifest-v1",
                "workspace": str(root),
                "sources": source_rows,
            }
        )
    )
    previous = _read_json(manifest_path)
    if (
        previous
        and previous.get("manifest_sha256") == manifest_sha256
        and mirror_path.is_file()
    ):
        previous["native_baseline"] = _snapshot_summary(baseline)
        previous["shadow_history"] = shadow_history
        _private_json(manifest_path, previous)
        return _mirror_status_from_manifest(previous, mirror_path)

    build_path = control_dir / f".{MIRROR_DB_NAME}.building"
    _remove_sqlite_files(build_path)
    memory = Memory(build_path)
    imported_records = 0
    imported_chunks = 0
    try:
        for source, source_row in zip(sources, source_rows):
            text = source.path.read_text(encoding="utf-8", errors="replace")
            for chunk in _markdown_chunks(text):
                result = memory.remember(
                    state.subject_id,
                    fact=chunk["text"],
                    force=True,
                    session_id=f"openclaw-native:{source.relative_path}",
                    turn_id=str(source_row["sha256"])[:16],
                    source_type="user_message",
                    actor="openclaw-shadow-import",
                    raw={
                        "format": "aetnamem-openclaw-native-source-v1",
                        "source_path": str(root / source.relative_path),
                        "snapshot_path": str(source.path),
                        "relative_path": source.relative_path,
                        "source_sha256": source_row["sha256"],
                        "line_start": chunk["line_start"],
                        "line_end": chunk["line_end"],
                        "plane": source.plane,
                        "pinned": source.pinned,
                    },
                )
                imported_records += len(result.get("records") or [])
                imported_chunks += 1
        memory.store.append_audit_event(
            subject_id=state.subject_id,
            event_type="host.memory_mirror_synchronized",
            actor="openclaw-shadow-import",
            payload={
                "migration_id": state.migration_id,
                "workspace_sha256": sha256_hex(str(root)),
                "manifest_sha256": manifest_sha256,
                "source_count": len(source_rows),
                "source_bytes": sum(int(row["bytes"]) for row in source_rows),
                "imported_chunks": imported_chunks,
                "record_count": imported_records,
            },
        )
        verification = memory.verify()
        if not verification.get("valid"):
            raise ValueError("AetnaMem mirror audit verification failed")
        memory.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        memory.close()

    _remove_sqlite_sidecars(build_path)
    os.replace(build_path, mirror_path)
    _remove_sqlite_sidecars(mirror_path)
    native_memory_chars = sum(
        int(row["bytes"]) for row in source_rows if row["relative_path"] == "MEMORY.md"
    )
    manifest = {
        "format": "aetnamem-openclaw-mirror-v1",
        "migration_id": state.migration_id,
        "subject_id": state.subject_id,
        "workspace": str(root),
        "mirror_db": str(mirror_path),
        "manifest_sha256": manifest_sha256,
        "source_count": len(source_rows),
        "source_bytes": sum(int(row["bytes"]) for row in source_rows),
        "native_memory_chars": native_memory_chars,
        "imported_chunks": imported_chunks,
        "record_count": imported_records,
        "sources": source_rows,
        "native_baseline": _snapshot_summary(baseline),
        "shadow_history": shadow_history,
        "synced_at": utc_now(),
    }
    _private_json(manifest_path, manifest)
    return _mirror_status_from_manifest(manifest, mirror_path)


def mirror_status(state: ControlState, *, refresh: bool = True) -> dict[str, Any]:
    control_dir = Path(state.control_dir)
    manifest = _read_json(control_dir / MIRROR_MANIFEST_NAME)
    cutover = _read_json(control_dir / CUTOVER_NAME)
    takeover_active = bool(
        cutover and cutover.get("status") in {"active", "emergency_off"}
    )
    if refresh and state.host == "openclaw" and not takeover_active:
        try:
            return sync_mirror(
                state,
                workspace=(
                    manifest.get("workspace") if isinstance(manifest, dict) else None
                ),
            )
        except Exception as exc:
            return {
                "status": "error",
                "synced": False,
                "error": str(exc),
                "mirror_db": str(Path(state.control_dir) / MIRROR_DB_NAME),
            }
    if not manifest:
        return {
            "status": "not_started",
            "synced": False,
            "mirror_db": str(Path(state.control_dir) / MIRROR_DB_NAME),
        }
    return _mirror_status_from_manifest(
        manifest, Path(state.control_dir) / MIRROR_DB_NAME
    )


def search_mirror(
    state: ControlState,
    query: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        records = memory.recall(
            state.subject_id,
            query,
            session_id=f"migration:{state.migration_id}:investigator",
            limit=max(1, min(int(limit), 100)),
            min_score=0.3,
        )
        episodes = {
            str(row["id"]): row for row in memory.store.list_episodes(state.subject_id)
        }
        for record in records:
            record["match_excerpt"] = _focused_excerpt(
                str(record.get("content") or ""), query
            )
            episode = episodes.get(str(record.get("episode_id") or ""))
            raw = episode.get("raw") if isinstance(episode, dict) else None
            if isinstance(raw, dict) and raw.get("format") in {
                "aetnamem-openclaw-native-source-v1",
                "aetnamem-control-plane-approved-source-v1",
            }:
                record["openclaw_provenance"] = raw
        return {
            "format": "aetnamem-openclaw-mirror-search-v1",
            "query": query,
            "subject_id": state.subject_id,
            "manifest_sha256": status.get("manifest_sha256"),
            "count": len(records),
            "records": records,
        }
    finally:
        memory.close()


def list_mirror_reviews(state: ControlState) -> dict[str, Any]:
    """Return the exact quarantined records awaiting a local human decision."""
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        records = [
            record
            for record in memory.list(state.subject_id, include_inactive=True)
            if record.get("status") == "quarantined"
        ]
        episodes = {
            str(row["id"]): row for row in memory.store.list_episodes(state.subject_id)
        }
        reviews: list[dict[str, Any]] = []
        for record in reversed(records):
            episode = episodes.get(str(record.get("episode_id") or "")) or {}
            episode_raw = (
                episode.get("raw") if isinstance(episode.get("raw"), dict) else {}
            )
            media = record.get("media_observation")
            extractor = media.get("extractor") if isinstance(media, dict) else None
            reviews.append(
                {
                    "record_id": record["id"],
                    "content": record.get("content") or "",
                    "created_at": record.get("created_at"),
                    "source_type": record.get("source_type"),
                    "scope": record.get("scope"),
                    "trust_tier": record.get("trust_tier"),
                    "source_session_id": record.get("source_session_id"),
                    "source_sha256": (
                        episode_raw.get("source_sha256")
                        or episode_raw.get("media_sha256")
                    ),
                    "media": (
                        {
                            "artifact_id": media.get("artifact_id"),
                            "modality": media.get("modality"),
                            "media_sha256": media.get("media_sha256"),
                            "digest_assurance": media.get("digest_assurance"),
                            "extractor": extractor,
                            "confidence": media.get("confidence"),
                            "preview_url": (
                                "/api/mirror/media-preview?record_id="
                                + str(record["id"])
                                if media.get("modality") == "image"
                                else None
                            ),
                            "recall_payload": "text_description",
                        }
                        if isinstance(media, dict)
                        else None
                    ),
                }
            )
        verification = memory.verify(state.subject_id)
        return {
            "format": "aetnamem-memory-review-queue-v1",
            "subject_id": state.subject_id,
            "count": len(reviews),
            "records": reviews,
            "audit_chain_valid": bool(verification.get("valid")),
        }
    finally:
        memory.close()


def resolve_mirror_review_image(state: ControlState, record_id: str) -> dict[str, Any]:
    """Resolve an exact, host-controlled image for an informed review.

    AetnaMem deliberately stores no media bytes or host filesystem path in the
    memory record. For a local OpenClaw review, this function finds a file only
    beneath OpenClaw's managed media directory and accepts it only after its
    streamed SHA-256 matches the artifact digest bound to the record.
    """
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    record_key = str(record_id or "").strip()
    if not record_key:
        raise ValueError("record_id is required")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        record = memory.store.get_record(state.subject_id, record_key)
        if record is None:
            raise ValueError("memory record was not found")
        if record.get("status") != "quarantined":
            raise ValueError("this record is no longer waiting for review")
        media = memory.store.media_provenance_for_records(
            state.subject_id, [record_key]
        ).get(record_key)
        if not media or media.get("modality") != "image":
            raise ValueError("this review is not an image observation")
        digest = str(media.get("media_sha256") or "")
    finally:
        memory.close()

    configured_root = os.environ.get("AETNAMEM_OPENCLAW_MEDIA_ROOT")
    root = (
        Path(configured_root).expanduser()
        if configured_root
        else Path.home() / ".openclaw" / "media"
    ).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("the OpenClaw source-image directory is unavailable")

    inspected = 0
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = [
            name for name in names if not (Path(directory) / name).is_symlink()
        ]
        for filename in filenames:
            inspected += 1
            if inspected > MAX_REVIEW_MEDIA_FILES:
                raise ValueError("source-image lookup exceeded the safe file limit")
            candidate = Path(directory) / filename
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
                size = resolved.stat().st_size
                if size <= 0 or size > MAX_REVIEW_IMAGE_BYTES:
                    continue
                hasher = hashlib.sha256()
                with resolved.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
                if hasher.hexdigest() != digest:
                    continue
            except (OSError, ValueError):
                continue
            content_type = mimetypes.guess_type(resolved.name)[0] or ""
            if not content_type.startswith("image/"):
                raise ValueError("the verified source bytes are not a supported image")
            return {
                "path": resolved,
                "content_type": content_type,
                "bytes": size,
                "media_sha256": digest,
            }
    raise ValueError("the exact source image is unavailable or its digest changed")


def review_mirror_record(
    state: ControlState,
    record_id: str,
    decision: str,
    *,
    actor: str = "dashboard-reviewer",
) -> dict[str, Any]:
    """Apply one explicit local approval or rejection to an exact record."""
    if not re.fullmatch(r"rec_[A-Za-z0-9]+", record_id):
        raise ValueError("record_id must be an AetnaMem record ID")
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    session_id = f"migration:{state.migration_id}:dashboard-review"
    try:
        before = memory.store.get_record(state.subject_id, record_id)
        if before is None or before.get("status") != "quarantined":
            raise ValueError("this record is no longer waiting for review")
        if decision == "approve":
            record = memory.promote(
                state.subject_id,
                record_id,
                session_id=session_id,
                actor=actor,
            )
            result: dict[str, Any] = {
                "decision": "approved",
                "record": record,
                "purged": False,
            }
        else:
            result = memory.reject(
                state.subject_id,
                record_id,
                session_id=session_id,
                actor=actor,
            )
        verification = memory.verify(state.subject_id)
        result.update(
            {
                "format": "aetnamem-memory-review-decision-v1",
                "record_id": record_id,
                "audit_chain_valid": bool(verification.get("valid")),
            }
        )
        return result
    finally:
        memory.close()


def _focused_excerpt(content: str, query: str, *, max_chars: int = 220) -> str:
    """Return the smallest useful sentence or bullet matching the query."""

    compact = " ".join(content.split())
    if not compact:
        return ""
    terms = tuple(
        dict.fromkeys(
            token
            for token in re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
            if token
        )
    )
    fragments = [
        fragment.strip("-*• \t")
        for fragment in re.split(
            r"(?<=[.!?])\s+|\n+|\s+-\s+(?=\S)",
            content,
        )
        if fragment.strip("-*• \t")
    ]
    query_folded = " ".join(query.casefold().split())

    def score(fragment: str) -> tuple[int, int, int]:
        folded = fragment.casefold()
        return (
            int(bool(query_folded and query_folded in folded)),
            sum(term in folded for term in terms),
            -len(fragment),
        )

    matching = [
        fragment
        for fragment in fragments
        if not terms or any(term in fragment.casefold() for term in terms)
    ]
    excerpt = max(matching, key=score) if matching else compact
    if len(excerpt) <= max_chars:
        return excerpt
    shortened = excerpt[: max(1, max_chars - 1)].rsplit(" ", 1)[0].rstrip()
    return (shortened or excerpt[: max_chars - 1]).rstrip() + "…"


def trace_mirror(
    state: ControlState,
    query: str,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    from aetnamem.investigate import trace_evidence

    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        return trace_evidence(
            memory,
            state.subject_id,
            query,
            limit=max(1, min(int(limit), 200)),
            audit_access=True,
            access_actor="openclaw-local-operator",
        )
    finally:
        memory.close()


def query_mirror_audit(
    state: ControlState,
    *,
    query: str = "",
    event_type: str = "",
    actor: str = "",
    session_id: str = "",
    record_id: str = "",
    since: str = "",
    until: str = "",
    cursor: int | None = None,
    limit: int = 100,
    direction: str = "desc",
    include_facets: bool = False,
) -> dict[str, Any]:
    """Search the full subject audit chain with stable cursor pagination."""
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        page = memory.store.query_audit_events(
            state.subject_id,
            query=query,
            event_type=event_type,
            actor=actor,
            session_id=session_id,
            record_id=record_id,
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
            direction=direction,
        )
        filters = {
            "query": query,
            "event_type": event_type,
            "actor": actor,
            "session_id": session_id,
            "record_id": record_id,
            "since": since,
            "until": until,
            "direction": direction,
        }
        event_identity = [
            {"sequence": row["sequence"], "event_hash": row["event_hash"]}
            for row in page["events"]
        ]
        verification = memory.store.verify_audit_chain_incremental(state.subject_id)
        result_digest = sha256_hex(canonical_json(event_identity))
        access_id = memory.store.append_investigation_access(
            subject_id=state.subject_id,
            operation="audit-explorer-search",
            actor="openclaw-local-operator",
            query_digest=sha256_hex(query),
            filters_digest=sha256_hex(canonical_json(filters)),
            result_digest=result_digest,
            result_count=len(page["events"]),
            verification_report_digest=sha256_hex(canonical_json(verification)),
        )
        report: dict[str, Any] = {
            "format": "aetnamem-audit-explorer-v1",
            "subject_id": state.subject_id,
            "filters": filters,
            "events": page["events"],
            "matched_total": page["matched_total"],
            "has_more": page["has_more"],
            "next_cursor": page["next_cursor"],
            "direction": page["direction"],
            "limit": page["limit"],
            "audit_chain_valid": bool(verification.get("valid")),
            "verification": verification,
            "result_digest": result_digest,
            "access_audit_id": access_id,
        }
        if include_facets:
            report["facets"] = memory.store.audit_event_facets(state.subject_id)
            report["histogram"] = memory.store.audit_event_histogram(
                state.subject_id,
                query=query,
                event_type=event_type,
                actor=actor,
                session_id=session_id,
                record_id=record_id,
                since=since,
                until=until,
                bucket="hour",
            )
        return report
    finally:
        memory.close()


def export_mirror_audit(
    state: ControlState,
    *,
    output_format: str,
    filters: dict[str, Any],
) -> tuple[str, str]:
    """Export a complete filtered evidence snapshot with verification metadata."""
    if output_format not in {"json", "ndjson", "csv", "text"}:
        raise ValueError("format must be json, ndjson, csv, or text")
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        events: list[dict[str, Any]] = []
        cursor: int | None = None
        while len(events) < 100_000:
            page = memory.store.query_audit_events(
                state.subject_id,
                query=str(filters.get("query") or ""),
                event_type=str(filters.get("event_type") or ""),
                actor=str(filters.get("actor") or ""),
                session_id=str(filters.get("session_id") or ""),
                record_id=str(filters.get("record_id") or ""),
                since=str(filters.get("since") or ""),
                until=str(filters.get("until") or ""),
                cursor=cursor,
                limit=500,
                direction=str(filters.get("direction") or "desc"),
            )
            events.extend(page["events"])
            cursor = page["next_cursor"]
            if not page["has_more"] or cursor is None:
                break
        verification = memory.store.verify_audit_chain_incremental(state.subject_id)
        identity = [
            {"sequence": row["sequence"], "event_hash": row["event_hash"]}
            for row in events
        ]
        report = {
            "format": "aetnamem-audit-export-v1",
            "created_at": utc_now(),
            "subject_id": state.subject_id,
            "filters": filters,
            "result_count": len(events),
            "truncated": len(events) >= 100_000,
            "audit_chain_valid": bool(verification.get("valid")),
            "verification": verification,
            "result_digest": sha256_hex(canonical_json(identity)),
            "events": events,
        }
        report["report_sha256"] = sha256_hex(canonical_json(report))
        memory.store.append_investigation_access(
            subject_id=state.subject_id,
            operation=f"audit-explorer-export-{output_format}",
            actor="openclaw-local-operator",
            query_digest=sha256_hex(str(filters.get("query") or "")),
            filters_digest=sha256_hex(canonical_json(filters)),
            result_digest=report["report_sha256"],
            result_count=len(events),
            verification_report_digest=sha256_hex(canonical_json(verification)),
        )
        if output_format == "json":
            return json.dumps(report, indent=2, sort_keys=True) + "\n", "application/json; charset=utf-8"
        if output_format == "ndjson":
            metadata = {key: value for key, value in report.items() if key != "events"}
            lines = [json.dumps({"metadata": metadata}, sort_keys=True)]
            lines.extend(json.dumps({"event": row}, sort_keys=True) for row in events)
            return "\n".join(lines) + "\n", "application/x-ndjson; charset=utf-8"
        if output_format == "csv":
            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(["sequence", "created_at", "event_type", "actor", "session_id", "turn_id", "record_id", "event_id", "event_hash", "payload_json"])
            for row in events:
                writer.writerow([
                    row.get("sequence"), row.get("created_at"), row.get("event_type"),
                    row.get("actor"), row.get("session_id"), row.get("turn_id"),
                    row.get("record_id"), row.get("event_id"), row.get("event_hash"),
                    canonical_json(row.get("payload") or {}),
                ])
            return stream.getvalue(), "text/csv; charset=utf-8"
        lines = [
            "AetnaMem audit investigation",
            f"Generated: {report['created_at']}",
            f"Subject: {state.subject_id}",
            f"Integrity: {'PASSED' if report['audit_chain_valid'] else 'FAILED'}",
            f"Events: {len(events)}",
            f"Report SHA-256: {report['report_sha256']}",
            f"Filters: {canonical_json(filters)}",
            "",
        ]
        for row in events:
            lines.extend([
                f"[{row['sequence']}] {row['created_at']}  {row['event_type']}",
                f"  actor={row['actor']} session={row.get('session_id') or '-'} record={row.get('record_id') or '-'}",
                f"  event={row['event_id']} hash={row['event_hash']}",
                f"  payload={canonical_json(row.get('payload') or {})}",
                "",
            ])
        return "\n".join(lines), "text/plain; charset=utf-8"
    finally:
        memory.close()


def inspect_mirror_record(state: ControlState, record_id: str) -> dict[str, Any]:
    """Build a human-facing, audit-bound history for one memory record."""
    from aetnamem.core.canonical import canonical_json, sha256_hex

    if not re.fullmatch(r"rec_[A-Za-z0-9]+", record_id):
        raise ValueError("record_id must be an AetnaMem record ID")
    status = mirror_status(state)
    if not status.get("synced"):
        raise ValueError(status.get("error") or "OpenClaw mirror is not synchronized")
    memory = Memory(status["mirror_db"], retain_query_text=True)
    try:
        record = memory.store.get_record(state.subject_id, record_id)
        events = memory.store.list_audit_events(state.subject_id)
        retrievals = memory.store.list_retrieval_events(state.subject_id)
        related_events = [
            event for event in events
            if event.get("record_id") == record_id
            or record_id in _event_record_ids(event)
        ]
        if record is None and not related_events:
            raise ValueError("record was not found in memory or retained audit evidence")

        episode = None
        episode_id = (record or {}).get("episode_id") or next(
            (
                event.get("payload", {}).get("episode_id")
                for event in related_events
                if event.get("payload", {}).get("episode_id")
            ),
            None,
        )
        if episode_id:
            episode = next(
                (
                    row for row in memory.store.list_episodes(state.subject_id)
                    if row.get("id") == episode_id
                ),
                None,
            )
        if episode_id:
            seen_event_ids = {str(event.get("event_id")) for event in related_events}
            for event in events:
                if (
                    event.get("payload", {}).get("episode_id") == episode_id
                    and str(event.get("event_id")) not in seen_event_ids
                ):
                    related_events.append(event)
                    seen_event_ids.add(str(event.get("event_id")))
        interpretation = next(
            (
                event for event in related_events
                if event.get("event_type")
                in {
                    "memory.semantic_interpretation_received",
                    "memory.semantic_interpretation_duplicate",
                }
            ),
            None,
        )
        if interpretation is None and episode:
            interpretation = next(
                (
                    event for event in events
                    if event.get("event_type") == "memory.semantic_interpretation_received"
                    and event.get("payload", {}).get("episode_id") == episode.get("id")
                ),
                None,
            )

        deliveries: list[dict[str, Any]] = []
        injections = [
            event for event in events
            if event.get("event_type") == "memory.context_injected"
            and record_id in (event.get("payload", {}).get("record_ids") or [])
        ]
        responses = [
            event for event in events
            if event.get("event_type") == "agent.response_after_memory"
            and record_id
            in (event.get("payload", {}).get("injected_record_ids") or [])
        ]
        for retrieval in retrievals:
            candidate = next(
                (
                    item for item in retrieval.get("candidates", [])
                    if item.get("record_id") == record_id
                ),
                None,
            )
            if not candidate:
                continue
            session_id = retrieval.get("session_id")
            retrieval_id = str(retrieval.get("id") or "")
            injection = next(
                (
                    event for event in injections
                    if str(event.get("payload", {}).get("retrieval_id") or "")
                    == retrieval_id
                ),
                None,
            )
            link_assurance = "exact-retrieval-id" if injection else None
            # Old evidence predates retrieval IDs on context events. Preserve
            # that history, but never turn a candidate-only row into a claimed
            # delivery and label the weaker association explicitly.
            if injection is None and candidate.get("returned"):
                injection = next(
                    (
                        event for event in injections
                        if not event.get("payload", {}).get("retrieval_id")
                        and event.get("session_id") == session_id
                        and str(event.get("created_at") or "")
                        >= str(retrieval.get("created_at") or "")
                    ),
                    None,
                )
                if injection:
                    link_assurance = "legacy-session-time"
            response = next(
                (
                    event for event in responses
                    if injection is not None
                    and (
                        str(event.get("payload", {}).get("context_event_id") or "")
                        == str(injection.get("event_id") or "")
                        or str(event.get("payload", {}).get("retrieval_id") or "")
                        == retrieval_id
                    )
                ),
                None,
            )
            response_link_assurance = "exact-context-or-retrieval-id" if response else None
            if response is None and injection is not None:
                response = next(
                    (
                        event for event in responses
                        if not event.get("payload", {}).get("context_event_id")
                        and not event.get("payload", {}).get("retrieval_id")
                        and event.get("session_id") == session_id
                        and str(event.get("created_at") or "")
                        >= str(injection.get("created_at") or "")
                    ),
                    None,
                )
                if response:
                    response_link_assurance = "legacy-session-time"
            deliveries.append(
                {
                    "retrieval_id": retrieval.get("id"),
                    "recalled_at": retrieval.get("created_at"),
                    "session_id": session_id,
                    "query_sha256": retrieval.get("query_sha256"),
                    "score": candidate.get("score"),
                    "rank": candidate.get("rank"),
                    "text_method": candidate.get("text_method"),
                    "returned": bool(candidate.get("returned")),
                    "context_injected_at": injection.get("created_at") if injection else None,
                    "context_event_id": injection.get("event_id") if injection else None,
                    "response_sha256": (
                        response.get("payload", {}).get("response_sha256")
                        if response else None
                    ),
                    "response_event_id": response.get("event_id") if response else None,
                    "link_assurance": link_assurance,
                    "response_link_assurance": response_link_assurance,
                }
            )

        created = next(
            (
                event for event in related_events
                if event.get("event_type")
                in {"memory.record_created", "memory.record_quarantined"}
                and event.get("record_id") == record_id
            ),
            None,
        )
        superseded = next(
            (
                event for event in events
                if record_id in (event.get("payload", {}).get("supersedes") or [])
            ),
            None,
        )
        deleted = next(
            (
                event for event in events
                if event.get("event_type")
                in {"memory.forget", "memory.record_rejected"}
                and record_id in (event.get("payload", {}).get("purged_record_ids") or [])
            ),
            None,
        )
        receipt = _deletion_receipt_from_event(state.subject_id, deleted) if deleted else None
        native = episode.get("raw") if episode and isinstance(episode.get("raw"), dict) else {}
        interpreted_payload = interpretation.get("payload", {}) if interpretation else {}
        provenance = {
            "source_message_sha256": (
                interpreted_payload.get("source_message_sha256")
                or (created or {}).get("payload", {}).get("content_sha256")
                or native.get("source_sha256")
            ),
            "interpreting_model": interpreted_payload.get("interpreter"),
            "interpretation_assurance": interpreted_payload.get(
                "interpretation_assurance"
            ),
            "source_binding": interpreted_payload.get("source_binding"),
            "episode_id": episode_id or native.get("episode_id"),
            "source_type": (record or {}).get("source_type") or native.get("source_type"),
            "native_path": native.get("relative_path"),
            "native_source_sha256": native.get("source_sha256"),
            "plane": native.get("plane") or (record or {}).get("scope"),
        }

        timeline = []
        retrieval_by_id = {str(row["id"]): row for row in retrievals}
        for event in related_events:
            timeline.append(_auditor_timeline_event(event, record_id))
        for delivery in deliveries:
            retrieval = retrieval_by_id.get(str(delivery["retrieval_id"]))
            if retrieval:
                timeline.append(
                    {
                        "at": retrieval.get("created_at"),
                        "type": "memory.retrieval_scored",
                        "title": "Candidate scored for recall",
                        "event_id": retrieval.get("id"),
                        "session_id": retrieval.get("session_id"),
                        "detail": (
                            f"rank {delivery['rank']} · score {delivery['score']} · "
                            f"{'returned' if delivery['returned'] else 'not returned'}"
                        ),
                    }
                )
        timeline.sort(key=lambda item: (str(item.get("at") or ""), str(item.get("event_id") or "")))
        verification = memory.verify(state.subject_id)
        subject_verification = verification.get("subjects", {}).get(state.subject_id, {})
        result = {
            "format": "aetnamem-record-investigation-v1",
            "subject_id": state.subject_id,
            "record_id": record_id,
            "record": record,
            "status": (record or {}).get("status") or ("deleted" if deleted else "audit-only"),
            "provenance": provenance,
            "lifecycle": {
                "created_at": (record or {}).get("created_at") or (created or {}).get("created_at"),
                "superseded_at": (superseded or {}).get("created_at"),
                "deleted_at": (record or {}).get("deleted_at") or (deleted or {}).get("created_at"),
            },
            "deliveries": deliveries,
            "timeline": timeline,
            "deletion_receipt": receipt,
            "audit_chain_valid": bool(subject_verification.get("chain_valid")),
            "audit_event_count": len(related_events),
        }
        result["report_sha256"] = sha256_hex(canonical_json(result))
        memory.store.append_investigation_access(
            subject_id=state.subject_id,
            operation="inspect-record",
            actor="openclaw-local-operator",
            query_digest=sha256_hex(record_id),
            filters_digest=sha256_hex(canonical_json({"record_id": record_id})),
            result_digest=result["report_sha256"],
            result_count=len(timeline),
        )
        return result
    finally:
        memory.close()


def format_mirror_record_report(report: dict[str, Any]) -> str:
    """Render a record investigation as a portable plain-text report."""
    record = report.get("record") or {}
    provenance = report.get("provenance") or {}
    lifecycle = report.get("lifecycle") or {}
    lines = [
        "AetnaMem record investigation",
        f"Record: {report['record_id']}",
        f"Status: {report.get('status', 'unknown')}",
        f"Audit integrity: {'PASSED' if report.get('audit_chain_valid') else 'FAILED'}",
        f"Report SHA-256: {report.get('report_sha256', 'not recorded')}",
        "",
        "Memory",
        str(record.get("content") or "Content was purged; only audit evidence remains."),
        "",
        "Provenance",
        f"Source message SHA-256: {provenance.get('source_message_sha256') or 'not recorded'}",
        f"Interpreting model: {provenance.get('interpreting_model') or 'not applicable / not recorded'}",
        f"Source binding: {provenance.get('source_binding') or 'not recorded'}",
        f"Native source: {provenance.get('native_path') or 'not applicable'}",
        "",
        "Lifecycle",
        f"Created: {lifecycle.get('created_at') or 'not recorded'}",
        f"Superseded: {lifecycle.get('superseded_at') or 'not superseded'}",
        f"Deleted: {lifecycle.get('deleted_at') or 'not deleted'}",
        "",
        "Deliveries",
    ]
    deliveries = report.get("deliveries") or []
    if not deliveries:
        lines.append("No recall of this record is recorded.")
    for delivery in deliveries:
        lines.append(
            f"- {delivery.get('recalled_at')}: rank {delivery.get('rank')}, "
            f"score {delivery.get('score')}, session {delivery.get('session_id') or 'none'}"
        )
        lines.append(
            "  Context injected: "
            + (delivery.get("context_injected_at") or "not recorded")
        )
        lines.append(
            "  Agent response SHA-256: "
            + (delivery.get("response_sha256") or "not recorded")
        )
    lines.extend(["", "Chronological evidence"])
    for item in report.get("timeline") or []:
        lines.append(
            f"- {item.get('at') or 'unknown time'} · {item.get('title') or item.get('type')}"
        )
        if item.get("detail"):
            lines.append(f"  {item['detail']}")
        lines.append(f"  Evidence ID: {item.get('event_id') or 'not recorded'}")
    return "\n".join(lines).rstrip() + "\n"


def _event_record_ids(event: dict[str, Any]) -> set[str]:
    ids = {str(event["record_id"])} if event.get("record_id") else set()
    payload = event.get("payload") or {}
    for key in (
        "record_ids", "injected_record_ids", "returned_ids", "purged_record_ids",
        "supersedes", "superseded_record_ids",
    ):
        ids.update(str(value) for value in (payload.get(key) or []))
    return ids


def _auditor_timeline_event(event: dict[str, Any], record_id: str) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "audit.event")
    titles = {
        "episode.ingested": "Source admitted",
        "memory.semantic_interpretation_received": "Source interpreted by the host model",
        "memory.record_created": "Memory record created",
        "memory.record_quarantined": "Memory record quarantined",
        "memory.record_promoted": "Memory approved for recall",
        "memory.record_rejected": "Memory rejected and purged",
        "memory.recall": "Memory returned by recall",
        "memory.context_injected": "Memory injected into agent context",
        "agent.response_after_memory": "Agent response bound to delivered memory",
        "memory.forget": "Memory deleted",
    }
    payload = event.get("payload") or {}
    detail = event_type
    if event_type == "memory.context_injected":
        detail = f"context block {str(payload.get('block_sha256') or '')[:16]}…"
    elif event_type == "agent.response_after_memory":
        detail = f"response digest {str(payload.get('response_sha256') or '')[:16]}…"
    elif event_type == "memory.forget":
        detail = f"verified purge of {len(payload.get('purged_record_ids') or [])} record(s)"
    elif event_type == "memory.record_rejected":
        detail = "reviewer rejected the exact candidate and verified its purge"
    elif event_type == "memory.recall":
        detail = f"retrieval {payload.get('retrieval_id') or 'unknown'}"
    elif event_type == "memory.semantic_interpretation_received":
        detail = f"model {payload.get('interpreter') or 'not recorded'}"
    return {
        "at": event.get("created_at"),
        "type": event_type,
        "title": titles.get(event_type, event_type.replace(".", " ").title()),
        "event_id": event.get("event_id"),
        "session_id": event.get("session_id"),
        "turn_id": event.get("turn_id"),
        "actor": event.get("actor"),
        "detail": detail,
        "event_hash": event.get("event_hash"),
        "record_id": record_id,
    }


def _deletion_receipt_from_event(
    subject_id: str, event: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not event:
        return None
    from aetnamem.core.canonical import canonical_json, sha256_hex

    payload = event.get("payload") or {}
    receipt: dict[str, Any] = {
        "format": (
            "aetnamem-deletion-receipt-v2"
            if payload.get("semantic_index_cleanup") is not None
            else "aetnamem-deletion-receipt-v1"
        ),
        "subject_id": subject_id,
        "created_at": event.get("created_at"),
        "selector_sha256": payload.get("selector_sha256"),
        "purged_record_ids": payload.get("purged_record_ids") or [],
        "purged_episode_ids": payload.get("purged_episode_ids") or [],
        "purged_graph_ids": payload.get("purged_graph_ids") or [],
        "audit_event_id": event.get("event_id"),
        "audit_event_hash": event.get("event_hash"),
    }
    if event.get("event_type") == "memory.record_rejected":
        receipt.update(
            {
                "review_decision": "rejected",
                "reviewed_record_id": event.get("record_id"),
                "review_actor": event.get("actor"),
            }
        )
    for key in ("semantic_index_cleanup", "media_cleanup"):
        if payload.get(key) is not None:
            receipt[key] = payload[key]
    receipt["receipt_sha256"] = sha256_hex(canonical_json(receipt))
    return receipt


def activate_takeover(
    state: ControlState,
    state_path: str | Path,
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    report = progress or (lambda _step, _total, _label: None)
    total_steps = 8
    report(1, total_steps, "Verifying the OpenClaw memory mirror")
    if state.host != "openclaw":
        raise ValueError("native-memory takeover is currently implemented for OpenClaw")
    status = sync_mirror(state)
    if not status.get("synced") or int(status.get("record_count") or 0) < 1:
        raise ValueError("OpenClaw memory mirror is empty or failed verification")
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH")
    report(2, total_steps, "Checking OpenClaw memory capabilities")
    capability_report = inspect_native_memory_capabilities(executable)
    if not capability_report["safe_to_switch"]:
        details = "; ".join(capability_report["blocking_reasons"])
        raise ValueError(
            "OpenClaw memory takeover stopped because configured native "
            f"capabilities would be lost: {details}"
        )

    control_dir = Path(state.control_dir)
    cutover_path = control_dir / CUTOVER_NAME
    if cutover_path.exists():
        current = _read_json(cutover_path) or {}
        if current.get("status") == "active":
            return _cutover_public(current)
        if current.get("status") in {"rolled_back", "rolled_back_after_failure"}:
            _archive_completed_cutover(control_dir, current)
        else:
            status_name = str(current.get("status") or "unknown")
            raise ValueError(
                "AetnaMem found an interrupted OpenClaw switch "
                f"(status: {status_name}). Native memory may already be "
                "frozen. Choose Restore OpenClaw in the dashboard or run "
                "`aetnamem control restore`; restoration verifies the saved "
                "files before another activation is allowed."
            )

    workspace = Path(str(status["workspace"]))
    archive = _new_cutover_archive(control_dir)
    prior_slot = _optional_json(
        [executable, "config", "get", "plugins.slots.memory", "--json"]
    )
    prior_session_hook = _optional_json(
        [
            executable,
            "config",
            "get",
            "hooks.internal.entries.session-memory",
            "--json",
        ]
    )
    prior_plugin_entry = _optional_json(
        [
            executable,
            "config",
            "get",
            "plugins.entries.memory-aetnamem",
            "--json",
        ]
    )
    prior_tools_also_allow = _optional_json(
        [executable, "config", "get", "tools.alsoAllow", "--json"]
    )
    cutover: dict[str, Any] = {
        "format": "aetnamem-openclaw-cutover-v1",
        "migration_id": state.migration_id,
        "status": "preparing",
        "workspace": str(workspace),
        "mirror_db": status["mirror_db"],
        "manifest_sha256": status["manifest_sha256"],
        "archive": str(archive),
        "prior_memory_slot": prior_slot,
        "prior_session_memory_hook": prior_session_hook,
        "prior_plugin_entry": prior_plugin_entry,
        "prior_tools_also_allow": prior_tools_also_allow,
        "relocated": [],
        "approved_candidates_merged": 0,
        "native_capability_report": capability_report,
        "created_at": utc_now(),
    }
    _private_json(cutover_path, cutover)
    try:
        # Quiesce the native writer before the final mirror and snapshot. The
        # gateway is restarted below on success and in the failure path.
        report(3, total_steps, "Pausing OpenClaw memory writes")
        _run([executable, "gateway", "stop"])
        report(4, total_steps, "Taking the final searchable memory snapshot")
        status = sync_mirror(state, workspace=workspace)
        if not status.get("synced") or int(status.get("record_count") or 0) < 1:
            raise ValueError("final OpenClaw memory mirror failed verification")
        promoted_candidates = _merge_approved_control_candidates(
            state, status["mirror_db"]
        )
        archive.mkdir(mode=0o700, exist_ok=False)
        native_snapshot = _snapshot_native_memory(workspace, archive)
        shadow_history = status.get("shadow_history")
        shadow_history = shadow_history if isinstance(shadow_history, dict) else {}
        if native_snapshot["snapshot_sha256"] != shadow_history.get(
            "latest_observed_sha256"
        ):
            raise ValueError(
                "switch-time snapshot does not match the final searchable mirror"
            )
        _private_json(
            control_dir / NATIVE_SNAPSHOT_MANIFEST_NAME,
            native_snapshot,
        )
        cutover.update(
            {
                "mirror_db": status["mirror_db"],
                "manifest_sha256": status["manifest_sha256"],
                "native_snapshot": native_snapshot,
                "native_snapshot_verified": True,
                "approved_candidates_merged": promoted_candidates,
            }
        )
        _private_json(cutover_path, cutover)

        if _tree_manifest(workspace, NATIVE_MEMORY_ROOTS) != native_snapshot["entries"]:
            raise ValueError(
                "OpenClaw native memory changed after the switch-time snapshot"
            )
        report(5, total_steps, "Freezing native supplemental memory")
        for relative in SUPPLEMENTAL_MEMORY_ROOTS:
            source = workspace / relative
            if not source.exists():
                continue
            cutover["relocated"].append(relative)
            _private_json(cutover_path, cutover)
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()

        report(6, total_steps, "Configuring AetnaMem as the memory provider")
        _run([executable, "hooks", "disable", "session-memory"], allow_missing=True)
        _set_json(executable, "plugins.slots.memory", "none")
        base = "plugins.entries.memory-aetnamem"
        _set_json(executable, f"{base}.config.controlPlane", {"enabled": False})
        _set_json(executable, f"{base}.config.takeoverActive", True)
        _set_json(executable, f"{base}.config.nativeWorkspace", str(workspace))
        _set_json(executable, f"{base}.config.dbPath", status["mirror_db"])
        _set_json(executable, f"{base}.config.subject", state.subject_id)
        _set_json(executable, f"{base}.hooks.allowConversationAccess", True)
        _set_json(
            executable,
            f"{base}.config.capture",
            {
                "enabled": True,
                "captureAssistant": True,
            },
        )
        _set_json(
            executable,
            f"{base}.config.recall",
            {
                "enabled": True,
                "maxRecords": 3,
                "maxChars": DEFAULT_RECALL_CHARS,
                "minScore": 0.3,
                "timeoutMs": 4000,
            },
        )
        _set_json(executable, f"{base}.enabled", True)
        existing_tools = (
            [str(value) for value in prior_tools_also_allow]
            if isinstance(prior_tools_also_allow, list)
            else []
        )
        _set_json(
            executable,
            "tools.alsoAllow",
            list(
                dict.fromkeys(
                    [*existing_tools, "memory_remember", "aetnamem_observe"]
                )
            ),
        )
        report(7, total_steps, "Restarting OpenClaw")
        _run([executable, "gateway", "restart"])
        gateway = _json_command(
            [executable, "gateway", "status", "--require-rpc", "--json"]
        )
        rpc = gateway.get("rpc") if isinstance(gateway, dict) else None
        if not isinstance(rpc, dict) or rpc.get("ok") is not True:
            raise ValueError("OpenClaw gateway RPC did not verify after cutover")
        plugin_runtime = _json_command(
            [
                executable,
                "plugins",
                "inspect",
                "memory-aetnamem",
                "--runtime",
                "--json",
            ]
        )
        plugin = (
            plugin_runtime.get("plugin") if isinstance(plugin_runtime, dict) else None
        )
        tool_names = (
            set(plugin.get("toolNames") or []) if isinstance(plugin, dict) else set()
        )
        required_tools = {
            "memory_search",
            "memory_get",
            "memory_remember",
            "aetnamem_observe",
        }
        typed_hooks = {
            str(row.get("name"))
            for row in plugin_runtime.get("typedHooks", [])
            if isinstance(row, dict)
        }
        required_hooks = {
            "before_model_resolve",
            "before_prompt_build",
            "agent_end",
            "before_message_write",
            "before_tool_call",
        }
        protected_workspace = _optional_json(
            [
                executable,
                "config",
                "get",
                f"{base}.config.nativeWorkspace",
                "--json",
            ]
        )
        if (
            not isinstance(plugin, dict)
            or plugin.get("status") != "loaded"
            or not required_tools.issubset(tool_names)
            or not required_hooks.issubset(typed_hooks)
            or protected_workspace != str(workspace)
        ):
            raise ValueError(
                "AetnaMem OpenClaw runtime did not verify the standard "
                "memory tools, capture/injection hooks, and native-path guard"
            )
        report(8, total_steps, "Verified memory tools, capture, and native write guard")
        cutover.update(
            {
                "status": "active",
                "activated_at": utc_now(),
                "native_memory_frozen": True,
                "native_snapshot_verified": True,
                "native_memory_slot": "none",
                "session_memory_hook": "disabled",
                "gateway_verified": True,
                "compatibility_tools": [
                    "memory_search",
                    "memory_get",
                    "memory_remember",
                    "aetnamem_observe",
                ],
                "compatibility_tools_verified": True,
                "capture_hooks_verified": True,
                "native_write_guard_verified": True,
            }
        )
        _private_json(cutover_path, cutover)
        return _cutover_public(cutover)
    except Exception:
        _restore_cutover(cutover, executable=executable)
        _run([executable, "gateway", "restart"], allow_missing=True)
        cutover["status"] = "rolled_back_after_failure"
        cutover["rolled_back_at"] = utc_now()
        _private_json(cutover_path, cutover)
        raise


def restore_takeover(
    state: ControlState,
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    report = progress or (lambda _step, _total, _label: None)
    total_steps = 4
    report(1, total_steps, "Checking the frozen OpenClaw snapshot")
    cutover_path = Path(state.control_dir) / CUTOVER_NAME
    cutover = _read_json(cutover_path)
    if not cutover:
        return {"restored": True, "takeover_present": False}
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH; native memory was not restored")
    report(2, total_steps, "Preserving any post-switch native files")
    _restore_cutover(cutover, executable=executable)
    report(3, total_steps, "Returning active-period memories to OpenClaw")
    active_export = _export_active_memories_to_native(
        cutover,
        subject_id=state.subject_id,
    )
    cutover["active_memory_export"] = active_export
    cutover["status"] = "rolled_back"
    cutover["rolled_back_at"] = utc_now()
    _private_json(cutover_path, cutover)
    report(4, total_steps, "OpenClaw native memory restored and verified")
    return {
        "restored": True,
        "takeover_present": True,
        "native_memory_restored": True,
        "manifest_sha256": cutover.get("manifest_sha256"),
        "active_memory_export": active_export,
        "post_switch_native_preserved": cutover.get("post_switch_native_preserved", []),
    }


def emergency_off_takeover(state: ControlState) -> dict[str, Any]:
    cutover = _read_json(Path(state.control_dir) / CUTOVER_NAME)
    if not cutover or cutover.get("status") != "active":
        return {"takeover_present": bool(cutover), "plugin_disabled": False}
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH; AetnaMem plugin was not disabled")
    _set_json(executable, "plugins.entries.memory-aetnamem.enabled", False)
    _run([executable, "gateway", "restart"])
    cutover["status"] = "emergency_off"
    cutover["emergency_off_at"] = utc_now()
    _private_json(Path(state.control_dir) / CUTOVER_NAME, cutover)
    return {
        "takeover_present": True,
        "plugin_disabled": True,
        "native_memory_frozen": True,
        "next": "Run `aetnamem control restore` to restore native OpenClaw memory.",
    }


def restart_and_verify_gateway() -> dict[str, Any]:
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH")
    _run([executable, "gateway", "restart"])
    gateway = _json_command(
        [executable, "gateway", "status", "--require-rpc", "--json"]
    )
    rpc = gateway.get("rpc") if isinstance(gateway, dict) else None
    if not isinstance(rpc, dict) or rpc.get("ok") is not True:
        raise ValueError("OpenClaw gateway RPC verification failed")
    return {"restarted": True, "verified": True}


def takeover_status(state: ControlState) -> dict[str, Any]:
    cutover = _read_json(Path(state.control_dir) / CUTOVER_NAME)
    return (
        _cutover_public(cutover)
        if cutover
        else {
            "status": "shadow",
            "active": False,
            "native_memory_frozen": False,
        }
    )


def inspect_native_memory_capabilities(
    executable: str | None = None,
) -> dict[str, Any]:
    """Find explicitly configured native features a takeover cannot preserve.

    Missing keys mean OpenClaw defaults. Those defaults are covered by the
    AetnaMem mirror, standard memory_search/memory_get aliases, continuous
    capture, and verified restore. Explicit extra corpora or native
    experimental pipelines must never disappear silently.
    """

    command = executable or shutil.which("openclaw")
    if command is None:
        raise ValueError("OpenClaw is not on PATH")
    checks = {
        "default_memory_search": "agents.defaults.memorySearch",
        "agent_overrides": "agents.list",
        "memory_config": "memory",
        "memory_core": "plugins.entries.memory-core",
        "memory_wiki": "plugins.entries.memory-wiki",
        "active_memory": "plugins.entries.active-memory",
    }
    configured = {
        name: _optional_json([command, "config", "get", key, "--json"])
        for name, key in checks.items()
    }
    reasons: list[str] = []

    def inspect_search(value: Any, label: str) -> None:
        if not isinstance(value, dict):
            return
        sources = value.get("sources")
        if isinstance(sources, list) and any(str(item) != "memory" for item in sources):
            reasons.append(f"{label} indexes non-memory sources: {sources}")
        if value.get("extraPaths"):
            reasons.append(f"{label} uses extraPaths")
        experimental = value.get("experimental")
        if isinstance(experimental, dict) and experimental.get("sessionMemory") is True:
            reasons.append(f"{label} indexes session transcripts")
        if value.get("backend") == "qmd":
            reasons.append(f"{label} uses the qmd backend")
        if value.get("multimodal"):
            reasons.append(f"{label} enables native multimodal indexing")

    inspect_search(configured["default_memory_search"], "agents.defaults.memorySearch")
    agents = configured["agent_overrides"]
    if isinstance(agents, list):
        for agent in agents:
            if isinstance(agent, dict):
                inspect_search(
                    agent.get("memorySearch"),
                    f"agent {agent.get('id') or '<unknown>'} memorySearch",
                )
    memory_config = configured["memory_config"]
    if isinstance(memory_config, dict):
        if memory_config.get("backend") == "qmd":
            reasons.append("memory.backend is qmd")
        if memory_config.get("multimodal"):
            reasons.append("memory.multimodal is configured")
    core = configured["memory_core"]
    if isinstance(core, dict):
        core_config = core.get("config")
        if isinstance(core_config, dict) and core_config.get("dreaming"):
            reasons.append("memory-core dreaming is configured")
    for name, label in (
        ("memory_wiki", "memory-wiki corpus"),
        ("active_memory", "active-memory plugin"),
    ):
        value = configured[name]
        if isinstance(value, dict) and value.get("enabled") is not False:
            reasons.append(f"{label} is enabled")

    return {
        "format": "aetnamem-openclaw-capability-check-v1",
        "safe_to_switch": not reasons,
        "blocking_reasons": reasons,
        "preserved": [
            "MEMORY.md and memory/*.md imported with provenance",
            "standard memory_search tool",
            "standard memory_get tool",
            "model-interpreted memory_remember tool",
            "pre-switch native files and configuration restore",
        ],
        "configured": configured,
    }


def _restore_cutover(cutover: dict[str, Any], *, executable: str) -> None:
    workspace = Path(str(cutover["workspace"]))
    archive = Path(str(cutover["archive"]))
    preservation_root: Path | None = None
    preserved: list[dict[str, Any]] = list(
        cutover.get("post_switch_native_preserved") or []
    )
    for relative in reversed(list(cutover.get("relocated") or [])):
        source = archive / relative
        destination = workspace / relative
        if not source.exists():
            continue
        if destination.exists():
            expected = _tree_manifest(archive, (relative,))
            actual = _tree_manifest(workspace, (relative,))
            if actual != expected:
                if preservation_root is None:
                    preservation_root = _new_preservation_root(archive.parent)
                preserved_path = preservation_root / relative
                preserved_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.move(str(destination), str(preserved_path))
                preserved.append(
                    {
                        "relative_path": relative,
                        "preserved_path": str(preserved_path),
                        "entries": actual,
                    }
                )
            else:
                continue
        _copy_native_path(source, destination)
    if preservation_root is not None:
        cutover["post_switch_native_preservation_root"] = str(preservation_root)
        cutover["post_switch_native_preserved"] = preserved
    snapshot = cutover.get("native_snapshot")
    if isinstance(snapshot, dict):
        restored = _tree_manifest(workspace, SUPPLEMENTAL_MEMORY_ROOTS)
        expected = _entries_for_roots(
            list(snapshot.get("entries") or []),
            SUPPLEMENTAL_MEMORY_ROOTS,
        )
        if restored != expected:
            raise ValueError("restored OpenClaw native memory failed hash verification")
    prior_slot = cutover.get("prior_memory_slot")
    if prior_slot is None:
        _run(
            [executable, "config", "unset", "plugins.slots.memory"],
            allow_missing=True,
        )
    else:
        _set_json(executable, "plugins.slots.memory", prior_slot)
    hook = cutover.get("prior_session_memory_hook")
    if isinstance(hook, dict) and hook.get("enabled") is True:
        _run([executable, "hooks", "enable", "session-memory"])
    elif isinstance(hook, dict) and hook.get("enabled") is False:
        _run([executable, "hooks", "disable", "session-memory"])
    prior_plugin = cutover.get("prior_plugin_entry")
    if isinstance(prior_plugin, dict):
        _set_json(executable, "plugins.entries.memory-aetnamem", prior_plugin)
    prior_tools = cutover.get("prior_tools_also_allow")
    if isinstance(prior_tools, list):
        _set_json(executable, "tools.alsoAllow", prior_tools)
    elif "prior_tools_also_allow" in cutover:
        _run(
            [executable, "config", "unset", "tools.alsoAllow"],
            allow_missing=True,
        )


def _new_preservation_root(control_dir: Path) -> Path:
    base = control_dir / "openclaw-post-switch-preserved"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = control_dir / f"{base.name}-{suffix}"
    candidate.mkdir(mode=0o700)
    return candidate


def _new_cutover_archive(control_dir: Path) -> Path:
    base = control_dir / "openclaw-native-frozen"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = control_dir / f"{base.name}-{suffix}"
    return candidate


def _archive_completed_cutover(
    control_dir: Path,
    cutover: dict[str, Any],
) -> None:
    """Preserve terminal cutover evidence before beginning another attempt."""
    history = control_dir / "openclaw-cutover-history"
    digest = sha256_hex(canonical_json(cutover))
    target = history / f"{cutover.get('status', 'completed')}-{digest[:16]}.json"
    if not target.exists():
        _private_json(target, cutover)


def _export_active_memories_to_native(
    cutover: dict[str, Any],
    *,
    subject_id: str,
) -> dict[str, Any]:
    """Return non-native memories to OpenClaw after its snapshot verifies.

    The mirror starts as an exact import whose source sessions all use the
    ``openclaw-native:`` prefix. Approved shadow candidates and authenticated
    user memories captured after takeover do not. Those records must remain
    available when OpenClaw becomes authoritative again.
    """

    previous = cutover.get("active_memory_export")
    if isinstance(previous, dict):
        previous_path = Path(str(previous.get("path") or ""))
        expected_sha256 = str(previous.get("sha256") or "")
        if (
            previous_path.is_file()
            and expected_sha256
            and sha256_hex(previous_path.read_bytes()) == expected_sha256
        ):
            return previous

    mirror_db = Path(str(cutover["mirror_db"]))
    workspace = Path(str(cutover["workspace"]))
    memory = Memory(mirror_db)
    try:
        records = [
            row
            for row in memory.list(subject_id)
            if row.get("source_type") == "user_message"
            and not str(row.get("source_session_id") or "").startswith(
                "openclaw-native:"
            )
        ]
        records.sort(key=lambda row: (str(row.get("created_at")), str(row["id"])))
        if not records:
            return {
                "format": "aetnamem-openclaw-active-export-v1",
                "record_count": 0,
                "record_ids": [],
                "path": None,
                "sha256": None,
            }

        lines = [
            "# Memories captured while AetnaMem was active",
            "",
            ("These memories were returned by AetnaMem during verified " "restore."),
            "",
        ]
        for row in records:
            content = " ".join(str(row["content"]).split())
            lines.append(f"- {content}")
        data = ("\n".join(lines).rstrip() + "\n").encode("utf-8")
        digest = sha256_hex(data)
        export_dir = workspace / "memory"
        export_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        export_path = export_dir / f"aetnamem-active-{digest[:12]}.md"
        if export_path.exists():
            if export_path.is_symlink() or export_path.read_bytes() != data:
                raise ValueError(
                    "cannot export active-period memories because the "
                    f"deterministic path is occupied: {export_path}"
                )
        else:
            temporary = export_path.with_name(f".{export_path.name}.tmp")
            temporary.write_bytes(data)
            os.chmod(temporary, 0o600)
            os.replace(temporary, export_path)
        if sha256_hex(export_path.read_bytes()) != digest:
            raise ValueError("active-period memory export failed hash verification")

        receipt = {
            "format": "aetnamem-openclaw-active-export-v1",
            "record_count": len(records),
            "record_ids": [str(row["id"]) for row in records],
            "path": str(export_path),
            "sha256": digest,
        }
        with memory.store.transaction(immediate=True):
            memory.store.append_audit_event(
                subject_id=subject_id,
                event_type="host.memory_exported_on_restore",
                actor="control-plane-restore",
                payload={
                    "migration_id": cutover.get("migration_id"),
                    "record_ids": receipt["record_ids"],
                    "export_path_sha256": sha256_hex(str(export_path)),
                    "export_sha256": digest,
                },
            )
        return receipt
    finally:
        memory.close()


def _source_row(source: NativeSource) -> dict[str, Any]:
    data = source.path.read_bytes()
    return {
        "relative_path": source.relative_path,
        "path": str(source.path),
        "plane": source.plane,
        "pinned": source.pinned,
        "bytes": len(data),
        "sha256": sha256_hex(data),
        "mtime_ns": source.path.stat().st_mtime_ns,
    }


def _merge_approved_control_candidates(state: ControlState, mirror_db: str | Path) -> int:
    store = ControlStore(Path(state.control_dir) / "evidence.db")
    try:
        approved = store.list_candidates(state.migration_id, statuses=("approved",))
    finally:
        store.close()
    if not approved:
        return 0
    memory = Memory(mirror_db)
    created = 0
    try:
        for row in approved:
            result = memory.remember(
                state.subject_id,
                fact=str(row["content"]),
                force=True,
                session_id=str(row.get("source_session_id") or state.migration_id),
                source_type="user_message",
                actor="control-plane-approved-import",
                raw={
                    "format": "aetnamem-control-plane-approved-source-v1",
                    "migration_id": state.migration_id,
                    "candidate_id": row["id"],
                    "candidate_content_sha256": row["content_sha256"],
                    "reviewed_at": row.get("reviewed_at"),
                },
            )
            created += len(result.get("records") or [])
        memory.store.append_audit_event(
            subject_id=state.subject_id,
            event_type="migration.approved_candidates_imported",
            actor="control-plane-activator",
            payload={
                "migration_id": state.migration_id,
                "candidate_ids": [str(row["id"]) for row in approved],
                "created_records": created,
            },
        )
        memory.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        memory.close()
    return created


def _markdown_chunks(text: str, *, max_chars: int = 1200) -> Iterable[dict[str, Any]]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    start = 1
    for index, line in enumerate(lines, start=1):
        candidate = "\n".join([*current, line]).strip()
        boundary = not line.strip() and current
        too_large = len(candidate) > max_chars and current
        if too_large or boundary:
            value = "\n".join(current).strip()
            if value:
                chunks.append(
                    {"text": value, "line_start": start, "line_end": index - 1}
                )
            current = []
            start = index + 1 if boundary else index
            if boundary:
                continue
        current.append(line)
    value = "\n".join(current).strip()
    if value:
        chunks.append({"text": value, "line_start": start, "line_end": len(lines)})
    return chunks


def _mirror_status_from_manifest(
    manifest: dict[str, Any], mirror_path: Path
) -> dict[str, Any]:
    native_chars = int(manifest.get("native_memory_chars") or 0)
    max_chars = DEFAULT_RECALL_CHARS
    record_count = int(manifest.get("record_count") or 0)
    audit_verified = False
    audit_error = None
    if mirror_path.is_file():
        memory = Memory(mirror_path)
        try:
            subject_id = str(manifest.get("subject_id") or "local-user")
            record_count = len(memory.list(subject_id, include_inactive=True))
            audit_verified = bool(memory.verify(subject_id).get("valid"))
        except Exception as exc:
            audit_error = str(exc)
        finally:
            memory.close()
    return {
        **manifest,
        "status": "synced" if mirror_path.is_file() else "missing",
        "synced": mirror_path.is_file(),
        "mirror_db": str(mirror_path),
        "record_count": record_count,
        "audit_verified": audit_verified,
        "audit_error": audit_error,
        "context_budget_chars": max_chars,
        "native_memory_estimated_tokens": (native_chars + 3) // 4,
        "aetnamem_context_budget_estimated_tokens": (max_chars + 3) // 4,
        "token_projection": (
            "potential_reduction"
            if native_chars > max_chars
            else "no_cost_reduction_expected"
        ),
    }


def _cutover_public(value: dict[str, Any]) -> dict[str, Any]:
    status = str(value.get("status") or "unknown")
    terminal = {"rolled_back", "rolled_back_after_failure"}
    public = {
        key: value.get(key)
        for key in (
            "format",
            "status",
            "migration_id",
            "workspace",
            "mirror_db",
            "manifest_sha256",
            "activated_at",
            "rolled_back_at",
            "native_memory_frozen",
            "native_snapshot_verified",
            "native_memory_slot",
            "session_memory_hook",
            "gateway_verified",
            "compatibility_tools",
            "compatibility_tools_verified",
            "capture_hooks_verified",
            "native_write_guard_verified",
            "native_capability_report",
        )
        if key in value
    } | {
        "active": status == "active",
        "requires_restore": status not in terminal | {"active"},
    }
    if public["requires_restore"]:
        public["recovery_message"] = (
            "A previous OpenClaw switch did not reach a verified terminal "
            "state. Restore OpenClaw before trying activation again."
        )
    snapshot = value.get("native_snapshot")
    if isinstance(snapshot, dict):
        public["native_snapshot"] = {
            key: snapshot.get(key)
            for key in (
                "snapshot_sha256",
                "entry_count",
                "file_count",
                "total_bytes",
                "verified_at",
            )
        }
    return public


def _ensure_native_baseline(control_dir: Path, workspace: Path) -> dict[str, Any]:
    archive = control_dir / NATIVE_BASELINE_NAME
    manifest_path = control_dir / NATIVE_BASELINE_MANIFEST_NAME
    existing = _read_json(manifest_path)
    if existing:
        copied = _tree_manifest(archive, NATIVE_MEMORY_ROOTS)
        if copied != existing.get("entries"):
            raise ValueError(
                "the initial OpenClaw native-memory baseline no longer verifies"
            )
        return existing
    if archive.exists():
        copied = _tree_manifest(archive, NATIVE_MEMORY_ROOTS)
        current = _tree_manifest(workspace, NATIVE_MEMORY_ROOTS)
        if copied != current:
            raise ValueError(
                "an incomplete pre-shadow baseline exists and no longer "
                "matches OpenClaw; remove the failed migration before retrying"
            )
        recovered: dict[str, Any] = {
            "format": "aetnamem-openclaw-native-snapshot-v1",
            "workspace": str(workspace),
            "archive": str(archive),
            "entries": copied,
            "entry_count": len(copied),
            "file_count": sum(1 for row in copied if row["type"] == "file"),
            "total_bytes": sum(
                int(row.get("bytes") or 0) for row in copied if row["type"] == "file"
            ),
            "verified_at": utc_now(),
            "purpose": "pre-shadow-baseline",
            "snapshot_sha256": _native_snapshot_digest(copied),
        }
        _private_json(manifest_path, recovered)
        return recovered

    building = control_dir / f".{NATIVE_BASELINE_NAME}.building"
    shutil.rmtree(building, ignore_errors=True)
    building.mkdir(mode=0o700)
    try:
        baseline = _snapshot_native_memory(workspace, building)
        baseline["purpose"] = "pre-shadow-baseline"
        os.replace(building, archive)
        baseline["archive"] = str(archive)
        _private_json(manifest_path, baseline)
        return baseline
    except Exception:
        shutil.rmtree(building, ignore_errors=True)
        raise


def _record_shadow_version(
    control_dir: Path,
    workspace: Path,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    entries = _tree_manifest(workspace, NATIVE_MEMORY_ROOTS)
    digest = _native_snapshot_digest(entries)
    history_root = control_dir / SHADOW_HISTORY_NAME
    history_root.mkdir(mode=0o700, exist_ok=True)
    baseline_digest = str(baseline.get("snapshot_sha256") or "")
    if digest != baseline_digest:
        target = history_root / digest
        if not target.exists():
            building = history_root / f".{digest}.building"
            shutil.rmtree(building, ignore_errors=True)
            building.mkdir(mode=0o700)
            try:
                observed = _snapshot_native_memory(workspace, building)
                if observed["snapshot_sha256"] != digest:
                    raise ValueError(
                        "OpenClaw native memory changed during shadow synchronization"
                    )
                observed["purpose"] = "shadow-observed-version"
                _private_json(building / "snapshot.json", observed)
                os.replace(building, target)
            except Exception:
                shutil.rmtree(building, ignore_errors=True)
                raise
    versions = sorted(
        path.name
        for path in history_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    return {
        "initial_baseline_sha256": baseline_digest,
        "latest_observed_sha256": digest,
        "observed_change_versions": len(versions),
        "version_sha256s": versions,
        "snapshot_root": str(
            Path(str(baseline["archive"]))
            if digest == baseline_digest
            else history_root / digest
        ),
    }


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in (
            "snapshot_sha256",
            "entry_count",
            "file_count",
            "total_bytes",
            "verified_at",
            "purpose",
        )
    }


def _snapshot_native_memory(workspace: Path, archive: Path) -> dict[str, Any]:
    roots = NATIVE_MEMORY_ROOTS
    before = _tree_manifest(workspace, roots)
    for relative in roots:
        source = workspace / relative
        if source.exists():
            _copy_native_path(source, archive / relative)
    after = _tree_manifest(workspace, roots)
    copied = _tree_manifest(archive, roots)
    if before != after:
        raise ValueError(
            "OpenClaw native memory changed while it was being snapshotted; "
            "activation was not attempted"
        )
    if before != copied:
        raise ValueError(
            "OpenClaw native-memory snapshot failed byte-for-byte verification"
        )
    snapshot: dict[str, Any] = {
        "format": "aetnamem-openclaw-native-snapshot-v1",
        "workspace": str(workspace),
        "archive": str(archive),
        "entries": copied,
        "entry_count": len(copied),
        "file_count": sum(1 for row in copied if row["type"] == "file"),
        "total_bytes": sum(
            int(row.get("bytes") or 0) for row in copied if row["type"] == "file"
        ),
        "verified_at": utc_now(),
    }
    snapshot["snapshot_sha256"] = _native_snapshot_digest(copied)
    return snapshot


def _native_snapshot_digest(entries: list[dict[str, Any]]) -> str:
    return sha256_hex(
        canonical_json(
            {
                "format": "aetnamem-openclaw-native-snapshot-v1",
                "entries": entries,
            }
        )
    )


def _copy_native_path(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValueError(
            f"cannot guarantee a complete native-memory snapshot through symlink: {source}"
        )
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(
                "cannot guarantee a complete native-memory snapshot through "
                f"symlink: {item}"
            )
        target = destination / item.relative_to(source)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        else:
            raise ValueError(f"unsupported native-memory filesystem entry: {item}")


def _tree_manifest(base: Path, roots: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in roots:
        root = base / relative
        if not root.exists():
            continue
        if root.is_symlink():
            raise ValueError(
                f"cannot verify a native-memory snapshot through symlink: {root}"
            )
        candidates = [root]
        if root.is_dir():
            candidates.extend(sorted(root.rglob("*")))
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(
                    "cannot verify a native-memory snapshot through symlink: "
                    f"{candidate}"
                )
            path = candidate.relative_to(base).as_posix()
            if candidate.is_dir():
                rows.append({"path": path, "type": "directory"})
            elif candidate.is_file():
                data = candidate.read_bytes()
                rows.append(
                    {
                        "path": path,
                        "type": "file",
                        "bytes": len(data),
                        "sha256": sha256_hex(data),
                    }
                )
            else:
                raise ValueError(
                    f"unsupported native-memory filesystem entry: {candidate}"
                )
    return sorted(rows, key=lambda row: (str(row["path"]), str(row["type"])))


def _entries_for_roots(
    entries: list[dict[str, Any]],
    roots: Iterable[str],
) -> list[dict[str, Any]]:
    prefixes = tuple(str(root).rstrip("/") for root in roots)
    return [
        row
        for row in entries
        if any(
            str(row.get("path") or "") == prefix
            or str(row.get("path") or "").startswith(f"{prefix}/")
            for prefix in prefixes
        )
    ]


def _private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _remove_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _remove_sqlite_sidecars(path: Path) -> None:
    for candidate in (Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _json_command(arguments: list[str]) -> dict[str, Any]:
    result = _run(arguments)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"command returned invalid JSON: {' '.join(arguments)}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"command returned unexpected JSON: {' '.join(arguments)}")
    return value


def _optional_json(arguments: list[str]) -> Any | None:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _set_json(executable: str, key: str, value: Any) -> None:
    _run(
        [
            executable,
            "config",
            "set",
            key,
            json.dumps(value, separators=(",", ":")),
            "--strict-json",
        ]
    )


def _run(
    arguments: list[str], *, allow_missing: bool = False
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0 and not allow_missing:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise ValueError(f"{' '.join(arguments[:3])} failed: {detail}")
    return result
