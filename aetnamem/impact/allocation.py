from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import random
from typing import Any, Iterable

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.runtime.models import PLANE_NAMES


ARMS = tuple(f"{value:04b}" for value in range(16))


@dataclass(frozen=True)
class ScheduledAssignment:
    experiment_id: str
    block_id: str
    task_id: str
    repetition: int
    assignment_index: int
    run_id: str
    arm_id: str
    assignment_probability: float
    seed_commitment: str
    schedule_sha256: str
    assignment_token: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BalancedFactorialAllocator:
    """Precommit one randomized permutation of all 16 arms per task block."""

    def __init__(self, *, experiment_id: str, seed: str) -> None:
        if not experiment_id.strip() or not seed:
            raise ValueError("allocator requires experiment_id and a non-empty seed")
        self.experiment_id = experiment_id
        self._seed = seed
        self.seed_commitment = sha256_hex(seed)

    def schedule(
        self, task_ids: Iterable[str], *, repetitions: int = 1
    ) -> list[ScheduledAssignment]:
        if repetitions <= 0:
            raise ValueError("repetitions must be positive")
        provisional: list[dict[str, Any]] = []
        for task_id in task_ids:
            if not str(task_id).strip():
                raise ValueError("task IDs must be non-empty")
            for repetition in range(repetitions):
                block_id = f"{task_id}:r{repetition + 1}"
                arms = list(ARMS)
                random.Random(self._block_seed(block_id)).shuffle(arms)
                for index, arm_id in enumerate(arms):
                    run_material = {
                        "experiment_id": self.experiment_id,
                        "block_id": block_id,
                        "assignment_index": index,
                    }
                    provisional.append(
                        {
                            **run_material,
                            "task_id": str(task_id),
                            "repetition": repetition + 1,
                            "run_id": "impact_" + sha256_hex(
                                canonical_json(run_material)
                            )[:32],
                            "arm_id": arm_id,
                            "assignment_probability": 1.0 / 16.0,
                            "seed_commitment": self.seed_commitment,
                        }
                    )
        public_schedule = {
            "format": "aetnamem-balanced-factorial-schedule-v1",
            "experiment_id": self.experiment_id,
            "seed_commitment": self.seed_commitment,
            "assignments": provisional,
        }
        schedule_sha256 = sha256_hex(canonical_json(public_schedule))
        return [
            ScheduledAssignment(
                **item,
                schedule_sha256=schedule_sha256,
                assignment_token=self._token(item, schedule_sha256),
            )
            for item in provisional
        ]

    def verify(
        self, assignments: Iterable[ScheduledAssignment | dict[str, Any]]
    ) -> bool:
        values = [
            item.to_dict() if isinstance(item, ScheduledAssignment) else dict(item)
            for item in assignments
        ]
        if not values:
            return False
        expected = self.schedule(
            dict.fromkeys(str(item["task_id"]) for item in values),
            repetitions=max(int(item["repetition"]) for item in values),
        )
        expected_by_run = {item.run_id: item.to_dict() for item in expected}
        return len(values) == len(expected) and all(
            expected_by_run.get(str(item["run_id"])) == item for item in values
        )

    def _block_seed(self, block_id: str) -> int:
        digest = hmac.new(
            self._seed.encode(),
            canonical_json(
                {"experiment_id": self.experiment_id, "block_id": block_id}
            ).encode(),
            hashlib.sha256,
        ).digest()
        return int.from_bytes(digest, "big")

    def _token(self, item: dict[str, Any], schedule_sha256: str) -> str:
        return hmac.new(
            self._seed.encode(),
            canonical_json({**item, "schedule_sha256": schedule_sha256}).encode(),
            hashlib.sha256,
        ).hexdigest()


def arm_planes(arm_id: str) -> dict[str, bool]:
    if len(arm_id) != 4 or any(value not in "01" for value in arm_id):
        raise ValueError("arm_id must contain exactly four binary digits")
    return {
        plane: value == "1"
        for plane, value in zip(PLANE_NAMES, arm_id, strict=True)
    }


def verify_assignment_token(
    *,
    seed: str,
    experiment_id: str,
    task_id: str,
    block_id: str,
    repetition: int,
    assignment_index: int,
    run_id: str,
    arm_id: str,
    assignment_probability: float,
    seed_commitment: str,
    schedule_sha256: str,
    assignment_token: str,
) -> bool:
    item = {
        "experiment_id": experiment_id,
        "block_id": block_id,
        "assignment_index": assignment_index,
        "task_id": task_id,
        "repetition": repetition,
        "run_id": run_id,
        "arm_id": arm_id,
        "assignment_probability": assignment_probability,
        "seed_commitment": seed_commitment,
    }
    expected = hmac.new(
        seed.encode(),
        canonical_json({**item, "schedule_sha256": schedule_sha256}).encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, assignment_token)
