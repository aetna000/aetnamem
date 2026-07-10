"""Deterministic policy for evidence-to-action authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aetnamem.actions.models import ActionMode, EvidenceRef, PreparedOperation, digest_json


class ActionPolicyViolation(ValueError):
    pass


@dataclass(frozen=True)
class GuardPolicy:
    trusted_authority_tiers: tuple[str, ...] = ("trusted_user", "user_confirmed")
    require_attested_authority: bool = True
    require_authority_for_enforce: bool = True

    @property
    def digest(self) -> str:
        return digest_json(
            {
                "trusted_authority_tiers": self.trusted_authority_tiers,
                "require_attested_authority": self.require_attested_authority,
                "require_authority_for_enforce": self.require_authority_for_enforce,
            }
        )

    def validate_operation(
        self,
        prepared: PreparedOperation,
        evidence: Iterable[EvidenceRef],
        mode: ActionMode,
    ) -> None:
        if prepared.effect_class.value == "unknown_blocked":
            raise ActionPolicyViolation("unknown effects fail closed")
        authorities = [item for item in evidence if item.relation == "authorized_by"]
        for authority in authorities:
            if authority.trust_tier not in self.trusted_authority_tiers:
                raise ActionPolicyViolation(
                    f"{authority.trust_tier} evidence may inform but cannot authorize an action"
                )
            if self.require_attested_authority and not authority.attested:
                raise ActionPolicyViolation("action authority is not host-attested")
        if (
            mode is ActionMode.ENFORCE
            and self.require_authority_for_enforce
            and prepared.effect_class.value != "read_only"
            and not authorities
        ):
            raise ActionPolicyViolation("enforced mutations require authorized_by evidence")
