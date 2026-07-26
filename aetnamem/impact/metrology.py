from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex


def inspect_cli(
    command: str,
    *,
    model: str,
    arguments: list[str],
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        return {
            "format": "aetnamem-impact-metrology-v1",
            "available": False,
            "command": command,
            "model": model,
            "arguments": arguments,
            "telemetry_trust": "unavailable",
        }
    path = Path(executable).resolve()
    version = _capture([str(path), "--version"])
    help_text = _capture([str(path), "--help"])
    config_output = _capture(
        [
            str(path),
            *(["--cwd", str(Path(cwd).resolve())] if cwd is not None else []),
            "inspect",
            "--json",
        ]
    )
    models_output = _capture([str(path), "models"])
    value = {
        "format": "aetnamem-impact-metrology-v1",
        "available": True,
        "command": command,
        "executable": str(path),
        "executable_sha256": _file_sha256(path),
        "version_output": version,
        "discovered_config_sha256": sha256_hex(config_output),
        "model": model,
        "model_advertised": model in models_output,
        "models_output_sha256": sha256_hex(models_output),
        "arguments": arguments,
        "controls": {
            argument: argument in help_text
            for argument in arguments
            if argument.startswith("--")
        },
        "telemetry_trust": "must-be-confirmed-by-controller",
    }
    value["metrology_sha256"] = sha256_hex(canonical_json(value))
    return value


def write_metrology(path: str | Path, value: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _capture(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {type(exc).__name__}"
    return result.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
