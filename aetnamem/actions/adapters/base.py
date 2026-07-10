"""Execution-provider boundary for guarded actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from aetnamem.actions.models import (
    AdapterReceipt,
    PreparedOperation,
    VerificationResult,
)


@dataclass(frozen=True)
class ActionContext:
    transaction_id: str
    operation_id: str
    subject_id: str
    actor_id: str


@runtime_checkable
class ActionAdapter(Protocol):
    name: str

    def manifest(self) -> dict[str, Any]: ...

    def prepare(
        self,
        operation: str,
        arguments: dict[str, Any],
        context: ActionContext,
    ) -> PreparedOperation: ...

    def revalidate(self, prepared: PreparedOperation) -> VerificationResult: ...

    def execute(
        self,
        prepared: PreparedOperation,
        *,
        idempotency_key: str,
    ) -> AdapterReceipt: ...

    def verify(
        self,
        prepared: PreparedOperation,
        receipt: AdapterReceipt,
    ) -> VerificationResult: ...

    def compensate(
        self,
        prepared: PreparedOperation,
        receipt: AdapterReceipt,
        *,
        idempotency_key: str,
    ) -> AdapterReceipt: ...

    def verify_compensation(
        self,
        prepared: PreparedOperation,
        receipt: AdapterReceipt,
    ) -> VerificationResult: ...
