from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex


BASELINE_ARMS = {
    "no-memory": "0000",
    "semantic-only": "0100",
    "all-four-always": "1111",
}


def freeze_policy(
    rows: list[dict[str, Any]],
    *,
    max_mean_context_chars: float,
    minimum_runs: int = 2,
) -> dict[str, Any]:
    training = [row for row in rows if row.get("task_split") == "train"]
    if not training:
        raise ValueError("policy training requires training-split results")
    candidates = []
    for value in range(16):
        arm = f"{value:04b}"
        members = [row for row in training if row["arm_id"] == arm]
        if len(members) < minimum_runs:
            continue
        if not all(
            row.get("context_trust") == "host_verified"
            for row in members
        ):
            continue
        context_chars = mean(
            float(row.get("context_chars") or 0.0) for row in members
        )
        if context_chars > max_mean_context_chars:
            continue
        successes = [float(row["success"]) for row in members]
        rate = mean(successes)
        se = (
            stdev(successes) / math.sqrt(len(successes))
            if len(successes) > 1
            else 1.0
        )
        candidates.append(
            {
                "arm_id": arm,
                "runs": len(members),
                "success_rate": rate,
                "pessimistic_score": rate - 1.96 * se,
                "mean_context_chars": context_chars,
                "mean_tokens": mean(
                    float(row.get("tokens") or 0.0) for row in members
                ),
            }
        )
    if not candidates:
        raise ValueError("no policy arm satisfies the registered budget and evidence floor")
    selected = max(
        candidates,
        key=lambda item: (
            item["pessimistic_score"],
            item["success_rate"],
            -item["mean_context_chars"],
            item["arm_id"],
        ),
    )
    policy = {
        "format": "aetnamem-memory-impact-frozen-policy-v1",
        "selection_rule": (
            "highest pessimistic training success within host-verified "
            "AetnaMem context-character budget"
        ),
        "max_mean_context_chars": max_mean_context_chars,
        "selected_arm": selected["arm_id"],
        "naive_outcome_weighted_arm": max(
            candidates,
            key=lambda item: (
                item["success_rate"],
                -item["mean_context_chars"],
                item["arm_id"],
            ),
        )["arm_id"],
        "training_evidence": selected,
        "fallback_arm": "0000",
        "allowed_features": [],
    }
    policy["policy_sha256"] = sha256_hex(canonical_json(policy))
    return policy


def evaluate_held_out(
    rows: list[dict[str, Any]], policy: dict[str, Any]
) -> dict[str, Any]:
    digest = policy.get("policy_sha256")
    unsigned = {key: value for key, value in policy.items() if key != "policy_sha256"}
    if digest != sha256_hex(canonical_json(unsigned)):
        raise ValueError("frozen policy digest is invalid")
    held_out = [row for row in rows if row.get("task_split") == "held-out"]
    if not held_out:
        raise ValueError("held-out evaluation requires held-out results")
    comparators = {
        "frozen-policy": str(policy["selected_arm"]),
        **BASELINE_ARMS,
        "outcome-weighting-without-randomization": str(
            policy["naive_outcome_weighted_arm"]
        ),
    }
    results = {}
    for name, arm in comparators.items():
        members = [row for row in held_out if row["arm_id"] == arm]
        successes = sum(float(row["success"]) for row in members)
        total_cost = sum(float(row.get("cost_usd") or 0.0) for row in members)
        results[name] = {
            "arm_id": arm,
            "runs": len(members),
            "success_rate": successes / len(members) if members else None,
            "successes_per_dollar": successes / total_cost if total_cost else None,
            "mean_tokens": (
                mean(float(row.get("tokens") or 0.0) for row in members)
                if members
                else None
            ),
            "unsafe_actions": sum(
                int(row.get("unsafe_actions") or 0) for row in members
            ),
            "cost_evidence_complete": bool(members)
            and all(
                row.get("cost_trust") == "provider_reported"
                and row.get("cost_budget_compliant") is True
                for row in members
            ),
        }
    relevance_members = [
        row
        for row in held_out
        if row["arm_id"] == row.get("relevance_arm", "0100")
    ]
    relevance_successes = sum(float(row["success"]) for row in relevance_members)
    relevance_cost = sum(
        float(row.get("cost_usd") or 0.0) for row in relevance_members
    )
    results["relevance-retrieval"] = {
        "arm_id": "task-registered",
        "runs": len(relevance_members),
        "success_rate": (
            relevance_successes / len(relevance_members)
            if relevance_members
            else None
        ),
        "successes_per_dollar": (
            relevance_successes / relevance_cost if relevance_cost else None
        ),
        "mean_tokens": (
            mean(float(row.get("tokens") or 0.0) for row in relevance_members)
            if relevance_members
            else None
        ),
        "unsafe_actions": sum(
            int(row.get("unsafe_actions") or 0) for row in relevance_members
        ),
        "cost_evidence_complete": bool(relevance_members)
        and all(
            row.get("cost_trust") == "provider_reported"
            and row.get("cost_budget_compliant") is True
            for row in relevance_members
        ),
    }
    comparisons = _paired_comparisons(
        held_out,
        selected_arm=str(policy["selected_arm"]),
        comparator_arms={
            **BASELINE_ARMS,
            "outcome-weighting-without-randomization": str(
                policy["naive_outcome_weighted_arm"]
            ),
        },
    )
    return {
        "format": "aetnamem-memory-impact-held-out-v1",
        "policy_sha256": digest,
        "comparators": results,
        "paired_success_differences": comparisons,
        "claim_ready": _wins(results, comparisons),
    }


def write_policy(path: str | Path, policy: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _wins(
    results: dict[str, dict[str, Any]],
    comparisons: dict[str, dict[str, Any]],
) -> bool:
    selected = results["frozen-policy"]
    if (
        selected["success_rate"] is None
        or selected["runs"] < 20
        or selected["unsafe_actions"] != 0
        or not selected["cost_evidence_complete"]
    ):
        return False
    return bool(comparisons) and all(
        value["blocks"] >= 20 and value["lower_95"] > 0
        for value in comparisons.values()
    )


def _paired_comparisons(
    rows: list[dict[str, Any]],
    *,
    selected_arm: str,
    comparator_arms: dict[str, str],
) -> dict[str, dict[str, Any]]:
    blocks: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        blocks.setdefault(str(row["block_id"]), {})[str(row["arm_id"])] = row
    result: dict[str, dict[str, Any]] = {}
    comparator_names = {**comparator_arms, "relevance-retrieval": "task-registered"}
    for name, arm in comparator_names.items():
        differences = []
        for members in blocks.values():
            selected = members.get(selected_arm)
            if selected is None:
                continue
            comparator_arm = (
                str(selected.get("relevance_arm", "0100"))
                if name == "relevance-retrieval"
                else arm
            )
            comparator = members.get(comparator_arm)
            if comparator is None:
                continue
            differences.append(
                float(selected["success"]) - float(comparator["success"])
            )
        if not differences:
            continue
        effect = mean(differences)
        se = (
            stdev(differences) / math.sqrt(len(differences))
            if len(differences) > 1
            else 0.0
        )
        result[name] = {
            "blocks": len(differences),
            "risk_difference": effect,
            "lower_95": effect - 1.96 * se,
            "upper_95": effect + 1.96 * se,
        }
    return result
