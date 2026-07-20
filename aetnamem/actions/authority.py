"""Optional authority-resolution hook for externally backed authorizations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aetnamem.actions.models import EvidenceRef, PreparedOperation


@dataclass(frozen=True)
class ResolvedAuthority:
    ref_id: str
    digest: str
    authority_kind: str
    valid: bool = True


class AuthorityResolver(Protocol):
    def supports(self, ref: EvidenceRef) -> bool: ...

    def validate(
        self,
        ref: EvidenceRef,
        *,
        subject_id: str,
        prepared_operation: PreparedOperation,
        phase: str,
    ) -> ResolvedAuthority: ...
