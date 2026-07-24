from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PLANE_NAMES = ("working", "semantic", "episodic", "procedural")


@dataclass(frozen=True)
class RuntimeScope:
    subject_id: str
    agent_id: str = "default-agent"
    deployment_id: str = "local"
    tenant_id: str | None = None
    team_id: str | None = None
    parent_agent_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    turn_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class TurnRequest:
    query: str
    scope: RuntimeScope
    task_state: dict[str, Any] = field(default_factory=dict)
    max_chars: int = 5000


@dataclass
class PlaneContribution:
    plane: str
    content: str = ""
    item_ids: list[str] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    placement: str = "current_turn_tail"
    trust: str = "derived"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutcomeReport:
    run_id: str
    scope: RuntimeScope
    success: bool
    summary: str = ""
    result_digest: str | None = None
    feedback: str | None = None
    tool_receipts: tuple[dict[str, Any], ...] = ()
    idempotency_key: str | None = None
    manifest_sha256: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    outcome_trust: str = "caller_asserted"


@dataclass(frozen=True)
class ProviderHealth:
    plane: str
    healthy: bool
    detail: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
