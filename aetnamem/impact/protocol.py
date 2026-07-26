from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.runtime.models import PLANE_NAMES


PROTOCOL_FORMAT = "aetnamem-memory-impact-protocol-v1"


@dataclass(frozen=True)
class ImpactProtocol:
    raw: dict[str, Any]

    @property
    def experiment_id(self) -> str:
        return str(self.raw["experiment_id"])

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.raw))

    @property
    def seed_commitment(self) -> str:
        return sha256_hex(str(self.raw["randomization"]["seed"]))

    @property
    def task_files(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.raw["tasks"])

    @property
    def repetitions(self) -> int:
        return int(self.raw["design"].get("repetitions", 1))

    @property
    def results_dir(self) -> str:
        return str(self.raw.get("results_dir", "results"))

    def public_registration(self) -> dict[str, Any]:
        value = json.loads(canonical_json(self.raw))
        value["randomization"] = {
            key: item
            for key, item in value["randomization"].items()
            if key != "seed"
        }
        value["randomization"]["seed_commitment"] = self.seed_commitment
        value["protocol_sha256"] = self.digest
        return value


def load_protocol(path: str | Path) -> ImpactProtocol:
    protocol_path = Path(path)
    text = protocol_path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError(
                "protocol must use JSON-compatible YAML, or install PyYAML"
            ) from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("impact protocol must be an object")
    validate_protocol(value, base_dir=protocol_path.parent)
    return ImpactProtocol(value)


def validate_protocol(value: dict[str, Any], *, base_dir: Path | None = None) -> None:
    if value.get("format") != PROTOCOL_FORMAT:
        raise ValueError(f"protocol format must be {PROTOCOL_FORMAT!r}")
    if not str(value.get("experiment_id") or "").strip():
        raise ValueError("protocol requires experiment_id")
    design = value.get("design")
    if not isinstance(design, dict) or design.get("kind") != "balanced-2x2x2x2":
        raise ValueError("protocol design.kind must be 'balanced-2x2x2x2'")
    planes = tuple(design.get("planes") or ())
    if planes != PLANE_NAMES:
        raise ValueError(
            "protocol planes must be working, semantic, episodic, procedural in order"
        )
    if int(design.get("repetitions", 1)) <= 0:
        raise ValueError("protocol repetitions must be positive")
    randomization = value.get("randomization")
    if not isinstance(randomization, dict) or not str(
        randomization.get("seed") or ""
    ):
        raise ValueError("protocol requires a non-empty randomization.seed")
    if randomization.get("reveal") not in {"after-close", "immediate-test-only"}:
        raise ValueError("randomization.reveal must be after-close or immediate-test-only")
    budgets = value.get("budgets")
    if not isinstance(budgets, dict):
        raise ValueError("protocol requires budgets")
    for key in ("max_context_chars", "max_turns", "timeout_seconds"):
        if int(budgets.get(key, 0)) <= 0:
            raise ValueError(f"protocol budgets.{key} must be positive")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("protocol requires at least one task file")
    if base_dir is not None:
        missing = [
            item for item in tasks if not (base_dir / str(item)).resolve().is_file()
        ]
        if missing:
            raise ValueError(f"protocol task files do not exist: {', '.join(missing)}")
    model = value.get("model")
    if not isinstance(model, dict) or not str(model.get("command") or ""):
        raise ValueError("protocol requires model.command")
    verifier = value.get("verifier")
    if not isinstance(verifier, dict) or verifier.get("trust") != "host":
        raise ValueError("protocol verifier.trust must be 'host'")
    if bool(value.get("learning_enabled", False)):
        raise ValueError("registered impact experiments must disable runtime learning")


def default_protocol() -> dict[str, Any]:
    return {
        "format": PROTOCOL_FORMAT,
        "experiment_id": "memory-impact-v1",
        "replication_of": None,
        "design": {
            "kind": "balanced-2x2x2x2",
            "planes": list(PLANE_NAMES),
            "repetitions": 1,
            "primary_estimand": "intention-to-treat",
            "primary_interactions": ["semantic:procedural"],
        },
        "randomization": {
            "seed": "replace-before-registration",
            "reveal": "after-close",
        },
        "budgets": {
            "max_context_chars": 10000,
            "max_turns": 8,
            "timeout_seconds": 180,
            "max_cost_usd": 1.0,
        },
        "model": {
            "command": "grok",
            "name": "grok-4.5",
            "arguments": [
                "--no-memory",
                "--disable-web-search",
                "--no-subagents",
                "--sandbox",
                "strict",
                "--tools",
                "read_file,grep,list_dir,search_replace",
                "--permission-mode",
                "bypassPermissions",
                "--output-format",
                "json",
                "--verbatim",
                "--no-plan",
            ],
            "telemetry": "provider-reported-or-explicitly-estimated",
        },
        "verifier": {
            "trust": "host",
            "command": "python verify_outcome.py",
            "blind_to_arm": True,
        },
        "tasks": ["tasks/example.json"],
        "learning_enabled": False,
        "results_dir": "results",
    }
