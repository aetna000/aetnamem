from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from aetnamem.runtime.models import PLANE_NAMES


CONFIG_FORMAT = "aetnamem-runtime-config-v1"
CML_MODES = ("off", "shadow", "experiment")
CML_DESIGNS = ("bernoulli", "balanced-factorial")


def _cml_defaults() -> dict[str, Any]:
    return {
        "mode": "off",
        "design": "bernoulli",
        "policy_version": "cml-policy-v1",
        "assignment_probability": 0.5,
        "eligible_planes": [],
        "pinned_planes": [],
    }

PRESETS: dict[str, dict[str, Any]] = {
    "starter": {
        "description": "Safe local defaults for one person and one agent.",
        "budgets": {
            "total_chars": 4200,
            "working_chars": 700,
            "semantic_chars": 1800,
            "episodic_chars": 900,
            "procedural_chars": 800,
        },
        "planes": {
            "working": {"enabled": True},
            "semantic": {"enabled": True, "max_records": 3, "min_score": 0.3},
            "episodic": {"enabled": True, "max_outcomes": 3},
            "procedural": {"enabled": True, "skill_paths": []},
        },
        "failure_policy": "degrade",
        "cml": _cml_defaults(),
    },
    "private": {
        "description": "Local-only, conservative retention and small context.",
        "budgets": {
            "total_chars": 3000,
            "working_chars": 600,
            "semantic_chars": 1200,
            "episodic_chars": 600,
            "procedural_chars": 600,
        },
        "planes": {
            "working": {"enabled": True},
            "semantic": {"enabled": True, "max_records": 2, "min_score": 0.4},
            "episodic": {"enabled": True, "max_outcomes": 2},
            "procedural": {"enabled": True, "skill_paths": []},
        },
        "failure_policy": "degrade",
        "cml": _cml_defaults(),
    },
    "team": {
        "description": "Larger context and team-scoped learning for collaborating agents.",
        "budgets": {
            "total_chars": 7000,
            "working_chars": 1000,
            "semantic_chars": 2800,
            "episodic_chars": 1600,
            "procedural_chars": 1600,
        },
        "planes": {
            "working": {"enabled": True},
            "semantic": {"enabled": True, "max_records": 6, "min_score": 0.25},
            "episodic": {"enabled": True, "max_outcomes": 5, "share": "team"},
            "procedural": {"enabled": True, "skill_paths": []},
        },
        "failure_policy": "degrade",
        "cml": _cml_defaults(),
    },
    "benchmark": {
        "description": "Deterministic generous budgets for four-plane comparisons.",
        "budgets": {
            "total_chars": 10000,
            "working_chars": 1600,
            "semantic_chars": 3600,
            "episodic_chars": 2400,
            "procedural_chars": 2400,
        },
        "planes": {
            "working": {"enabled": True},
            "semantic": {"enabled": True, "max_records": 8, "min_score": 0.2},
            "episodic": {"enabled": True, "max_outcomes": 8},
            "procedural": {"enabled": True, "skill_paths": []},
        },
        "failure_policy": "degrade",
        "cml": _cml_defaults(),
    },
}


def preset_config(
    name: str,
    *,
    db_path: str,
    subject_id: str,
    agent_id: str = "default-agent",
    skill_paths: list[str] | None = None,
) -> dict[str, Any]:
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose: {', '.join(PRESETS)}")
    config = deepcopy(PRESETS[name])
    config.update(
        {
            "format": CONFIG_FORMAT,
            "preset": name,
            "db_path": db_path,
            "scope": {"subject_id": subject_id, "agent_id": agent_id},
        }
    )
    if skill_paths:
        config["planes"]["procedural"]["skill_paths"] = list(skill_paths)
    return config


def load_config(path_or_config: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(path_or_config, dict):
        config = deepcopy(path_or_config)
    else:
        config = json.loads(Path(path_or_config).read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if config.get("format") != CONFIG_FORMAT:
        raise ValueError(f"runtime config format must be {CONFIG_FORMAT!r}")
    if not str(config.get("db_path") or "").strip():
        raise ValueError("runtime config requires db_path")
    scope = config.get("scope")
    if not isinstance(scope, dict) or not str(scope.get("subject_id") or "").strip():
        raise ValueError("runtime config requires scope.subject_id")
    planes = config.get("planes")
    if not isinstance(planes, dict):
        raise ValueError("runtime config requires planes")
    unknown = set(planes) - set(PLANE_NAMES)
    if unknown:
        raise ValueError(f"unknown memory planes: {', '.join(sorted(unknown))}")
    for plane, settings in planes.items():
        if not isinstance(settings, dict):
            raise ValueError(f"plane {plane!r} configuration must be an object")
        provider = str(settings.get("provider", "embedded"))
        if provider != "embedded":
            raise ValueError(
                f"config provider {provider!r} is not built in; "
                "supply a host adapter through MemoryRuntime(providers=...)"
            )
    budgets = config.get("budgets")
    if not isinstance(budgets, dict) or int(budgets.get("total_chars", 0)) <= 0:
        raise ValueError("runtime config requires a positive budgets.total_chars")
    _validate_cml(
        config.get("cml", {"mode": "off"}),
        preset=str(config.get("preset", "custom")),
    )


def _validate_cml(value: Any, *, preset: str) -> None:
    if not isinstance(value, dict):
        raise ValueError("runtime config cml must be an object")
    mode = str(value.get("mode", "off"))
    if mode not in CML_MODES:
        raise ValueError(f"cml.mode must be one of: {', '.join(CML_MODES)}")
    design = str(value.get("design", "bernoulli"))
    if design not in CML_DESIGNS:
        raise ValueError(f"cml.design must be one of: {', '.join(CML_DESIGNS)}")
    probability = float(value.get("assignment_probability", 0.5))
    if not 0.0 <= probability <= 1.0:
        raise ValueError("cml.assignment_probability must be between 0 and 1")
    if mode == "experiment" and not 0.0 < probability < 1.0:
        raise ValueError(
            "cml experiment mode requires assignment_probability strictly between 0 and 1"
        )
    eligible = value.get("eligible_planes", [])
    pinned = value.get("pinned_planes", [])
    if design == "balanced-factorial":
        required = (
            "assigned_arm",
            "block_id",
            "task_id",
            "repetition",
            "assignment_index",
            "assignment_token",
            "schedule_sha256",
        )
        missing = [key for key in required if value.get(key) in {None, ""}]
        if missing:
            raise ValueError(
                "balanced-factorial cml requires " + ", ".join(missing)
            )
        arm = str(value["assigned_arm"])
        if len(arm) != 4 or any(bit not in "01" for bit in arm):
            raise ValueError("balanced-factorial assigned_arm must be four binary digits")
        if set(eligible) != set(PLANE_NAMES) or pinned:
            raise ValueError(
                "balanced-factorial requires all four eligible planes and no pinned planes; "
                "safety, identity, and authorization belong outside supplemental memory"
            )
        if float(value.get("assignment_probability", 0.0)) != 1.0 / 16.0:
            raise ValueError(
                "balanced-factorial assignment_probability must be exactly 1/16"
            )
    if not isinstance(eligible, list) or not isinstance(pinned, list):
        raise ValueError("cml eligible_planes and pinned_planes must be arrays")
    unknown = (set(eligible) | set(pinned)) - set(PLANE_NAMES)
    if unknown:
        raise ValueError(f"unknown cml memory planes: {', '.join(sorted(unknown))}")
    overlap = set(eligible) & set(pinned)
    if overlap:
        raise ValueError(
            f"cml planes cannot be both eligible and pinned: {', '.join(sorted(overlap))}"
        )
    if mode in {"shadow", "experiment"}:
        if not str(value.get("experiment_id") or "").strip():
            raise ValueError(f"cml {mode} mode requires experiment_id")
        if not str(value.get("seed") or ""):
            raise ValueError(f"cml {mode} mode requires a non-empty seed")
        if not eligible:
            raise ValueError(f"cml {mode} mode requires eligible_planes")
    if mode == "experiment" and preset != "benchmark":
        raise ValueError(
            "cml experiment mode is restricted to the benchmark preset; "
            "use shadow mode to observe assignments without withholding memory"
        )


def list_presets() -> list[dict[str, str]]:
    return [
        {"name": name, "description": str(value["description"])}
        for name, value in PRESETS.items()
    ]
