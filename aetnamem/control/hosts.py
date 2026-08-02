from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.control.models import ControlState
from aetnamem.control.store import ControlStore


def configure_host(
    state: ControlState,
    state_path: str | Path,
    *,
    aetnamem_executable: str | None = None,
) -> dict[str, Any]:
    if state.host != "openclaw":
        raise ValueError(f"unsupported control-plane host: {state.host}")
    return _configure_openclaw(
        state,
        state_path,
        aetnamem_executable=aetnamem_executable,
    )


def restore_host(state: ControlState) -> dict[str, Any]:
    store = ControlStore(Path(state.control_dir) / "evidence.db")
    try:
        snapshot = store.latest_snapshot(state.migration_id)
    finally:
        store.close()
    if snapshot is None:
        raise ValueError("migration has no verified host snapshot to restore")
    metadata = json.loads(str(snapshot["metadata_json"]))
    if state.host != "openclaw":
        raise ValueError(f"unsupported control-plane host: {state.host}")
    return _restore_openclaw(metadata)


def _configure_openclaw(
    state: ControlState,
    state_path: str | Path,
    *,
    aetnamem_executable: str | None = None,
) -> dict[str, Any]:
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError(
            "OpenClaw was not found on PATH. Install/start it, or use "
            "`aetnamem control shadow --host openclaw --no-configure` only for testing."
        )
    aetnamem_executable = aetnamem_executable or shutil.which("aetnamem")
    if aetnamem_executable is None:
        raise ValueError("the aetnamem executable is not on PATH")
    plugin_info = _run_json(
        [
            executable,
            "plugins",
            "inspect",
            "memory-aetnamem",
            "--json",
        ]
    )
    plugin_version = _find_plugin_version(plugin_info)
    if plugin_version is None or _version_tuple(plugin_version) < (1, 0, 0):
        raise ValueError(
            "The AetnaMem control plane requires openclaw-memory-aetnamem "
            "1.0.0-experimental.3 or newer. "
            "Run `aetnamem openclaw install`; it installs and verifies the "
            "matching bridge before starting the migration."
        )
    prior = _run_optional_json(
        [executable, "config", "get", "plugins.entries.memory-aetnamem", "--json"]
    )
    metadata = {
        "format": "aetnamem-openclaw-snapshot-v1",
        "present": prior is not None,
        "entry": prior,
        "entry_sha256": sha256_hex(canonical_json(prior)) if prior is not None else None,
    }
    backup_path = Path(state.control_dir) / "openclaw-restore.json"
    _private_json(backup_path, metadata)
    control_plane = {
        "enabled": True,
        "statePath": str(Path(state_path).expanduser().resolve(strict=False)),
    }
    # Route an already-enabled plugin through the fail-closed migration server
    # before touching hook permission. Enable is deliberately the final write.
    writes = [
        (
            "plugins.entries.memory-aetnamem.config.controlPlane",
            control_plane,
        ),
        (
            "plugins.entries.memory-aetnamem.config.command",
            str(Path(aetnamem_executable).resolve()),
        ),
        (
            "plugins.entries.memory-aetnamem.hooks.allowConversationAccess",
            True,
        ),
        ("plugins.entries.memory-aetnamem.enabled", True),
    ]
    try:
        for key, value in writes:
            _run(
                [
                    executable,
                    "config",
                    "set",
                    key,
                    json.dumps(value, separators=(",", ":")),
                    "--strict-json",
                ]
            )
        observed = _run_json(
            [
                executable,
                "config",
                "get",
                "plugins.entries.memory-aetnamem.config.controlPlane",
                "--json",
            ]
        )
        if observed != control_plane:
            raise ValueError("OpenClaw did not retain the control-plane configuration")
    except Exception:
        _restore_openclaw(metadata)
        raise
    store = ControlStore(Path(state.control_dir) / "evidence.db")
    try:
        store.add_host_snapshot(
            state.migration_id,
            host="openclaw",
            config_path=None,
            config_sha256=metadata["entry_sha256"],
            backup_path=str(backup_path),
            metadata=metadata,
        )
    finally:
        store.close()
    return {
        "host": "openclaw",
        "configured": True,
        "snapshot": str(backup_path),
        "hot_reload_expected": True,
        "native_memory_changed": False,
    }


def _restore_openclaw(metadata: dict[str, Any]) -> dict[str, Any]:
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError("OpenClaw is not on PATH; saved snapshot was not restored")
    key = "plugins.entries.memory-aetnamem"
    if metadata.get("present"):
        _run(
            [
                executable,
                "config",
                "set",
                key,
                json.dumps(metadata["entry"], separators=(",", ":")),
                "--strict-json",
            ]
        )
        restored = _run_json([executable, "config", "get", key, "--json"])
        expected_sha = str(metadata["entry_sha256"])
        if sha256_hex(canonical_json(restored)) != expected_sha:
            raise ValueError("OpenClaw restore verification failed")
        entry = restored if isinstance(restored, dict) else {}
    else:
        _run([executable, "config", "unset", key])
        if _run_optional_json([executable, "config", "get", key, "--json"]) is not None:
            raise ValueError("OpenClaw restore verification failed")
        entry = {}
    config = entry.get("config")
    config = config if isinstance(config, dict) else {}
    control_plane = config.get("controlPlane")
    control_plane = control_plane if isinstance(control_plane, dict) else {}
    return {
        "host": "openclaw",
        "restored": True,
        "verified": True,
        "plugin_present": bool(metadata.get("present")),
        "plugin_enabled": bool(entry.get("enabled")),
        "control_plane_enabled": bool(control_plane.get("enabled")),
    }


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"{' '.join(arguments[:3])} failed: {detail}")
    return result


def _run_json(arguments: list[str]) -> Any:
    result = _run(arguments)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{' '.join(arguments[:3])} did not return JSON") from exc


def _run_optional_json(arguments: list[str]) -> Any | None:
    result = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        normalized = detail.casefold()
        if any(
            phrase in normalized
            for phrase in ("not found", "missing", "unknown config path", "no value")
        ):
            return None
        raise ValueError(f"{' '.join(arguments[:3])} failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{' '.join(arguments[:3])} did not return JSON") from exc


def _private_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _find_plugin_version(value: Any) -> str | None:
    if isinstance(value, dict):
        identity = " ".join(
            str(value.get(key) or "")
            for key in ("id", "name", "package", "packageName")
        ).casefold()
        version = value.get("version")
        if "aetnamem" in identity and isinstance(version, str):
            return version
        for child in value.values():
            found = _find_plugin_version(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_plugin_version(child)
            if found is not None:
                return found
    return None


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.lstrip("v").split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)
