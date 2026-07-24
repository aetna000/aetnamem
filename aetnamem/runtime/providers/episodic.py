from __future__ import annotations

from aetnamem.runtime.models import (
    OutcomeReport,
    PlaneContribution,
    ProviderHealth,
    TurnRequest,
)
from aetnamem.runtime.store import RuntimeStore


class EpisodicProvider:
    plane = "episodic"

    def __init__(
        self, store: RuntimeStore, *, max_chars: int = 900, max_outcomes: int = 3
    ) -> None:
        self.store = store
        self.max_chars = max(0, int(max_chars))
        self.max_outcomes = max(0, int(max_outcomes))

    def prepare(self, request: TurnRequest) -> PlaneContribution:
        scope = request.scope
        outcomes = self.store.relevant_outcomes(
            subject_id=scope.subject_id,
            agent_id=scope.agent_id,
            query=request.query,
            limit=self.max_outcomes,
        )
        lessons = self.store.active_lessons(
            subject_id=scope.subject_id,
            agent_id=scope.agent_id,
            query=request.query,
            limit=self.max_outcomes,
        )
        lines = ["<episodic_memory>"]
        item_ids: list[str] = []
        provenance: list[dict] = []
        for item in outcomes:
            status = "succeeded" if item["success"] else "failed"
            line = f"- Prior attempt {status}: {item['summary']} [outcome:{item['id'][:16]}]"
            if _would_overflow(lines, line, self.max_chars):
                break
            lines.append(line)
            item_ids.append(str(item["id"]))
            provenance.append({"kind": "experience_outcome", "id": item["id"]})
        for lesson in lessons:
            line = f"- Reviewed lesson: {lesson['content']} [lesson:{lesson['id'][:16]}]"
            if _would_overflow(lines, line, self.max_chars):
                break
            lines.append(line)
            item_ids.append(str(lesson["id"]))
            provenance.append({"kind": "lesson", "id": lesson["id"]})
        lines.append("</episodic_memory>")
        content = "\n".join(lines) if len(lines) > 2 else ""
        return PlaneContribution(
            plane=self.plane,
            content=content,
            item_ids=item_ids,
            provenance=provenance,
            metadata={"outcome_count": len(outcomes), "lesson_count": len(lessons)},
            placement="current_turn_tail",
            trust="host_attested",
        )

    def record_outcome(self, outcome: OutcomeReport) -> list[dict]:
        stored = self.store.outcome_for_run(outcome.run_id)
        if stored is None or outcome.success or not outcome.summary.strip():
            return []
        lesson = self.store.create_lesson(
            outcome_id=str(stored["id"]),
            subject_id=outcome.scope.subject_id,
            agent_id=outcome.scope.agent_id,
            content=f"Avoid repeating this failed approach: {outcome.summary.strip()}",
        )
        lesson["kind"] = "lesson"
        return [lesson]

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.plane, True)


def _would_overflow(lines: list[str], line: str, max_chars: int) -> bool:
    return sum(len(item) + 1 for item in lines) + len(line) + 20 > max_chars
