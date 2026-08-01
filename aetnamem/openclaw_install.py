from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable

from aetnamem.trial import TrialManager, TrialMode
from aetnamem.trial.manager import DEFAULT_STATE_PATH, DEFAULT_TRIAL_ROOT


OPENCLAW_PLUGIN_ID = "memory-aetnamem"
OPENCLAW_PLUGIN_PACKAGE = "openclaw-memory-aetnamem"
OPENCLAW_PLUGIN_VERSION = "0.5.0-experimental.2"
_CONFIG_KEY = "plugins.entries.memory-aetnamem"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]
ProgressReporter = Callable[[int, int, str], None]


def install_openclaw(
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    trial_root: str | Path = DEFAULT_TRIAL_ROOT,
    runner: Runner | None = None,
    engine_executable: str | None = None,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Install the matching bridge and enter fail-closed capture mode.

    The Python package is the authority for this workflow. The npm package is
    a host bridge and is never presented as a standalone installation.
    """

    run = runner or _run
    report = progress or (lambda _step, _total, _label: None)
    total_steps = 8
    report(1, total_steps, "Checking AetnaMem and OpenClaw")
    engine = _resolve_engine(engine_executable)
    openclaw = shutil.which("openclaw")
    if openclaw is None:
        raise ValueError(
            "OpenClaw was not found on PATH. Install OpenClaw first, then rerun "
            "`aetnamem openclaw install`."
        )

    engine_version = _verify_engine(engine, run)
    _require_success(run([openclaw, "--version"]), "OpenClaw version check")

    report(2, total_steps, "Reading the current OpenClaw configuration")
    prior_plugin = _inspect_plugin(openclaw, run, optional=True)
    prior_version = _find_plugin_version(prior_plugin)
    prior_entry = _get_optional_json(
        [openclaw, "config", "get", _CONFIG_KEY, "--json"], run
    )
    package_changed = False
    manager: TrialManager | None = None
    rollback_errors: list[str] = []

    try:
        report(3, total_steps, "Installing the verified OpenClaw bridge")
        if prior_version != OPENCLAW_PLUGIN_VERSION:
            install_command = [
                openclaw,
                "plugins",
                "install",
                f"npm:{OPENCLAW_PLUGIN_PACKAGE}@{OPENCLAW_PLUGIN_VERSION}",
                "--pin",
            ]
            if prior_version is not None:
                install_command.append("--force")
            _require_success(run(install_command), "OpenClaw bridge installation")
            package_changed = True

        report(4, total_steps, "Verifying the installed bridge")
        installed = _inspect_plugin(openclaw, run, optional=False)
        installed_version = _find_plugin_version(installed)
        if installed_version != OPENCLAW_PLUGIN_VERSION:
            raise ValueError(
                "OpenClaw retained bridge version "
                f"{installed_version or 'unknown'}; expected {OPENCLAW_PLUGIN_VERSION}"
            )

        # Record the exact executable before the trial snapshot is taken. This
        # survives service PATH differences and remains the rollback baseline.
        _set_json(
            openclaw,
            f"{_CONFIG_KEY}.config.command",
            engine,
            run,
        )
        if prior_plugin is None:
            _set_json(openclaw, f"{_CONFIG_KEY}.enabled", False, run)

        report(5, total_steps, "Copying and indexing existing OpenClaw memory")
        manager = TrialManager.start(
            host="openclaw",
            state_path=state_path,
            trial_root=trial_root,
        )
        from aetnamem.trial.hosts import configure_host

        integration = configure_host(
            manager.state(),
            state_path,
            aetnamem_executable=engine,
        )
        report(6, total_steps, "Restarting the OpenClaw gateway")
        _require_success(
            run([openclaw, "gateway", "restart"]),
            "OpenClaw gateway restart",
        )
        report(7, total_steps, "Verifying the gateway and plugin runtime")
        gateway = _get_json(
            [
                openclaw,
                "gateway",
                "status",
                "--require-rpc",
                "--json",
            ],
            run,
        )
        if not _gateway_verified(gateway):
            raise ValueError("OpenClaw gateway RPC verification did not pass")
        runtime_plugin = _inspect_plugin(openclaw, run, optional=False)
        if not _plugin_runtime_healthy(runtime_plugin):
            raise ValueError("OpenClaw reported that the AetnaMem bridge is not healthy")
        observed = _get_json(
            [
                openclaw,
                "config",
                "get",
                f"{_CONFIG_KEY}.config",
                "--json",
            ],
            run,
        )
        if not isinstance(observed, dict):
            raise ValueError("OpenClaw did not return the AetnaMem plugin configuration")
        safe_switch = observed.get("safeSwitch")
        if not isinstance(safe_switch, dict) or safe_switch.get("enabled") is not True:
            raise ValueError("OpenClaw did not retain fail-closed Safe Switch mode")
        if observed.get("command") != engine:
            raise ValueError("OpenClaw did not retain the exact AetnaMem executable path")

        report(8, total_steps, "Verifying the memory mirror and audit evidence")
        status = manager.status()
        if status.get("mode") != "capture":
            raise ValueError("AetnaMem trial did not enter shadow capture mode")
        mirror = status.get("mirror")
        mirror = mirror if isinstance(mirror, dict) else {}
        baseline = mirror.get("native_baseline")
        baseline = baseline if isinstance(baseline, dict) else {}
        if not mirror.get("audit_verified") or not baseline.get("snapshot_sha256"):
            raise ValueError(
                "OpenClaw native-memory baseline or searchable mirror did not verify"
            )
        return {
            "format": "aetnamem-openclaw-install-v1",
            "installed": True,
            "engine_version": engine_version,
            "engine_executable": engine,
            "plugin_version": installed_version,
            "plugin_id": OPENCLAW_PLUGIN_ID,
            "gateway_verified": _gateway_verified(gateway),
            "trial_id": status.get("trial_id"),
            "trial_mode": status.get("mode"),
            "changes_model_context": status.get("changes_model_context"),
            "trial_dir": status.get("trial_dir"),
            "state_path": str(Path(state_path).expanduser().resolve(strict=False)),
            "integration": integration,
            "native_baseline_verified": True,
            "native_baseline_sha256": baseline.get("snapshot_sha256"),
            "native_baseline_files": baseline.get("file_count"),
            "native_baseline_bytes": baseline.get("total_bytes"),
            "mirror_verified": True,
            "mirror_db": mirror.get("mirror_db"),
        }
    except Exception as exc:
        report(total_steps, total_steps, "Installation failed; restoring prior state")
        if manager is not None:
            try:
                manager.transition(TrialMode.OFF, actor="install-rollback")
            except Exception as rollback_exc:  # pragma: no cover - defensive
                rollback_errors.append(f"trial stop: {rollback_exc}")
        if package_changed:
            try:
                if prior_version is None:
                    _require_success(
                        run(
                            [
                                openclaw,
                                "plugins",
                                "uninstall",
                                OPENCLAW_PLUGIN_ID,
                                "--force",
                            ]
                        ),
                        "bridge package rollback",
                    )
                else:
                    _require_success(
                        run(
                            [
                                openclaw,
                                "plugins",
                                "install",
                                f"npm:{OPENCLAW_PLUGIN_PACKAGE}@{prior_version}",
                                "--pin",
                                "--force",
                            ]
                        ),
                        "bridge package rollback",
                    )
            except Exception as rollback_exc:
                rollback_errors.append(f"bridge package: {rollback_exc}")
        try:
            _restore_entry(openclaw, prior_entry, run)
        except Exception as rollback_exc:
            rollback_errors.append(f"OpenClaw configuration: {rollback_exc}")
        try:
            _require_success(
                run([openclaw, "gateway", "restart"]),
                "OpenClaw gateway restart after rollback",
            )
        except Exception as rollback_exc:
            rollback_errors.append(f"gateway restart: {rollback_exc}")
        detail = f"AetnaMem OpenClaw installation failed: {exc}"
        if rollback_errors:
            detail += ". Rollback also needs attention: " + "; ".join(rollback_errors)
        else:
            detail += ". The prior OpenClaw plugin configuration was restored."
        raise ValueError(detail) from exc


def _resolve_engine(explicit: str | None) -> str:
    candidate = explicit or shutil.which("aetnamem")
    if not candidate:
        raise ValueError(
            "The `aetnamem` executable is not on PATH. Install the engine first "
            "with `python -m pip install aetnamem`, confirm `aetnamem --version`, "
            "then rerun `aetnamem openclaw install`."
        )
    path = Path(candidate).expanduser().resolve(strict=False)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"AetnaMem executable is missing or not executable: {path}")
    return str(path)


def _verify_engine(engine: str, run: Runner) -> str:
    result = run([engine, "--version"])
    _require_success(result, "AetnaMem engine version check")
    output = result.stdout.strip()
    if not output.startswith("aetnamem "):
        raise ValueError(f"unexpected AetnaMem version response: {output or 'empty'}")
    return output.removeprefix("aetnamem ").strip()


def _inspect_plugin(
    openclaw: str, run: Runner, *, optional: bool
) -> Any | None:
    result = run(
        [openclaw, "plugins", "inspect", OPENCLAW_PLUGIN_ID, "--json"]
    )
    if result.returncode != 0 and optional:
        normalized = f"{result.stderr}\n{result.stdout}".casefold()
        if any(text in normalized for text in ("not found", "not installed", "unknown")):
            return None
    _require_success(result, "OpenClaw bridge inspection")
    return _parse_json(result.stdout, "OpenClaw bridge inspection")


def _find_plugin_version(value: Any) -> str | None:
    if isinstance(value, dict):
        plugin = value.get("plugin")
        if isinstance(plugin, dict) and isinstance(plugin.get("version"), str):
            return str(plugin["version"])
        if isinstance(value.get("version"), str):
            return str(value["version"])
        for nested in value.values():
            found = _find_plugin_version(nested)
            if found is not None:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _find_plugin_version(nested)
            if found is not None:
                return found
    return None


def _gateway_verified(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    rpc = value.get("rpc")
    if isinstance(rpc, dict) and rpc.get("ok") is True:
        return True
    gateway = value.get("gateway")
    if not isinstance(gateway, dict):
        return False
    probe = gateway.get("probe")
    if isinstance(probe, dict):
        return probe.get("ok") is True
    return gateway.get("reachable") is True or gateway.get("status") in {
        "running",
        "ready",
    }


def _plugin_runtime_healthy(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    plugin = value.get("plugin")
    if not isinstance(plugin, dict) or plugin.get("status") not in {
        "loaded",
        "active",
        "ready",
    }:
        return False
    diagnostics = value.get("diagnostics")
    if isinstance(diagnostics, list):
        for item in diagnostics:
            if isinstance(item, dict) and str(item.get("level", "")).casefold() in {
                "error",
                "fatal",
            }:
                return False
    return True


def _set_json(openclaw: str, key: str, value: Any, run: Runner) -> None:
    _require_success(
        run(
            [
                openclaw,
                "config",
                "set",
                key,
                json.dumps(value, separators=(",", ":")),
                "--strict-json",
            ]
        ),
        f"OpenClaw configuration write for {key}",
    )


def _restore_entry(openclaw: str, prior_entry: Any | None, run: Runner) -> None:
    if prior_entry is None:
        result = run([openclaw, "config", "unset", _CONFIG_KEY])
        if result.returncode != 0:
            normalized = f"{result.stderr}\n{result.stdout}".casefold()
            if not any(
                text in normalized
                for text in ("not found", "no value", "missing", "unknown config path")
            ):
                _require_success(result, "OpenClaw configuration rollback")
        return
    _set_json(openclaw, _CONFIG_KEY, prior_entry, run)


def _get_json(arguments: list[str], run: Runner) -> Any:
    result = run(arguments)
    _require_success(result, " ".join(arguments[1:3]))
    return _parse_json(result.stdout, " ".join(arguments[1:3]))


def _get_optional_json(arguments: list[str], run: Runner) -> Any | None:
    result = run(arguments)
    if result.returncode != 0:
        normalized = f"{result.stderr}\n{result.stdout}".casefold()
        if any(
            text in normalized
            for text in ("not found", "missing", "no value", "unknown config path")
        ):
            return None
        _require_success(result, " ".join(arguments[1:3]))
    return _parse_json(result.stdout, " ".join(arguments[1:3]))


def _parse_json(text: str, operation: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{operation} did not return JSON") from exc


def _require_success(result: CommandResult, operation: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
    raise ValueError(f"{operation} failed: {detail}")


def _run(arguments: list[str]) -> CommandResult:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"could not run {' '.join(arguments[:3])}: {exc}") from exc
    return CommandResult(result.returncode, result.stdout, result.stderr)
