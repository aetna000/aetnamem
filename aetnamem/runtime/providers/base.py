from __future__ import annotations

from typing import Protocol

from aetnamem.runtime.models import (
    OutcomeReport,
    PlaneContribution,
    ProviderHealth,
    TurnRequest,
)


class MemoryPlaneProvider(Protocol):
    plane: str

    def prepare(self, request: TurnRequest) -> PlaneContribution:
        ...

    def record_outcome(self, outcome: OutcomeReport) -> list[dict]:
        ...

    def health(self) -> ProviderHealth:
        ...
