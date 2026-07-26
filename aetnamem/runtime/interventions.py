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
    assigned_arm = str(cml_config.get("assigned_arm", ""))
    if design == "balanced-factorial":
        from aetnamem.impact.allocation import arm_planes, verify_assignment_token

        candidate_planes = {item.contribution.plane for item in candidates}
        if candidate_planes != set(PLANE_NAMES):
            raise ValueError(
                "balanced-factorial run requires candidates for all four memory planes"
            )
        if cml_config.get("require_nonempty_candidates", False):
            empty = [
                item.contribution.plane
                for item in candidates
                if not item.contribution.content.strip()
            ]
            if empty:
                raise ValueError(
                    "balanced-factorial candidates must be non-empty: "
                    + ", ".join(empty)
                )
        token_valid = verify_assignment_token(
            seed=seed,
            experiment_id=experiment_id,
            task_id=str(cml_config["task_id"]),
            block_id=str(cml_config["block_id"]),
            repetition=int(cml_config["repetition"]),
            assignment_index=int(cml_config["assignment_index"]),
            run_id=run_id,
            arm_id=assigned_arm,
            assignment_probability=probability,
            seed_commitment=seed_commitment,
            schedule_sha256=str(cml_config["schedule_sha256"]),
            assignment_token=str(cml_config["assignment_token"]),
        )
        if not token_valid:
            raise ValueError("balanced-factorial assignment token is invalid")
        assigned_planes = arm_planes(assigned_arm)
    else:
        assigned_planes = {}

    provisional: list[dict[str, Any]] = []
    for candidate in candidates:
        contribution = candidate.contribution
        candidate_sha256 = _candidate_sha256(
            contribution,
            identity=str(cml_config.get("candidate_identity", "evidence-envelope-v1")),
        )
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
        elif design == "balanced-factorial":
            assigned = assigned_planes[contribution.plane]
            propensity = 0.5
            eligibility = "eligible"
            pinned_reason = None
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
    joint_propensity = (
        probability
        if design == "balanced-factorial"
        else _joint_propensity(provisional)
    )

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
        "schedule_sha256": cml_config.get("schedule_sha256"),
        "block_id": cml_config.get("block_id"),
        "assignment_index": cml_config.get("assignment_index"),
        "assignment_token_sha256": (
            sha256_hex(str(cml_config["assignment_token"]))
            if cml_config.get("assignment_token")
            else None
        ),
        "require_full_exposure": bool(
            cml_config.get("require_full_exposure", False)
        ),
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


def _candidate_sha256(
    contribution: PlaneContribution, *, identity: str = "evidence-envelope-v1"
) -> str:
    if identity not in {"evidence-envelope-v1", "content-envelope-v1"}:
        raise ValueError(f"unknown candidate identity: {identity}")
    evidence = (
        {
            "item_ids": contribution.item_ids,
            "provenance": contribution.provenance,
        }
        if identity == "evidence-envelope-v1"
        else {}
    )
    return sha256_hex(
        canonical_json(
            {
                "identity": identity,
                "plane": contribution.plane,
                "content_sha256": sha256_hex(contribution.content),
                **evidence,
                "metadata": contribution.metadata,
                "placement": contribution.placement,
                "trust": contribution.trust,
            }
        )
    )


def _joint_propensity(provisional: list[dict[str, Any]]) -> float:
    value = 1.0
    for item in provisional:
        if item["eligibility"] == "eligible":
            value *= float(item["propensity"])
    return value


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
