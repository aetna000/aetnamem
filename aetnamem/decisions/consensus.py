"""Deterministic ballot outcome calculation."""

from __future__ import annotations

import math
from typing import Any

from aetnamem.decisions.models import ConsensusPolicy, digest_json


def calculate_outcome(
    *,
    ballot_id: str,
    target_revision_id: str,
    target_digest: str,
    eligible: list[str],
    votes: list[dict[str, Any]],
    policy: ConsensusPolicy,
    manual_passed: bool | None = None,
    manual_rationale_digest: str | None = None,
) -> dict[str, Any]:
    active = sorted(votes, key=lambda item: (item["principal_id"], item["revision"]))
    tally: dict[str, int] = {}
    for vote in active:
        tally[vote["choice"]] = tally.get(vote["choice"], 0) + 1

    participating = len(active)
    non_abstain = sum(count for choice, count in tally.items() if choice != "abstain")
    quorum_required = math.ceil(len(eligible) * policy.quorum)
    quorum_met = participating >= quorum_required

    if policy.method == "manual":
        if manual_passed is None:
            raise ValueError("manual consensus requires manual_passed")
        passed = bool(manual_passed) and quorum_met
        denominator_count = participating
        passing_count = 0
    else:
        passing_count = sum(tally.get(choice, 0) for choice in policy.passing_choices)
        denominator_count = {
            "eligible": len(eligible),
            "participating": participating,
            "non_abstain": non_abstain,
        }[policy.denominator]
        ratio = passing_count / denominator_count if denominator_count else 0.0
        required = 1.0 if policy.method == "unanimity" else policy.threshold
        passed = quorum_met and ratio >= required

    body = {
        "format": "aetnamem-decision-outcome-v1",
        "ballot_id": ballot_id,
        "target_revision_id": target_revision_id,
        "target_digest": target_digest,
        "eligible_principals": sorted(eligible),
        "counted_vote_ids": [vote["id"] for vote in active],
        "vote_commitments": [vote["commitment"] for vote in active],
        "policy": policy.to_dict(),
        "tally": dict(sorted(tally.items())),
        "participating": participating,
        "quorum_required": quorum_required,
        "quorum_met": quorum_met,
        "passing_count": passing_count,
        "denominator_count": denominator_count,
        "passed": passed,
        "manual_rationale_digest": manual_rationale_digest,
    }
    return {**body, "digest": digest_json(body)}

