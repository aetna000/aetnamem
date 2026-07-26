from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex


@dataclass(frozen=True)
class ImpactTask:
    source_path: Path
    raw: dict[str, Any]

    @property
    def task_id(self) -> str:
        return str(self.raw["task_id"])

    @property
    def family(self) -> str:
        return str(self.raw["family"])

    @property
    def split(self) -> str:
        return str(self.raw["split"])

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.raw))

    def resolve(self, value: str) -> Path:
        return (self.source_path.parent / value).resolve()


def load_task(path: str | Path) -> ImpactTask:
    source = Path(path).resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"impact task must be an object: {source}")
    required = {
        "format",
        "task_id",
        "family",
        "split",
        "query",
        "task_state",
        "snapshot",
        "workspace",
        "verifier",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError(f"impact task missing {', '.join(missing)}: {source}")
    if value["format"] != "aetnamem-memory-impact-task-v1":
        raise ValueError(f"unsupported impact task format: {source}")
    if value["split"] not in {"train", "validation", "held-out"}:
        raise ValueError(f"task split must be train, validation, or held-out: {source}")
    if not isinstance(value["task_state"], dict):
        raise ValueError(f"task_state must be an object: {source}")
    baseline_arms = value.get("baseline_arms") or {}
    if not isinstance(baseline_arms, dict):
        raise ValueError(f"baseline_arms must be an object: {source}")
    for name, arm in baseline_arms.items():
        if len(str(arm)) != 4 or any(bit not in "01" for bit in str(arm)):
            raise ValueError(f"baseline arm {name!r} must be four binary digits")
    for field in ("snapshot", "workspace", "verifier"):
        if not (source.parent / str(value[field])).resolve().exists():
            raise ValueError(f"task {field} does not exist: {value[field]}")
    return ImpactTask(source, value)
