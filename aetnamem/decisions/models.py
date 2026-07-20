"""Stable, provider-neutral contracts for collaborative decisions.

The host authenticates people and derives ``ActorContext``.  The decision
engine records opaque principals, enforces case capabilities, and never treats
an actor label as proof of identity by itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex


class DecisionError(RuntimeError):
    """Base class for decision workflow errors."""


class DecisionNotFound(DecisionError, KeyError):
    pass


class DecisionConflict(DecisionError):
    pass


class DecisionStateError(DecisionError):
    pass


class DecisionPolicyViolation(DecisionError, PermissionError):
    pass


@dataclass(frozen=True)
class ActorContext:
    """Trusted request context constructed by an authenticated host."""

    namespace_id: str
    principal_id: str
    correlation_id: str | None = None
    assurance: str = "host_authenticated"
    attestation: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.namespace_id or not self.principal_id:
            raise ValueError("namespace_id and principal_id are required")


@dataclass(frozen=True)
class CriterionSpec:
    key: str
    title: str
    choices: tuple[str, ...]
    required: bool = True
    description: str = ""
    rating_schemes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.title or not self.choices:
            raise ValueError("criterion key, title, and choices are required")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("criterion choices must be unique")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["choices"] = list(self.choices)
        value["rating_schemes"] = list(self.rating_schemes)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CriterionSpec":
        return cls(
            key=str(value["key"]),
            title=str(value["title"]),
            choices=tuple(str(item) for item in value["choices"]),
            required=bool(value.get("required", True)),
            description=str(value.get("description", "")),
            rating_schemes=tuple(str(item) for item in value.get("rating_schemes", ())),
        )


@dataclass(frozen=True)
class DecisionTemplate:
    template_id: str
    version: str
    title: str
    criteria: tuple[CriterionSpec, ...]
    profile: str = "generic"
    sections: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.template_id or not self.version or not self.title:
            raise ValueError("template id, version, and title are required")
        keys = [criterion.key for criterion in self.criteria]
        if len(keys) != len(set(keys)):
            raise ValueError("template criterion keys must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "title": self.title,
            "profile": self.profile,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
            "sections": list(self.sections),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DecisionTemplate":
        return cls(
            template_id=str(value["template_id"]),
            version=str(value["version"]),
            title=str(value["title"]),
            profile=str(value.get("profile", "generic")),
            criteria=tuple(CriterionSpec.from_dict(item) for item in value.get("criteria", ())),
            sections=tuple(str(item) for item in value.get("sections", ())),
            metadata=dict(value.get("metadata") or {}),
        )

    @property
    def digest(self) -> str:
        return digest_json(self.to_dict())

    def criterion(self, key: str) -> CriterionSpec:
        for criterion in self.criteria:
            if criterion.key == key:
                return criterion
        raise ValueError(f"criterion is not defined by the pinned template: {key}")


@dataclass(frozen=True)
class ArtifactLink:
    source_revision_id: str
    role: str = "supports"

    def __post_init__(self) -> None:
        if not self.source_revision_id or not self.role:
            raise ValueError("source revision and role are required")


@dataclass(frozen=True)
class ConsensusPolicy:
    method: str = "threshold"
    threshold: float = 0.5
    quorum: float = 0.5
    denominator: str = "non_abstain"
    passing_choices: tuple[str, ...] = ("yes",)

    def __post_init__(self) -> None:
        if self.method not in {"threshold", "unanimity", "manual"}:
            raise ValueError("consensus method must be threshold, unanimity, or manual")
        if not 0 < self.threshold <= 1 or not 0 <= self.quorum <= 1:
            raise ValueError("threshold and quorum must be fractions between zero and one")
        if self.denominator not in {"eligible", "participating", "non_abstain"}:
            raise ValueError("invalid consensus denominator")
        if self.method != "manual" and not self.passing_choices:
            raise ValueError("computed consensus requires passing choices")

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "threshold": self.threshold,
            "quorum": self.quorum,
            "denominator": self.denominator,
            "passing_choices": list(self.passing_choices),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ConsensusPolicy":
        return cls(
            method=str(value.get("method", "threshold")),
            threshold=float(value.get("threshold", 0.5)),
            quorum=float(value.get("quorum", 0.5)),
            denominator=str(value.get("denominator", "non_abstain")),
            passing_choices=tuple(str(item) for item in value.get("passing_choices", ("yes",))),
        )

    @property
    def digest(self) -> str:
        return digest_json(self.to_dict())


ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "chair": (
        "adopt",
        "authorize",
        "create_artifact",
        "manage_ballot",
        "manage_conflicts",
        "manage_members",
        "manage_retention",
        "vote",
    ),
    "voter": ("create_artifact", "vote"),
    "methodologist": ("create_artifact", "vote"),
    "approver": ("approve", "authorize", "create_artifact"),
    "observer": (),
    "agent": ("create_draft",),
}


def capabilities_for_role(role: str) -> tuple[str, ...]:
    try:
        return ROLE_CAPABILITIES[role]
    except KeyError as exc:
        raise ValueError(f"unknown decision role: {role}") from exc


def digest_json(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def revision_digest(
    *, artifact_id: str, revision: int, kind: str, content: dict[str, Any], author: str
) -> str:
    return digest_json(
        {
            "format": "aetnamem-decision-artifact-v1",
            "artifact_id": artifact_id,
            "revision": revision,
            "kind": kind,
            "content": content,
            "author": author,
        }
    )
