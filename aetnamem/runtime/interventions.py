from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.runtime.models import PLANE_NAMES, PlaneContribution


CML_MANIFEST_FORMAT = "aetnamem-cml-manifest-v1"


@dataclass(frozen=True)
class CandidateContribution:
    contribution_id: str
    contribution: PlaneContribution


@dataclass(frozen=True)
class InterventionDecision:
    decision_id: str
    experiment_id: str
    run_id: str
    plane: str
    candidate_contribution_id: str
    candidate_sha256: str
    assigned: bool
    applied: bool
    propensity: float
    arm_id: str
    applied_arm_id: str
    joint_propensity: float
    design: str
    stratum: str
    seed_commitment: str
    policy_version: str
    policy_sha256: str
    eligibility: str
    pinned_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CMLAssignment:
    mode: str
    admitted: tuple[PlaneContribution, ...]
    decisions: tuple[InterventionDecision, ...]
    manifest: dict[str, Any]


def assign_contributions(
    *,
    cml_config: dict[str, Any],
    run_id: str,
    candidates: list[CandidateContribution],
    default_stratum: str,
) -> CMLAssignment | None:
    mode = str(cml_config.get("mode", "off"))
    if mode == "off":
        return None

    experiment_id = str(cml_config["experiment_id"])
    design = str(cml_config.get("design", "bernoulli"))
    probability = float(cml_config.get("assignment_probability", 0.5))
    eligible_planes = {str(value) for value in cml_config.get("eligible_planes", [])}
    pinned_planes = {str(value) for value in cml_config.get("pinned_planes", [])}
    policy_version = str(cml_config.get("policy_version", "cml-policy-v1"))
    stratum = str(cml_config.get("stratum") or default_stratum or "default")
    seed = str(cml_config["seed"])
    seed_commitment = sha256_hex(seed)
    policy_payload = {
        key: value
        for key, value in cml_config.items()
        if key != "seed"
    }
    policy_sha256 = sha256_hex(canonical_json(policy_payload))

    provisional: list[dict[str, Any]] = []
    for candidate in candidates:
        contribution = candidate.contribution
        candidate_sha256 = _candidate_sha256(contribution)
        if contribution.plane in pinned_planes:
            assigned = True
            propensity = 1.0
            eligibility = "pinned"
            pinned_reason = "configured_pinned"
        elif contribution.plane not in eligible_planes:
            assigned = True
            propensity = 1.0
            eligibility = "ineligible"
            pinned_reason = "not_experiment_eligible"
        else:
            assigned = _bernoulli_draw(
                seed=seed,
                experiment_id=experiment_id,
                stratum=stratum,
                run_id=run_id,
                plane=contribution.plane,
                probability=probability,
            )
            propensity = probability if assigned else 1.0 - probability
            eligibility = "eligible"
            pinned_reason = None
        applied = assigned if mode == "experiment" else True
        provisional.append(
            {
                "candidate": candidate,
                "candidate_sha256": candidate_sha256,
                "assigned": assigned,
                "applied": applied,
                "propensity": propensity,
                "eligibility": eligibility,
                "pinned_reason": pinned_reason,
            }
        )

    assigned_by_plane = {
        item["candidate"].contribution.plane: bool(item["assigned"])
        for item in provisional
    }
    applied_by_plane = {
        item["candidate"].contribution.plane: bool(item["applied"])
        for item in provisional
    }
    arm_id = _arm_id(assigned_by_plane)
    applied_arm_id = _arm_id(applied_by_plane)
    joint_propensity = 1.0
    for item in provisional:
        if item["eligibility"] == "eligible":
            joint_propensity *= float(item["propensity"])

    decisions: list[InterventionDecision] = []
    for item in provisional:
        candidate = item["candidate"]
        decision_id = "cmldec_" + sha256_hex(
            canonical_json(
                {
                    "experiment_id": experiment_id,
                    "run_id": run_id,
                    "plane": candidate.contribution.plane,
                    "candidate_sha256": item["candidate_sha256"],
                }
            )
        )[:32]
        decisions.append(
            InterventionDecision(
                decision_id=decision_id,
                experiment_id=experiment_id,
                run_id=run_id,
                plane=candidate.contribution.plane,
                candidate_contribution_id=candidate.contribution_id,
                candidate_sha256=str(item["candidate_sha256"]),
                assigned=bool(item["assigned"]),
                applied=bool(item["applied"]),
                propensity=float(item["propensity"]),
                arm_id=arm_id,
                applied_arm_id=applied_arm_id,
                joint_propensity=joint_propensity,
                design=design,
                stratum=stratum,
                seed_commitment=seed_commitment,
                policy_version=policy_version,
                policy_sha256=policy_sha256,
                eligibility=str(item["eligibility"]),
                pinned_reason=item["pinned_reason"],
            )
        )

    admitted = tuple(
        item["candidate"].contribution
        for item in provisional
        if item["applied"]
    )
    manifest = {
        "format": CML_MANIFEST_FORMAT,
        "mode": mode,
        "experiment_id": experiment_id,
        "design": design,
        "stratum": stratum,
        "policy_version": policy_version,
        "policy_sha256": policy_sha256,
        "seed_commitment": seed_commitment,
        "arm_id": arm_id,
        "applied_arm_id": applied_arm_id,
        "joint_propensity": joint_propensity,
        "decisions": [
            {
                "decision_id": item.decision_id,
                "plane": item.plane,
                "candidate_contribution_id": item.candidate_contribution_id,
                "candidate_sha256": item.candidate_sha256,
                "assigned": item.assigned,
                "applied": item.applied,
                "propensity": item.propensity,
                "eligibility": item.eligibility,
                "pinned_reason": item.pinned_reason,
            }
            for item in decisions
        ],
    }
    return CMLAssignment(
        mode=mode,
        admitted=admitted,
        decisions=tuple(decisions),
        manifest=manifest,
    )


def _candidate_sha256(contribution: PlaneContribution) -> str:
    return sha256_hex(
        canonical_json(
            {
                "plane": contribution.plane,
                "content_sha256": sha256_hex(contribution.content),
                "item_ids": contribution.item_ids,
                "provenance": contribution.provenance,
                "metadata": contribution.metadata,
                "placement": contribution.placement,
                "trust": contribution.trust,
            }
        )
    )


def _bernoulli_draw(
    *,
    seed: str,
    experiment_id: str,
    stratum: str,
    run_id: str,
    plane: str,
    probability: float,
) -> bool:
    message = canonical_json(
        {
            "experiment_id": experiment_id,
            "stratum": stratum,
            "run_id": run_id,
            "plane": plane,
        }
    ).encode("utf-8")
    digest = hmac.new(seed.encode("utf-8"), message, hashlib.sha256).digest()
    draw = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return draw < probability


def _arm_id(values: dict[str, bool]) -> str:
    return "".join(
        "1" if values.get(plane) else "0" if plane in values else "x"
        for plane in PLANE_NAMES
    )
