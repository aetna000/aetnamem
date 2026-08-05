from __future__ import annotations

from pathlib import Path
import shutil
import time
from typing import Any

from aetnamem.control.compat import (
    TESTED_OPENCLAW_VERSIONS,
    evaluate_host_version,
    normalize_openclaw_version,
)
from aetnamem.control.evidence import seal_report
from aetnamem.control.models import ControlMode, ControlState
from aetnamem.control.openclaw_native import (
    CUTOVER_NAME,
    MIRROR_DB_NAME,
    MIRROR_MANIFEST_NAME,
    _manifest_diff,
    _optional_json,
    _read_json,
    _restore_expected_entries,
    _run,
    _source_row,
    discover_sources,
)
from aetnamem.control.store import ControlStore
from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.core.storage import HouseholdPolicy
from aetnamem.memory import Memory
from aetnamem.openclaw_install import OPENCLAW_PLUGIN_VERSION, _find_plugin_version
from aetnamem.store.sqlite import utc_now


def _check(name: str, status: str, measured: Any, evidence: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "measured": measured, "evidence": evidence}


def _host_version(executable: str) -> tuple[str, str]:
    result = _run([executable, "--version"])
    version = normalize_openclaw_version(result.stdout or result.stderr)
    return version, evaluate_host_version(version)


def _stored_source_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("sources")
    return list(rows) if isinstance(rows, list) else []


def _current_source_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    workspace = Path(str(manifest.get("workspace") or ""))
    current: list[dict[str, Any]] = []
    for source in discover_sources(workspace):
        current.append(_source_row(source))
    return current


def _source_differences(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    stored = {str(row.get("relative_path")): row for row in _stored_source_rows(manifest)}
    current = {str(row.get("relative_path")): row for row in _current_source_rows(manifest)}
    rows: list[dict[str, Any]] = []
    for path in sorted(set(stored) | set(current)):
        expected = stored.get(path)
        actual = current.get(path)
        matched = bool(
            expected
            and actual
            and expected.get("sha256") == actual.get("sha256")
            and expected.get("bytes") == actual.get("bytes")
        )
        if not matched:
            rows.append(
                {
                    "path": path,
                    "expected_sha256": expected.get("sha256") if expected else None,
                    "actual_sha256": actual.get("sha256") if actual else None,
                    "missing": expected is not None and actual is None,
                    "unexpected": expected is None and actual is not None,
                }
            )
    return rows


def _audit_integrity(path: Path, subject_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "error": "mirror database is missing"}
    before = sha256_hex(path.read_bytes())
    memory = Memory(path)
    try:
        report = memory.verify(subject_id)
    finally:
        memory.close()
    after = sha256_hex(path.read_bytes())
    if before != after:
        return {"valid": False, "error": "integrity verification mutated the mirror database"}
    return report


def _live_config(executable: str, keys: list[str]) -> dict[str, Any]:
    return {
        key: _optional_json([executable, "config", "get", key, "--json"])
        for key in keys
    }


def _config_check(
    state: ControlState, executable: str, cutover: dict[str, Any] | None
) -> dict[str, Any]:
    if state.mode is ControlMode.ACTIVE and cutover:
        applied = cutover.get("applied_configuration")
        if isinstance(applied, dict):
            observed = _live_config(executable, sorted(applied))
            mismatches = [key for key in sorted(applied) if observed.get(key) != applied[key]]
            return _check(
                "config_consistency",
                "fail" if mismatches else "pass",
                {"recorded_keys": len(applied), "partial": False},
                {"mismatches": mismatches, "observed_sha256": sha256_hex(canonical_json(observed))},
            )
        legacy = {
            "plugins.slots.memory": "none",
            "hooks.internal.entries.session-memory": {"enabled": False},
        }
        observed = _live_config(executable, sorted(legacy))
        mismatches = [key for key, value in legacy.items() if observed.get(key) != value]
        return _check(
            "config_consistency",
            "fail" if mismatches else "warn",
            {"recorded_keys": len(legacy), "partial": True},
            {"mismatches": mismatches, "reason": "pre-v1 complete applied configuration was not recorded"},
        )
    keys = [
        "plugins.slots.memory",
        "plugins.entries.memory-aetnamem.enabled",
        "plugins.entries.memory-aetnamem.config.controlPlane",
        "plugins.entries.memory-aetnamem.config.takeoverActive",
    ]
    observed = _live_config(executable, keys)
    control = observed[keys[2]]
    safe = (
        observed[keys[0]] != "none"
        and observed[keys[1]] is True
        and isinstance(control, dict)
        and control.get("enabled") is True
        and observed[keys[3]] is not True
    )
    return _check(
        "config_consistency",
        "pass" if safe else "fail",
        {"recorded_keys": len(keys), "partial": False},
        {"configuration_sha256": sha256_hex(canonical_json(observed))},
    )


def _restore_readiness(
    state: ControlState,
    cutover: dict[str, Any] | None,
    host_version: str,
) -> dict[str, Any]:
    if not cutover:
        return _check("restore_readiness", "skip", False, {"reason": "activation snapshot not created yet"})
    try:
        expected = _restore_expected_entries(cutover)
        archive = Path(str(cutover.get("archive") or ""))
        roots = tuple(str(value) for value in cutover.get("relocated") or ())
        differences = _manifest_diff(expected, archive, roots=roots)
        snapshot_valid = all(row["matched"] for row in differences)
    except ValueError as exc:
        return _check("restore_readiness", "fail", False, {"error": str(exc)})
    control_dir = Path(state.control_dir)
    store = ControlStore(
        control_dir / "evidence.db",
        policy=HouseholdPolicy.load(control_dir / MIRROR_DB_NAME),
    )
    try:
        drill = store.latest_evidence(state.migration_id, kind="restore_drill")
    finally:
        store.close()
    if not snapshot_valid:
        return _check("restore_readiness", "fail", False, {"differences": differences})
    if drill is None:
        return _check("restore_readiness", "warn", True, {"reason": "no restore drill recorded"})
    body = drill["body"]
    stale = bool(body.get("host_version") and body.get("host_version") != host_version)
    return _check(
        "restore_readiness",
        "warn" if stale else ("pass" if body.get("valid") else "fail"),
        bool(body.get("valid")),
        {
            "drill_report_sha256": body.get("report_sha256"),
            "drill_ended_at": body.get("ended_at"),
            "stale_for_host_version": stale,
        },
    )


def run_verification(state: ControlState, *, probe: bool = False) -> dict[str, Any]:
    """Measure the current control-plane state without repairing or restarting it."""

    started = time.monotonic()
    started_at = utc_now()
    executable = shutil.which("openclaw")
    checks: list[dict[str, Any]] = []
    host_version = "unavailable"
    if executable is None:
        checks.append(_check("host_version_tested", "fail", None, {"error": "OpenClaw is not on PATH"}))
        checks.append(_check("bridge_version_pinned", "fail", None, {"error": "OpenClaw is not on PATH"}))
    else:
        try:
            host_version, classification = _host_version(executable)
            checks.append(
                _check(
                    "host_version_tested",
                    {"tested": "pass", "untested_patch": "warn", "untested": "fail"}[classification],
                    host_version,
                    {"classification": classification, "tested_versions": list(TESTED_OPENCLAW_VERSIONS)},
                )
            )
        except ValueError as exc:
            checks.append(_check("host_version_tested", "fail", None, {"error": str(exc)}))
        plugin = _optional_json([executable, "plugins", "inspect", "memory-aetnamem", "--json"])
        bridge_version = _find_plugin_version(plugin)
        checks.append(
            _check(
                "bridge_version_pinned",
                "pass" if bridge_version == OPENCLAW_PLUGIN_VERSION else "fail",
                bridge_version,
                {"expected": OPENCLAW_PLUGIN_VERSION},
            )
        )

    control_dir = Path(state.control_dir)
    manifest = _read_json(control_dir / MIRROR_MANIFEST_NAME)
    cutover = _read_json(control_dir / CUTOVER_NAME)
    if manifest is None:
        checks.append(_check("mirror_integrity", "fail", False, {"error": "stored mirror manifest is missing"}))
    else:
        differences = [] if state.mode is ControlMode.ACTIVE else _source_differences(manifest)
        audit = _audit_integrity(control_dir / MIRROR_DB_NAME, state.subject_id)
        mirror_valid = not differences and bool(audit.get("valid"))
        checks.append(
            _check(
                "mirror_integrity",
                "pass" if mirror_valid else "fail",
                mirror_valid,
                {"divergent_paths": differences, "audit_valid": bool(audit.get("valid")), "audit_error": audit.get("error")},
            )
        )

    if executable is not None:
        checks.append(_config_check(state, executable, cutover))
        if state.mode is ControlMode.SHADOW:
            observed = _live_config(
                executable,
                ["plugins.slots.memory", "plugins.entries.memory-aetnamem.config.takeoverActive"],
            )
            safe = observed["plugins.slots.memory"] != "none" and observed["plugins.entries.memory-aetnamem.config.takeoverActive"] is not True
            checks.append(_check("shadow_configuration_safe", "pass" if safe else "fail", safe, observed))
            checks.append(_check("shadow_context_probe", "skip", False, {"reason": "isolation unavailable" if probe else "probe not requested"}))
        else:
            checks.append(_check("shadow_configuration_safe", "skip", None, {"reason": "active mode"}))
            checks.append(_check("shadow_context_probe", "skip", None, {"reason": "active mode"}))

        frozen_valid: bool | None = None
        if state.mode is ControlMode.ACTIVE and cutover:
            snapshot = cutover.get("native_snapshot") or {}
            roots = tuple(str(value) for value in cutover.get("relocated") or ())
            archive = Path(str(cutover.get("archive") or ""))
            expected = _restore_expected_entries(cutover)
            differences = _manifest_diff(expected, archive, roots=roots)
            frozen_valid = all(row["matched"] for row in differences)
            checks.append(_check("frozen_paths_unchanged", "pass" if frozen_valid else "fail", frozen_valid, {"differences": [row for row in differences if not row["matched"]], "snapshot_sha256": snapshot.get("snapshot_sha256")}))
        else:
            checks.append(_check("frozen_paths_unchanged", "skip", None, {"reason": "not active"}))

        if frozen_valid is False:
            checks.append(
                _check(
                    "restore_readiness",
                    "skip",
                    False,
                    {"reason": "frozen paths failed the dedicated integrity check"},
                )
            )
        else:
            checks.append(_restore_readiness(state, cutover, host_version))
        gateway = _optional_json([executable, "gateway", "status", "--require-rpc", "--json"])
        rpc = gateway.get("rpc") if isinstance(gateway, dict) else None
        healthy = isinstance(rpc, dict) and rpc.get("ok") is True
        checks.append(_check("gateway_health", "pass" if healthy else "fail", healthy, {"rpc_ok": healthy}))
    else:
        for name in ("config_consistency", "shadow_configuration_safe", "shadow_context_probe", "frozen_paths_unchanged", "restore_readiness", "gateway_health"):
            checks.append(_check(name, "skip", None, {"reason": "OpenClaw is unavailable"}))

    valid = not any(row["status"] == "fail" for row in checks)
    body = {
        "format": "aetnamem-control-verification-v1",
        "migration_id": state.migration_id,
        "mode": state.mode.value,
        "host": state.host,
        "host_version": host_version,
        "bridge_version": next((row["measured"] for row in checks if row["name"] == "bridge_version_pinned"), None),
        "started_at": started_at,
        "ended_at": utc_now(),
        "duration_ms": round((time.monotonic() - started) * 1000),
        "checks": checks,
        "valid": valid,
    }
    stable = {key: body[key] for key in ("format", "migration_id", "mode", "host", "host_version", "bridge_version", "checks", "valid")}
    report = seal_report(body, stable_evidence=stable)
    store = ControlStore(
        control_dir / "evidence.db",
        policy=HouseholdPolicy.load(control_dir / MIRROR_DB_NAME),
    )
    try:
        evidence = store.append_evidence(state.migration_id, kind="verification", body=report)
    finally:
        store.close()
    return {**report, "evidence_entry_sha256": evidence["entry_sha256"]}


def verification_exit_code(report: dict[str, Any]) -> int:
    failures = [row["name"] for row in report.get("checks", []) if row.get("status") == "fail"]
    if not failures:
        return 0
    return 2 if failures == ["host_version_tested"] else 1
