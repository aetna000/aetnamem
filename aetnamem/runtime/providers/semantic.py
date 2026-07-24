from __future__ import annotations

from aetnamem.memory import Memory
from aetnamem.runtime.models import (
    OutcomeReport,
    PlaneContribution,
    ProviderHealth,
    TurnRequest,
)


class SemanticProvider:
    plane = "semantic"

    def __init__(
        self,
        memory: Memory,
        *,
        max_chars: int = 1800,
        max_records: int = 3,
        min_score: float = 0.3,
    ) -> None:
        self.memory = memory
        self.max_chars = max(0, int(max_chars))
        self.max_records = max(0, int(max_records))
        self.min_score = float(min_score)

    def prepare(self, request: TurnRequest) -> PlaneContribution:
        persona_chars = min(600, self.max_chars // 3)
        recall_chars = max(0, self.max_chars - persona_chars)
        pack = self.memory.build_context_pack(
            request.scope.subject_id,
            request.query,
            session_id=request.scope.session_id,
            persona_max_chars=persona_chars,
            recall_max_records=self.max_records,
            recall_max_chars=recall_chars,
            min_score=self.min_score,
            reference_mode="compact",
        )
        stable = str(pack["stable_context"])
        dynamic = str(pack["dynamic_context"])
        content = "\n".join(part for part in (stable, dynamic) if part)
        record_ids = [
            *pack["stable_record_ids"],
            *pack["dynamic_record_ids"],
        ]
        return PlaneContribution(
            plane=self.plane,
            content=content,
            item_ids=record_ids,
            provenance=[
                {"kind": "semantic_record", "id": record_id}
                for record_id in record_ids
            ],
            metadata={"legacy_context_pack": pack},
            placement="split",
            trust="governed",
        )

    def record_outcome(self, outcome: OutcomeReport) -> list[dict]:
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.plane, True)
