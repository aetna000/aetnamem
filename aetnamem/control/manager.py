from __future__ import annotations

from dataclasses import replace
import getpass
from pathlib import Path
from typing import Any
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.core.storage import HouseholdPolicy
from aetnamem.extract.rules import extract_facts
from aetnamem.retrieve.rank import rank_records
from aetnamem.store.sqlite import utc_now
from aetnamem.control.models import ControlMode, ControlState
from aetnamem.control.state import load_effective_state, load_state, state_lock, write_state
from aetnamem.control.store import ControlStore


DEFAULT_CONTROL_ROOT = Path.home() / ".aetnamem" / "migrations"
DEFAULT_STATE_PATH = Path.home() / ".aetnamem" / "control-plane.json"
DEFAULT_SUBJECT = "local-user"

_ALLOWED_TRANSITIONS: dict[ControlMode, frozenset[ControlMode]] = {
    ControlMode.OFF: frozenset({ControlMode.SHADOW, ControlMode.ACTIVE}),
    ControlMode.SHADOW: frozenset({ControlMode.ACTIVE, ControlMode.OFF}),
    ControlMode.ACTIVE: frozenset({ControlMode.OFF}),
}


class ControlPlaneManager:
    """Host-neutral memory control plane.

    The host integration reads one small, digest-bound state file. Candidate
    memories and migration evidence live in a separate SQLite database and cannot
    enter the ordinary AetnaMem recall path until a later, explicit import.
    """

    def __init__(self, state_path: str | Path = DEFAULT_STATE_PATH) -> None:
        self.state_path = Path(state_path).expanduser().resolve(strict=False)

    @classmethod
    def start(
        cls,
        *,
        host: str,
        state_path: str | Path = DEFAULT_STATE_PATH,
        control_root: str | Path = DEFAULT_CONTROL_ROOT,
        subject_id: str = DEFAULT_SUBJECT,
    ) -> "ControlPlaneManager":
        if host != "openclaw":
            raise ValueError("the verified host adapter in this release is openclaw")
        manager = cls(state_path)
        with state_lock(manager.state_path):
            if manager.state_path.exists():
                current = load_state(manager.state_path)
                if current.mode is not ControlMode.OFF:
                    raise ValueError(
                        f"migration {current.migration_id} is already {current.mode.value}; "
                        "turn it off before starting another"
                    )
            migration_id = f"control_{uuid.uuid4().hex}"
            control_dir = (
                Path(control_root).expanduser().resolve(strict=False) / migration_id
            )
            control_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
            now = utc_now()
            state = ControlState(
                migration_id=migration_id,
                host=host,
                subject_id=subject_id or DEFAULT_SUBJECT,
                control_dir=str(control_dir),
                mode=ControlMode.SHADOW,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            store = ControlStore(
                control_dir / "evidence.db",
                policy=HouseholdPolicy.load(control_dir / "openclaw-mirror.db"),
            )
            try:
                store.create_migration(migration_id, host, state.subject_id)
                store.append_transition(
                    migration_id,
                    revision=state.revision,
                    old_mode=ControlMode.OFF.value,
                    new_mode=ControlMode.SHADOW.value,
                    actor=_local_actor(),
                )
            finally:
                store.close()
            write_state(manager.state_path, state)
        return manager

    def effective_state(self) -> tuple[ControlState, str | None]:
        return load_effective_state(self.state_path)

    def state(self) -> ControlState:
        return load_state(self.state_path)

    def status(self) -> dict[str, Any]:
        state, warning = self.effective_state()
        result = state.public_status(warning=warning)
        if warning or state.migration_id == "unavailable":
            result["evidence"] = None
            result["readiness"] = {
                "ready_for_active": False,
                "reasons": ["state is missing or invalid; integration is fail-closed"],
            }
            return result
        store = self._store(state)
        try:
            evidence = store.summary(state.migration_id)
            latest_restore_drill = store.latest_evidence(
                state.migration_id, kind="restore_drill"
            )
            latest_verification = store.latest_evidence(
                state.migration_id, kind="verification"
            )
        finally:
            store.close()
        mirror: dict[str, Any] | None = None
        takeover: dict[str, Any] | None = None
        if state.host == "openclaw":
            from aetnamem.control.openclaw_native import (
                mirror_status,
                takeover_status,
            )

            mirror = mirror_status(state)
            takeover = takeover_status(state)
        result["evidence"] = evidence
        result["restore_drill"] = (
            latest_restore_drill["body"] if latest_restore_drill else None
        )
        result["verification"] = (
            latest_verification["body"] if latest_verification else None
        )
        result["mirror"] = mirror
        result["takeover"] = takeover
        result["readiness"] = self._readiness(state, evidence, mirror=mirror)
        return result

    def capture(
        self,
        message: str,
        *,
        session_id: str | None = None,
        authenticated_user: bool,
    ) -> dict[str, Any]:
        state, warning = self.effective_state()
        if warning or not state.mode.captures:
            return {"captured": 0, "candidate_ids": [], "reason": "migration is off"}
        if not authenticated_user:
            return {
                "captured": 0,
                "candidate_ids": [],
                "reason": "only authenticated user messages are eligible",
            }
        facts = extract_facts(message, source_type="user_message")
        store = self._store(state)
        created: list[str] = []
        duplicates: list[str] = []
        try:
            for fact in facts:
                row, duplicate = store.insert_candidate(
                    state.migration_id,
                    content=fact.content,
                    fact_key=fact.fact_key,
                    confidence=fact.confidence,
                    source_type=fact.source_type,
                    trust_tier=fact.trust_tier,
                    source_message_sha256=sha256_hex(message),
                    source_session_id=session_id,
                )
                (duplicates if duplicate else created).append(str(row["id"]))
        finally:
            store.close()
        return {
            "captured": len(created),
            "candidate_ids": created,
            "duplicate_ids": duplicates,
            "raw_message_stored": False,
        }

    def candidates(self, *, include_reviewed: bool = False) -> list[dict[str, Any]]:
        state = self.state()
        store = self._store(state)
        try:
            statuses = None if include_reviewed else ("candidate",)
            return store.list_candidates(state.migration_id, statuses=statuses)
        finally:
            store.close()

    def review(self, candidate_ids: list[str], *, approve: bool) -> list[dict[str, Any]]:
        state = self.state()
        store = self._store(state)
        try:
            return store.review_candidates(
                state.migration_id, candidate_ids, approve=approve
            )
        finally:
            store.close()

    def prepare(
        self,
        query: str,
        *,
        session_id: str | None = None,
        host_run_id: str | None = None,
        limit: int = 3,
        max_chars: int = 1200,
        min_score: float = 0.3,
    ) -> dict[str, Any]:
        state, warning = self.effective_state()
        if warning or not state.mode.captures:
            return self._no_context(state, warning or "migration is off")
        store = self._store(state)
        try:
            approved = store.list_candidates(
                state.migration_id, statuses=("approved",)
            )
            ranked = rank_records(query, approved)
            candidate_chosen = [
                item
                for item in ranked
                if item.text_score > 0 and item.score >= min_score
            ][: max(0, limit)]
            mirror_records: list[dict[str, Any]] = []
            if state.host == "openclaw":
                from aetnamem.control.openclaw_native import search_mirror

                try:
                    mirror_records = list(
                        search_mirror(state, query, limit=limit).get("records") or []
                    )
                except ValueError:
                    mirror_records = []
            lines: list[str] = []
            candidate_ids: list[str] = []
            candidate_hashes: list[str] = []
            used_chars = 0
            chosen_rows = [
                (
                    str(item.record["id"]),
                    str(item.record["content"]),
                    str(item.record["content_sha256"]),
                )
                for item in candidate_chosen
            ]
            chosen_rows.extend(
                (
                    str(record["id"]),
                    str(record.get("content") or ""),
                    sha256_hex(str(record.get("content") or "")),
                )
                for record in mirror_records
            )
            seen: set[str] = set()
            for record_id, value, content_sha256 in chosen_rows:
                content = value.strip()
                normalized = content.casefold()
                if not content or normalized in seen:
                    continue
                seen.add(normalized)
                line = f"- {content}"
                if used_chars + len(line) + 1 > max_chars:
                    break
                lines.append(line)
                candidate_ids.append(record_id)
                candidate_hashes.append(content_sha256)
                used_chars += len(line) + 1
            context = (
                "<aetnamem_control_plane>\n"
                + "\n".join(lines)
                + "\n</aetnamem_control_plane>"
                if lines
                else ""
            )
            turn = store.insert_turn(
                state.migration_id,
                query_sha256=sha256_hex(query),
                session_id=session_id,
                host_run_id=host_run_id,
            )
            manifest = {
                "format": "aetnamem-control-context-v1",
                "migration_id": state.migration_id,
                "state_revision": state.revision,
                "mode": state.mode.value,
                "query_sha256": sha256_hex(query),
                "candidate_ids": candidate_ids,
                "candidate_content_sha256": candidate_hashes,
                "context_sha256": sha256_hex(context),
            }
            preview = store.insert_preview(
                state.migration_id,
                str(turn["id"]),
                candidate_ids=candidate_ids,
                context_text=context,
                manifest_sha256=sha256_hex(canonical_json(manifest)),
            )
            inject = bool(context) and state.mode.influences_agent
            reason: str | None = None
            exposure = None
            if inject:
                exposure = store.insert_exposure(
                    state.migration_id,
                    turn_id=str(turn["id"]),
                    preview_id=str(preview["id"]),
                    session_id=session_id,
                    mode=state.mode.value,
                )
            return {
                "mode": state.mode.value,
                "preview_id": preview["id"],
                "manifest_sha256": preview["manifest_sha256"],
                "candidate_ids": candidate_ids,
                "context": context if inject else "",
                "preview_context": context,
                "inject": inject,
                "exposure_id": exposure["id"] if exposure else None,
                "reason": reason,
            }
        finally:
            store.close()

    def confirm_exposure(self, exposure_id: str) -> bool:
        state = self.state()
        store = self._store(state)
        try:
            return store.mark_exposure_shown(state.migration_id, exposure_id)
        finally:
            store.close()

    def record_blackbox_event(
        self,
        *,
        event_type: str,
        run_id: str,
        session_id: str | None = None,
        tool_call_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one content-minimizing host observation to the flight chain."""

        from aetnamem.control.blackbox import EVIDENCE_KIND, normalize_event

        state, warning = self.effective_state()
        if warning or state.migration_id == "unavailable":
            raise ValueError("blackbox recording requires a valid control state")
        body = normalize_event(
            migration_id=state.migration_id,
            host=state.host,
            event_type=event_type,
            run_id=run_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            payload=payload,
        )
        store = self._store(state)
        try:
            entry = store.append_evidence(
                state.migration_id,
                kind=EVIDENCE_KIND,
                body=body,
            )
        finally:
            store.close()
        return {
            "recorded": True,
            "event_id": entry["id"],
            "sequence": entry["sequence"],
            "entry_sha256": entry["entry_sha256"],
        }

    def blackbox_events(self, *, run_id: str | None = None) -> list[dict[str, Any]]:
        from aetnamem.control.blackbox import EVIDENCE_KIND

        state = self.state()
        store = self._store(state)
        try:
            entries = store.list_evidence(state.migration_id, kind=EVIDENCE_KIND)
        finally:
            store.close()
        if run_id is None:
            return entries
        return [
            entry
            for entry in entries
            if str((entry.get("body") or {}).get("run_id") or "") == run_id
        ]

    def blackbox_runs(self, *, limit: int = 50) -> dict[str, Any]:
        from aetnamem.control.blackbox import EVIDENCE_KIND, flight_runs

        state = self.state()
        store = self._store(state)
        try:
            entries = store.list_evidence(state.migration_id, kind=EVIDENCE_KIND)
            chain = store.verify_evidence_chain(
                state.migration_id, kind=EVIDENCE_KIND
            )
        finally:
            store.close()
        runs = flight_runs(entries)
        return {
            "format": "aetnamem-agent-blackbox-index-v1",
            "enabled": True,
            "host": state.host,
            "migration_id": state.migration_id,
            "raw_content_stored": False,
            "chain": chain,
            "total_runs": len(runs),
            "total_events": len(entries),
            "runs": runs[: max(0, min(int(limit), 500))],
        }

    def verify_blackbox_flight(self, run_id: str) -> dict[str, Any]:
        from aetnamem.control.blackbox import EVIDENCE_KIND, verify_flight

        state = self.state()
        store = self._store(state)
        try:
            entries = store.list_evidence(state.migration_id, kind=EVIDENCE_KIND)
            chain = store.verify_evidence_chain(
                state.migration_id, kind=EVIDENCE_KIND
            )
        finally:
            store.close()
        return verify_flight(run_id=run_id, entries=entries, chain=chain)

    def transition(
        self,
        mode: ControlMode | str,
        *,
        actor: str | None = None,
    ) -> ControlState:
        target = mode if isinstance(mode, ControlMode) else ControlMode(mode)
        with state_lock(self.state_path):
            state = load_state(self.state_path)
            if target is state.mode:
                return state
            if target not in _ALLOWED_TRANSITIONS[state.mode]:
                raise ValueError(
                    f"cannot move directly from {state.mode.value} to {target.value}"
                )
            evidence_store = self._store(state)
            try:
                mirror = None
                if state.host == "openclaw":
                    from aetnamem.control.openclaw_native import mirror_status

                    mirror = mirror_status(state)
                readiness = self._readiness(
                    state,
                    evidence_store.summary(state.migration_id),
                    mirror=mirror,
                )
                if target is ControlMode.ACTIVE and not readiness["ready_for_active"]:
                    raise ValueError("; ".join(readiness["reasons"]))
                now = utc_now()
                updated = replace(
                    state,
                    mode=target,
                    revision=state.revision + 1,
                    updated_at=now,
                    state_sha256="",
                )
                evidence_store.append_transition(
                    state.migration_id,
                    revision=updated.revision,
                    old_mode=state.mode.value,
                    new_mode=target.value,
                    actor=actor or _local_actor(),
                )
                return write_state(self.state_path, updated)
            finally:
                evidence_store.close()

    def _readiness(
        self,
        state: ControlState,
        evidence: dict[str, Any],
        *,
        mirror: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        counts = evidence["candidates"]
        approved = int(counts.get("approved", 0))
        chain_valid = bool(evidence["transition_chain"]["valid"])
        mirror_ready = bool(
            mirror
            and mirror.get("synced")
            and mirror.get("audit_verified")
        )
        reasons: list[str] = []
        if not chain_valid:
            reasons.append("migration transition evidence did not verify")
        if approved < 1 and not mirror_ready:
            reasons.append("mirror native memory or approve at least one candidate")
        ready_for_active = chain_valid and (approved > 0 or mirror_ready)
        return {
            "ready_for_active": ready_for_active,
            "mirror_ready": mirror_ready,
            "reasons": reasons,
        }

    def _store(self, state: ControlState) -> ControlStore:
        control_dir = Path(state.control_dir)
        return ControlStore(
            control_dir / "evidence.db",
            policy=HouseholdPolicy.load(control_dir / "openclaw-mirror.db"),
        )

    @staticmethod
    def _no_context(state: ControlState, reason: str) -> dict[str, Any]:
        return {
            "mode": ControlMode.OFF.value
            if state.migration_id == "unavailable"
            else state.mode.value,
            "preview_id": None,
            "manifest_sha256": None,
            "candidate_ids": [],
            "context": "",
            "preview_context": "",
            "inject": False,
            "exposure_id": None,
            "reason": reason,
        }


def _local_actor() -> str:
    try:
        return f"local-user:{getpass.getuser()}"
    except Exception:  # pragma: no cover - defensive platform fallback
        return "local-user"
