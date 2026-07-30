from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.trial.models import TrialState
from aetnamem.trial.store import TrialStore


def configure_host(
    state: TrialState,
    state_path: str | Path,
    *,
    aetnamem_executable: str | None = None,
) -> dict[str, Any]:
    if state.host == "openclaw":
        return _configure_openclaw(
            state,
            state_path,
            aetnamem_executable=aetnamem_executable,
        )
    if state.host == "hermes":
        return _configure_hermes(state, state_path)
    raise ValueError(f"unsupported trial host: {state.host}")


def restore_host(state: TrialState) -> dict[str, Any]:
    store = TrialStore(Path(state.trial_dir) / "evidence.db")
    try:
        snapshot = store.latest_snapshot(state.trial_id)
    finally:
        store.close()
    if snapshot is None:
        raise ValueError("trial has no verified host snapshot to restore")
    metadata = json.loads(str(snapshot["metadata_json"]))
    if state.host == "openclaw":
        return _restore_openclaw(metadata)
    if state.host == "hermes":
        return _restore_hermes(metadata)
    raise ValueError(f"unsupported trial host: {state.host}")


def _configure_openclaw(
    state: TrialState,
    state_path: str | Path,
    *,
    aetnamem_executable: str | None = None,
) -> dict[str, Any]:
    executable = shutil.which("openclaw")
    if executable is None:
        raise ValueError(
            "OpenClaw was not found on PATH. Install/start it, or use "
            "`aetnamem trial start --host openclaw --no-configure` only for testing."
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
    if plugin_version is None or _version_tuple(plugin_version) < (0, 4, 1):
        raise ValueError(
            "Safe Switch requires openclaw-memory-aetnamem "
            "0.4.1-experimental.3 or newer. "
            "Run `aetnamem openclaw install`; it installs and verifies the "
            "matching bridge before starting the trial."
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
    backup_path = Path(state.trial_dir) / "openclaw-rollback.json"
    _private_json(backup_path, metadata)
    safe_switch = {
        "enabled": True,
        "statePath": str(Path(state_path).expanduser().resolve(strict=False)),
    }
    # Route an already-enabled plugin through the fail-closed trial server
    # before touching hook permission. Enable is deliberately the final write.
    writes = [
        (
            "plugins.entries.memory-aetnamem.config.safeSwitch",
            safe_switch,
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
                "plugins.entries.memory-aetnamem.config.safeSwitch",
                "--json",
            ]
        )
        if observed != safe_switch:
            raise ValueError("OpenClaw did not retain the Safe Switch configuration")
    except Exception:
        _restore_openclaw(metadata)
        raise
    store = TrialStore(Path(state.trial_dir) / "evidence.db")
    try:
        store.add_host_snapshot(
            state.trial_id,
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
            raise ValueError("OpenClaw rollback verification failed")
        entry = restored if isinstance(restored, dict) else {}
    else:
        _run([executable, "config", "unset", key])
        if _run_optional_json([executable, "config", "get", key, "--json"]) is not None:
            raise ValueError("OpenClaw rollback verification failed")
        entry = {}
    config = entry.get("config")
    config = config if isinstance(config, dict) else {}
    safe_switch = config.get("safeSwitch")
    safe_switch = safe_switch if isinstance(safe_switch, dict) else {}
    return {
        "host": "openclaw",
        "restored": True,
        "verified": True,
        "plugin_present": bool(metadata.get("present")),
        "plugin_enabled": bool(entry.get("enabled")),
        "safe_switch_enabled": bool(safe_switch.get("enabled")),
    }


def _configure_hermes(
    state: TrialState, state_path: str | Path
) -> dict[str, Any]:
    if shutil.which("hermes") is None:
        raise ValueError(
            "Hermes was not found on PATH. Install/start it, or use "
            "`aetnamem trial start --host hermes --no-configure` only for testing."
        )
    plugin_dir = Path.home() / ".hermes" / "plugins" / "aetnamem-safe-switch"
    backup_dir = Path(state.trial_dir) / "hermes-plugin-backup"
    existed = plugin_dir.exists()
    if existed:
        if plugin_dir.is_symlink() or not plugin_dir.is_dir():
            raise ValueError("existing Hermes AetnaMem plugin path is not a directory")
        shutil.copytree(plugin_dir, backup_dir)
    plugin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    aetnamem_executable = shutil.which("aetnamem")
    if aetnamem_executable is None:
        raise ValueError("the aetnamem executable is not on PATH")
    manifest = (
        "name: aetnamem-safe-switch\n"
        'version: "0.1.0"\n'
        "description: Reversible AetnaMem Safe Switch hooks\n"
    )
    loader = Path(__file__).with_name("hermes_standalone.py").read_text(
        encoding="utf-8"
    )
    (plugin_dir / "plugin.yaml").write_text(manifest, encoding="utf-8")
    (plugin_dir / "__init__.py").write_text(loader, encoding="utf-8")
    config_file = plugin_dir / ".aetnamem-config.json"
    config_file.write_text(
        json.dumps(
            {
                "command": str(Path(aetnamem_executable).resolve()),
                "state_path": str(
                    Path(state_path).expanduser().resolve(strict=False)
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(config_file, 0o600)
    metadata = {
        "format": "aetnamem-hermes-snapshot-v1",
        "plugin_dir": str(plugin_dir),
        "present": existed,
        "backup_dir": str(backup_dir) if existed else None,
    }
    backup_path = Path(state.trial_dir) / "hermes-rollback.json"
    _private_json(backup_path, metadata)
    store = TrialStore(Path(state.trial_dir) / "evidence.db")
    try:
        store.add_host_snapshot(
            state.trial_id,
            host="hermes",
            config_path=str(plugin_dir),
            config_sha256=None,
            backup_path=str(backup_path),
            metadata=metadata,
        )
    finally:
        store.close()
    return {
        "host": "hermes",
        "configured": True,
        "snapshot": str(backup_path),
        "restart_required": True,
        "native_memory_changed": False,
        "transport": "private-stdio-subprocess",
    }


def _restore_hermes(metadata: dict[str, Any]) -> dict[str, Any]:
    plugin_dir = Path(str(metadata["plugin_dir"])).expanduser()
    expected = Path.home() / ".hermes" / "plugins" / "aetnamem-safe-switch"
    if plugin_dir.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("refusing to restore an unexpected Hermes plugin path")
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
    if metadata.get("present"):
        backup_dir = Path(str(metadata["backup_dir"]))
        if not backup_dir.is_dir():
            raise ValueError("Hermes plugin backup is missing")
        shutil.copytree(backup_dir, plugin_dir)
    return {
        "host": "hermes",
        "restored": True,
        "verified": True,
        "plugin_present": bool(metadata.get("present")),
        "plugin_enabled": bool(metadata.get("present")),
        "safe_switch_enabled": False,
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
