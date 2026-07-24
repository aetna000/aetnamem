from __future__ import annotations

import json

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.runtime.models import (
    OutcomeReport,
    PlaneContribution,
    ProviderHealth,
    TurnRequest,
)
from aetnamem.runtime.store import RuntimeStore


class WorkingProvider:
    plane = "working"

    def __init__(self, store: RuntimeStore, *, max_chars: int = 700) -> None:
        self.store = store
        self.max_chars = max(0, int(max_chars))

    def prepare(self, request: TurnRequest) -> PlaneContribution:
        scope = request.scope
        state = dict(request.task_state)
        snapshot_id: str | None = None
        if state:
            digest = sha256_hex(canonical_json(state))
            snapshot_id = self.store.save_working_snapshot(
                subject_id=scope.subject_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
                task_id=scope.task_id,
                state=state,
                state_sha256=digest,
            )
        else:
            previous = self.store.latest_working_snapshot(
                subject_id=scope.subject_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
                task_id=scope.task_id,
            )
            if previous:
                state = dict(previous["state"])
                snapshot_id = str(previous["id"])

        if not state:
            return PlaneContribution(
                plane=self.plane,
                metadata={"empty": True, "reason": "no explicit task state"},
                placement="current_turn_tail",
                trust="host_attested",
            )
        content = _render_state(state, self.max_chars)
        return PlaneContribution(
            plane=self.plane,
            content=content,
            item_ids=[snapshot_id] if snapshot_id else [],
            provenance=(
                [{"kind": "working_snapshot", "id": snapshot_id}]
                if snapshot_id
                else []
            ),
            metadata={"state_keys": sorted(state)},
            placement="current_turn_tail",
            trust="host_attested",
        )

    def record_outcome(self, outcome: OutcomeReport) -> list[dict]:
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.plane, True)


def _render_state(state: dict, max_chars: int) -> str:
    lines = ["<working_memory>"]
    for key in sorted(state):
        value = json.dumps(state[key], ensure_ascii=False, sort_keys=True)
        line = f"- {key}: {value}"
        if sum(len(item) + 1 for item in lines) + len(line) + 19 > max_chars:
            break
        lines.append(line)
    lines.append("</working_memory>")
    return "\n".join(lines) if len(lines) > 2 else ""
