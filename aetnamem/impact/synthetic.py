from __future__ import annotations

import json
import math
from pathlib import Path
import random
from statistics import mean
import tempfile
from typing import Any

from aetnamem.impact.allocation import BalancedFactorialAllocator
from aetnamem.impact.estimate import (
    estimate_primitive_effects,
    estimate_registered_effects,
)
from aetnamem.runtime import MemoryRuntime, RuntimeScope, preset_config
from aetnamem.runtime.models import PlaneContribution, ProviderHealth


PLANTED = {
    "working": 0.10,
    "semantic": 0.20,
    "episodic": 0.00,
    "procedural": 0.15,
    "semantic:procedural": 0.25,
}


def generate_randomized(
    *, blocks: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for block in range(blocks):
        difficulty = rng.uniform(-0.08, 0.08)
        heterogeneous = rng.uniform(-0.03, 0.03)
        for value in range(16):
            arm = f"{value:04b}"
            working, semantic, episodic, procedural = (
                bit == "1" for bit in arm
            )
            probability = (
                0.18
                + difficulty
                + 0.10 * working
                + (0.20 + heterogeneous) * semantic
                + 0.00 * episodic
                + 0.15 * procedural
                + 0.25 * semantic * procedural
            )
            probability = min(0.98, max(0.02, probability))
            rows.append(
                {
                    "block_id": f"synthetic-{block:04d}",
                    "task_id": f"synthetic-{block:04d}",
                    "arm_id": arm,
                    "success": rng.random() < probability,
                    "difficulty": difficulty,
                    "retrieved_memories": (
                        sum(bit == "1" for bit in arm)
                        + int((0.08 - difficulty) * 20)
                    ),
                    "cost_usd": 0.01 + 0.002 * sum(bit == "1" for bit in arm),
                    "tokens": 500 + 150 * sum(bit == "1" for bit in arm),
                    "latency_ms": 700 + 50 * sum(bit == "1" for bit in arm),
                }
            )
    return rows


def generate_confounded_observational(
    *, observations: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for index in range(observations):
        difficulty = rng.random()
        # Harder tasks retrieve more memory, but are intrinsically less likely to pass.
        treatment_probability = 0.15 + 0.70 * difficulty
        bits = [
            rng.random() < treatment_probability,
            rng.random() < treatment_probability,
            rng.random() < treatment_probability,
            rng.random() < treatment_probability,
        ]
        probability = (
            0.62
            - 0.45 * difficulty
            + 0.10 * bits[0]
            + 0.20 * bits[1]
            + 0.15 * bits[3]
            + 0.25 * bits[1] * bits[3]
        )
        arm = "".join("1" if value else "0" for value in bits)
        rows.append(
            {
                "block_id": f"observed-{index}",
                "task_id": f"observed-{index}",
                "arm_id": arm,
                "success": rng.random() < min(0.98, max(0.02, probability)),
                "difficulty": difficulty,
                "retrieved_memories": sum(bits),
            }
        )
    return rows


def run_calibration(
    *,
    simulations: int = 500,
    blocks: int = 80,
    seed: int = 20260726,
) -> dict[str, Any]:
    if simulations < 20 or blocks < 8:
        raise ValueError("calibration requires at least 20 simulations and 8 blocks")
    tracked = list(PLANTED)
    errors = {name: [] for name in tracked}
    covered = {name: 0 for name in tracked}
    direction = {name: 0 for name in tracked if PLANTED[name] != 0}
    detected = {name: 0 for name in tracked if PLANTED[name] != 0}
    null_rejections = 0
    for simulation in range(simulations):
        estimates = estimate_primitive_effects(
            generate_randomized(blocks=blocks, seed=seed + simulation)
        )
        adjusted = {name: estimates[name] for name in tracked}
        adjusted_values = {name: item.estimate for name, item in adjusted.items()}
        for name in tracked:
            item = adjusted[name]
            value = adjusted_values[name]
            errors[name].append(abs(value - PLANTED[name]))
            if item.lower <= PLANTED[name] <= item.upper:
                covered[name] += 1
            if PLANTED[name] and math.copysign(1, value) == math.copysign(
                1, PLANTED[name]
            ):
                direction[name] += 1
            if PLANTED[name] > 0 and item.lower > 0:
                detected[name] += 1
        null = adjusted["episodic"]
        if null.lower > 0 or null.upper < 0:
            null_rejections += 1

    observational = generate_confounded_observational(
        observations=blocks * 16, seed=seed + simulations + 1
    )
    naive_semantic = _naive_difference(observational, 1)
    randomized_rows = generate_randomized(
        blocks=blocks, seed=seed + simulations + 2
    )
    randomized_example = estimate_primitive_effects(randomized_rows)
    randomized_semantic = randomized_example["semantic"].estimate
    leave_one_out_semantic = _arm_mean(
        randomized_rows, "1111"
    ) - _arm_mean(randomized_rows, "1011")
    mae = mean(value for values in errors.values() for value in values)
    minimum_direction = min(
        count / simulations for count in direction.values()
    )
    coverages = {name: count / simulations for name, count in covered.items()}
    binding_probe = _run_ledger_binding_probe(seed=str(seed))
    gates = {
        "mean_absolute_error_below_0_03": mae < 0.03,
        "direction_recovery_at_least_0_90": minimum_direction >= 0.90,
        "coverage_between_0_90_and_0_99": all(
            0.90 <= value <= 0.99 for value in coverages.values()
        ),
        "null_false_positive_at_most_0_10": (
            null_rejections / simulations <= 0.10
        ),
        "randomized_semantic_closer_than_naive": abs(
            randomized_semantic - PLANTED["semantic"]
        )
        < abs(naive_semantic - PLANTED["semantic"]),
        "runtime_ledger_binding_probe": binding_probe["passed"],
    }
    return {
        "format": "aetnamem-memory-impact-synthetic-calibration-v1",
        "simulations": simulations,
        "blocks_per_simulation": blocks,
        "planted_risk_differences": PLANTED,
        "mean_absolute_error": mae,
        "direction_recovery": {
            name: count / simulations for name, count in direction.items()
        },
        "empirical_detection_power": {
            name: count / simulations for name, count in detected.items()
        },
        "coverage": coverages,
        "null_false_positive_rate": null_rejections / simulations,
        "confounding_demonstration": {
            "naive_observational_semantic": naive_semantic,
            "outcome_weighting_without_randomization_semantic": naive_semantic,
            "leave_one_plane_out_from_1111_semantic": leave_one_out_semantic,
            "randomized_semantic": randomized_semantic,
            "target": PLANTED["semantic"],
        },
        "runtime_ledger_binding_probe": binding_probe,
        "gates": gates,
        "passed": all(gates.values()),
    }


def _run_ledger_binding_probe(*, seed: str) -> dict[str, Any]:
    allocator = BalancedFactorialAllocator(
        experiment_id="synthetic-ledger-probe", seed=seed
    )
    assignments = allocator.schedule(["synthetic-binding"])
    candidates_by_plane: dict[str, set[str]] = {
        plane: set()
        for plane in ("working", "semantic", "episodic", "procedural")
    }
    arms = set()
    manifests = set()
    with tempfile.TemporaryDirectory(prefix="aetnamem-impact-") as directory:
        for assignment in assignments:
            config = preset_config(
                "benchmark",
                db_path=str(Path(directory) / f"{assignment.run_id}.db"),
                subject_id="synthetic-subject",
                agent_id="synthetic-agent",
            )
            config["learning_enabled"] = False
            config["cml"] = {
                "mode": "experiment",
                "experiment_id": assignment.experiment_id,
                "design": "balanced-factorial",
                "policy_version": "synthetic-probe-v1",
                "eligible_planes": [
                    "working",
                    "semantic",
                    "episodic",
                    "procedural",
                ],
                "pinned_planes": [],
                "seed": seed,
                "assigned_arm": assignment.arm_id,
                "block_id": assignment.block_id,
                "task_id": assignment.task_id,
                "repetition": assignment.repetition,
                "assignment_index": assignment.assignment_index,
                "assignment_token": assignment.assignment_token,
                "schedule_sha256": assignment.schedule_sha256,
                "assignment_probability": 1 / 16,
                "require_full_exposure": True,
                "require_nonempty_candidates": True,
                "candidate_identity": "content-envelope-v1",
            }
            providers = {
                plane: _SyntheticProvider(plane)
                for plane in ("working", "semantic", "episodic", "procedural")
            }
            runtime = MemoryRuntime(config, providers=providers)
            try:
                pack = runtime.prepare_turn(
                    "synthetic registered task",
                    scope=RuntimeScope(
                        subject_id="synthetic-subject",
                        agent_id="synthetic-agent",
                        task_id="synthetic-binding",
                        run_id=assignment.run_id,
                    ),
                )
                runtime.record_outcome(
                    assignment.run_id,
                    success=assignment.arm_id in {"1111", "0101"},
                    manifest_sha256=pack["manifest_sha256"],
                    metrics={"synthetic": True},
                )
                stored = runtime.store.interventions_for_run(assignment.run_id)
                for item in stored:
                    candidates_by_plane[item["plane"]].add(
                        item["candidate_sha256"]
                    )
                arms.add(pack["cml"]["arm_id"])
                manifests.add(pack["manifest_sha256"])
                if any(
                    not item["fully_exposed"]
                    for item in pack["manifest"]["exposure"]
                ):
                    raise AssertionError("synthetic probe exposure was truncated")
            finally:
                runtime.close()
    checks = {
        "all_16_arms": len(arms) == 16,
        "candidate_identity_stable": all(
            len(values) == 1 for values in candidates_by_plane.values()
        ),
        "unique_bound_manifests": len(manifests) == 16,
    }
    return {"passed": all(checks.values()), "checks": checks}


class _SyntheticProvider:
    def __init__(self, plane: str) -> None:
        self.plane = plane

    def prepare(self, request: Any) -> PlaneContribution:
        placement = (
            "stable_system_prefix"
            if self.plane in {"semantic", "procedural"}
            else "current_turn_tail"
        )
        return PlaneContribution(
            plane=self.plane,
            content=f"<{self.plane}_memory>registered synthetic contribution</{self.plane}_memory>",
            metadata={"synthetic": True},
            placement=placement,
            trust="synthetic_registered",
        )

    def record_outcome(self, outcome: Any) -> list[dict[str, Any]]:
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.plane, True)


def write_calibration(path: str | Path, result: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _naive_difference(rows: list[dict[str, Any]], index: int) -> float:
    treated = [float(row["success"]) for row in rows if row["arm_id"][index] == "1"]
    control = [float(row["success"]) for row in rows if row["arm_id"][index] == "0"]
    return mean(treated) - mean(control)


def _arm_mean(rows: list[dict[str, Any]], arm_id: str) -> float:
    return mean(
        float(row["success"]) for row in rows if row["arm_id"] == arm_id
    )
