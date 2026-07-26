from __future__ import annotations

from dataclasses import dataclass
import math
import random
from statistics import mean, stdev
from typing import Any, Callable

from aetnamem.runtime.models import PLANE_NAMES


@dataclass(frozen=True)
class Estimate:
    name: str
    estimate: float
    lower: float
    upper: float
    standard_error: float
    blocks: int
    estimand: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "estimate": self.estimate,
            "lower": self.lower,
            "upper": self.upper,
            "standard_error": self.standard_error,
            "blocks": self.blocks,
            "estimand": self.estimand,
        }


def estimate_registered_effects(rows: list[dict[str, Any]]) -> dict[str, Estimate]:
    _validate_rows(rows)
    result: dict[str, Estimate] = {}
    for index, plane in enumerate(PLANE_NAMES):
        result[plane] = _block_contrast(
            rows,
            plane,
            lambda arm, i=index: 1.0 if arm[i] == "1" else -1.0,
            divisor=8.0,
            estimand="factorial intention-to-treat risk difference",
        )
    for left in range(4):
        for right in range(left + 1, 4):
            name = f"{PLANE_NAMES[left]}:{PLANE_NAMES[right]}"
            result[name] = _block_contrast(
                rows,
                name,
                lambda arm, i=left, j=right: (
                    1.0 if arm[i] == arm[j] else -1.0
                ),
                divisor=4.0,
                estimand="factorial difference-in-differences",
            )
    return result


def estimate_primitive_effects(rows: list[dict[str, Any]]) -> dict[str, Estimate]:
    """Recover registered additive coefficients when S×P is the interaction term."""
    factorial = estimate_registered_effects(rows)
    factorial["semantic"] = _block_contrast(
        rows,
        "semantic",
        lambda arm: (
            1.0 if arm[1] == "1" else -1.0
        )
        if arm[3] == "0"
        else 0.0,
        divisor=4.0,
        estimand="semantic risk difference with procedural absent, averaged over W and E",
    )
    factorial["procedural"] = _block_contrast(
        rows,
        "procedural",
        lambda arm: (
            1.0 if arm[3] == "1" else -1.0
        )
        if arm[1] == "0"
        else 0.0,
        divisor=4.0,
        estimand="procedural risk difference with semantic absent, averaged over W and E",
    )
    return factorial


def cell_rates(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    _validate_rows(rows)
    result = {}
    for value in range(16):
        arm = f"{value:04b}"
        members = [row for row in rows if row["arm_id"] == arm]
        successes = sum(float(row["success"]) for row in members)
        cost = sum(float(row.get("cost_usd") or 0.0) for row in members)
        result[arm] = {
            "runs": float(len(members)),
            "success_rate": successes / len(members) if members else math.nan,
            "successes_per_dollar": (
                successes / cost if cost > 0 else math.nan
            ),
            "mean_tokens": mean(
                float(row.get("tokens") or 0.0) for row in members
            )
            if members
            else math.nan,
            "mean_latency_ms": mean(
                float(row.get("latency_ms") or 0.0) for row in members
            )
            if members
            else math.nan,
            "unsafe_actions": sum(
                float(row.get("unsafe_actions") or 0.0) for row in members
            ),
            "false_warnings": sum(
                float(row.get("false_warnings") or 0.0) for row in members
            ),
        }
    return result


def _block_contrast(
    rows: list[dict[str, Any]],
    name: str,
    sign: Callable[[str], float],
    *,
    divisor: float,
    estimand: str,
) -> Estimate:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["block_id"]), []).append(row)
    contrasts = []
    for members in grouped.values():
        arms = {str(item["arm_id"]) for item in members}
        if arms != {f"{value:04b}" for value in range(16)}:
            continue
        contrasts.append(
            sum(sign(str(row["arm_id"])) * float(row["success"]) for row in members)
            / divisor
        )
    if not contrasts:
        raise ValueError("no complete 16-arm blocks are available")
    value = mean(contrasts)
    se = stdev(contrasts) / math.sqrt(len(contrasts)) if len(contrasts) > 1 else 0.0
    return Estimate(
        name=name,
        estimate=value,
        lower=value - 1.96 * se,
        upper=value + 1.96 * se,
        standard_error=se,
        blocks=len(contrasts),
        estimand=estimand,
    )


def observational_difference(
    rows: list[dict[str, Any]], plane: str
) -> float:
    index = PLANE_NAMES.index(plane)
    treated = [
        float(row["success"]) for row in rows if str(row["arm_id"])[index] == "1"
    ]
    control = [
        float(row["success"]) for row in rows if str(row["arm_id"])[index] == "0"
    ]
    if not treated or not control:
        return math.nan
    return mean(treated) - mean(control)


def cluster_bootstrap(
    rows: list[dict[str, Any]],
    statistic: Callable[[list[dict[str, Any]]], float],
    *,
    iterations: int = 1000,
    seed: int = 17,
) -> tuple[float, float]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["block_id"]), []).append(row)
    blocks = sorted(grouped)
    rng = random.Random(seed)
    values = []
    for _ in range(iterations):
        sample = []
        for sample_index in range(len(blocks)):
            block = rng.choice(blocks)
            for row in grouped[block]:
                sample.append({**row, "block_id": f"{block}:{sample_index}"})
        values.append(statistic(sample))
    values.sort()
    return (
        values[int(0.025 * (len(values) - 1))],
        values[int(0.975 * (len(values) - 1))],
    )


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("impact analysis requires observations")
    for row in rows:
        arm = str(row.get("arm_id", ""))
        if len(arm) != 4 or any(value not in "01" for value in arm):
            raise ValueError(f"invalid arm_id: {arm!r}")
        if "block_id" not in row or "success" not in row:
            raise ValueError("impact observations require block_id and success")
