from __future__ import annotations

from dataclasses import replace
import getpass
from pathlib import Path
from typing import Any
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.extract.rules import extract_facts
from aetnamem.retrieve.rank import rank_records
from aetnamem.store.sqlite import utc_now
from aetnamem.trial.models import TrialMode, TrialState
from aetnamem.trial.state import load_effective_state, load_state, state_lock, write_state
from aetnamem.trial.store import TrialStore


DEFAULT_TRIAL_ROOT = Path.home() / ".aetnamem" / "trials"
DEFAULT_STATE_PATH = Path.home() / ".aetnamem" / "safe-switch.json"
DEFAULT_SUBJECT = "local-user"

_ALLOWED_TRANSITIONS: dict[TrialMode, frozenset[TrialMode]] = {
    TrialMode.OFF: frozenset({TrialMode.CAPTURE}),
    TrialMode.CAPTURE: frozenset({TrialMode.PREVIEW, TrialMode.OFF}),
    TrialMode.PREVIEW: frozenset({TrialMode.CANARY, TrialMode.OFF}),
    TrialMode.CANARY: frozenset(
        {TrialMode.PREVIEW, TrialMode.ACTIVE, TrialMode.OFF}
    ),
    TrialMode.ACTIVE: frozenset({TrialMode.PREVIEW, TrialMode.OFF}),
}


class TrialManager:
    """Host-neutral Safe Switch control plane.

    The host integration reads one small, digest-bound state file. Candidate
    memories and trial evidence live in a separate SQLite database and cannot
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
        trial_root: str | Path = DEFAULT_TRIAL_ROOT,
        subject_id: str = DEFAULT_SUBJECT,
    ) -> "TrialManager":
        if host not in {"openclaw", "hermes"}:
            raise ValueError("host must be openclaw or hermes")
        manager = cls(state_path)
        with state_lock(manager.state_path):
            if manager.state_path.exists():
                current = load_state(manager.state_path)
                if current.mode is not TrialMode.OFF:
                    raise ValueError(
                        f"trial {current.trial_id} is already {current.mode.value}; "
                        "turn it off before starting another"
                    )
            trial_id = f"trial_{uuid.uuid4().hex}"
            trial_dir = (
                Path(trial_root).expanduser().resolve(strict=False) / trial_id
            )
            trial_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
            now = utc_now()
            state = TrialState(
                trial_id=trial_id,
                host=host,
                subject_id=subject_id or DEFAULT_SUBJECT,
                trial_dir=str(trial_dir),
                mode=TrialMode.CAPTURE,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            store = TrialStore(trial_dir / "evidence.db")
            try:
                store.create_trial(trial_id, host, state.subject_id)
                store.append_transition(
                    trial_id,
                    revision=state.revision,
                    old_mode=TrialMode.OFF.value,
                    new_mode=TrialMode.CAPTURE.value,
                    actor=_local_actor(),
                )
            finally:
                store.close()
            write_state(manager.state_path, state)
        return manager

    def effective_state(self) -> tuple[TrialState, str | None]:
        return load_effective_state(self.state_path)

    def state(self) -> TrialState:
        return load_state(self.state_path)

    def status(self) -> dict[str, Any]:
        state, warning = self.effective_state()
        result = state.public_status(warning=warning)
        if warning or state.trial_id == "unavailable":
            result["evidence"] = None
            result["readiness"] = {
                "ready_for_preview": False,
                "ready_for_canary": False,
                "ready_for_active": False,
                "reasons": ["state is missing or invalid; integration is fail-closed"],
            }
            return result
        store = self._store(state)
        try:
            evidence = store.summary(state.trial_id)
        finally:
            store.close()
        result["evidence"] = evidence
        result["readiness"] = self._readiness(state, evidence)
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
            return {"captured": 0, "candidate_ids": [], "reason": "trial is off"}
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
                    state.trial_id,
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
            return store.list_candidates(state.trial_id, statuses=statuses)
        finally:
            store.close()

    def review(self, candidate_ids: list[str], *, approve: bool) -> list[dict[str, Any]]:
        state = self.state()
        store = self._store(state)
        try:
            return store.review_candidates(
                state.trial_id, candidate_ids, approve=approve
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
        if warning or not state.mode.previews:
            return self._no_context(state, warning or "mode does not preview")
        store = self._store(state)
        try:
            approved = store.list_candidates(
                state.trial_id, statuses=("approved",)
            )
            ranked = rank_records(query, approved)
            chosen = [
                item
                for item in ranked
                if item.text_score > 0 and item.score >= min_score
            ][: max(0, limit)]
            lines: list[str] = []
            candidate_ids: list[str] = []
            used_chars = 0
            for item in chosen:
                content = str(item.record["content"]).strip()
                line = f"- {content}"
                if used_chars + len(line) + 1 > max_chars:
                    break
                lines.append(line)
                candidate_ids.append(str(item.record["id"]))
                used_chars += len(line) + 1
            context = (
                "<aetnamem_safe_switch>\n"
                + "\n".join(lines)
                + "\n</aetnamem_safe_switch>"
                if lines
                else ""
            )
            turn = store.insert_turn(
                state.trial_id,
                query_sha256=sha256_hex(query),
                session_id=session_id,
                host_run_id=host_run_id,
            )
            manifest = {
                "format": "aetnamem-safe-switch-preview-v1",
                "trial_id": state.trial_id,
                "state_revision": state.revision,
                "mode": state.mode.value,
                "query_sha256": sha256_hex(query),
                "candidate_ids": candidate_ids,
                "candidate_content_sha256": [
                    str(item.record["content_sha256"]) for item in chosen[: len(candidate_ids)]
                ],
                "context_sha256": sha256_hex(context),
            }
            preview = store.insert_preview(
                state.trial_id,
                str(turn["id"]),
                candidate_ids=candidate_ids,
                context_text=context,
                manifest_sha256=sha256_hex(canonical_json(manifest)),
            )
            inject = bool(context) and state.mode.influences_agent
            reason: str | None = None
            if state.mode is TrialMode.CANARY:
                shown_or_requested = store.count_exposures(
                    state.trial_id, mode=TrialMode.CANARY.value
                )
                if shown_or_requested >= state.canary_turns:
                    inject = False
                    reason = "canary exposure limit reached"
            exposure = None
            if inject:
                exposure = store.insert_exposure(
                    state.trial_id,
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
            return store.mark_exposure_shown(state.trial_id, exposure_id)
        finally:
            store.close()

    def transition(
        self,
        mode: TrialMode | str,
        *,
        actor: str | None = None,
        canary_turns: int | None = None,
    ) -> TrialState:
        target = mode if isinstance(mode, TrialMode) else TrialMode(mode)
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
                readiness = self._readiness(
                    state, evidence_store.summary(state.trial_id)
                )
                if target is TrialMode.PREVIEW and not readiness["ready_for_preview"]:
                    raise ValueError("; ".join(readiness["reasons"]))
                if target is TrialMode.CANARY:
                    if not readiness["ready_for_canary"]:
                        raise ValueError("; ".join(readiness["reasons"]))
                    if canary_turns is None or canary_turns < 1:
                        raise ValueError("canary requires --turns of at least 1")
                if target is TrialMode.ACTIVE and not readiness["ready_for_active"]:
                    raise ValueError("; ".join(readiness["reasons"]))
                now = utc_now()
                updated = replace(
                    state,
                    mode=target,
                    revision=state.revision + 1,
                    updated_at=now,
                    canary_turns=(
                        canary_turns
                        if target is TrialMode.CANARY and canary_turns is not None
                        else state.canary_turns
                    ),
                    state_sha256="",
                )
                evidence_store.append_transition(
                    state.trial_id,
                    revision=updated.revision,
                    old_mode=state.mode.value,
                    new_mode=target.value,
                    actor=actor or _local_actor(),
                )
                return write_state(self.state_path, updated)
            finally:
                evidence_store.close()

    def _readiness(
        self, state: TrialState, evidence: dict[str, Any]
    ) -> dict[str, Any]:
        counts = evidence["candidates"]
        approved = int(counts.get("approved", 0))
        chain_valid = bool(evidence["transition_chain"]["valid"])
        reasons: list[str] = []
        if not chain_valid:
            reasons.append("trial transition evidence did not verify")
        if approved < 1:
            reasons.append("approve at least one candidate memory")
        ready_for_preview = chain_valid and approved > 0
        ready_for_canary = ready_for_preview and int(evidence["previews"]) > 0
        if ready_for_preview and int(evidence["previews"]) < 1:
            reasons.append("observe at least one successful preview")
        shown_canary = int(evidence.get("shown_canary_exposures", 0))
        ready_for_active = (
            ready_for_canary
            and state.canary_turns > 0
            and shown_canary >= state.canary_turns
        )
        if ready_for_canary and state.canary_turns < 1:
            reasons.append("run a limited canary before active mode")
        elif (
            state.canary_turns > 0
            and shown_canary < state.canary_turns
        ):
            reasons.append(
                f"complete {state.canary_turns - shown_canary} more canary exposure(s)"
            )
        return {
            "ready_for_preview": ready_for_preview,
            "ready_for_canary": ready_for_canary,
            "ready_for_active": ready_for_active,
            "reasons": reasons,
        }

    def _store(self, state: TrialState) -> TrialStore:
        return TrialStore(Path(state.trial_dir) / "evidence.db")

    @staticmethod
    def _no_context(state: TrialState, reason: str) -> dict[str, Any]:
        return {
            "mode": TrialMode.OFF.value
            if state.trial_id == "unavailable"
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
