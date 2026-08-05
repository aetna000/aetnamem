from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess

from aetnamem.control import ControlMode, ControlPlaneManager
from aetnamem.control.compat import evaluate_host_version, parse_openclaw_version
from aetnamem.control.openclaw_native import (
    CUTOVER_NAME,
    _native_snapshot_digest,
    _tree_manifest,
    mirror_status,
    sync_mirror,
)
from aetnamem.control.verify import run_verification, verification_exit_code


def _setup(tmp_path: Path) -> tuple[ControlPlaneManager, Path]:
    manager = ControlPlaneManager.start(
        host="openclaw",
        state_path=tmp_path / "state.json",
        control_root=tmp_path / "migrations",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "MEMORY.md").write_text("- User likes careful migrations.\n", encoding="utf-8")
    sync_mirror(manager.state(), workspace=workspace)
    return manager, workspace


def _host(
    monkeypatch,
    *,
    slot: str = "memory-native",
    version: str = "2026.7.1-2",
    bridge_version: str = "1.0.0-experimental.6",
) -> dict[str, object]:
    config: dict[str, object] = {
        "plugins.slots.memory": slot,
        "plugins.entries.memory-aetnamem.enabled": True,
        "plugins.entries.memory-aetnamem.config.controlPlane": {"enabled": True},
        "plugins.entries.memory-aetnamem.config.takeoverActive": False,
    }
    monkeypatch.setattr(
        "aetnamem.control.verify.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.control.verify._run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments, 0, f"openclaw {version}\n", ""
        ),
    )

    def optional(arguments: list[str]):
        if arguments[1:3] == ["plugins", "inspect"]:
            return {"plugin": {"version": bridge_version}}
        if arguments[1:3] == ["gateway", "status"]:
            return {"rpc": {"ok": True}}
        return config.get(arguments[3])

    monkeypatch.setattr("aetnamem.control.verify._optional_json", optional)
    return config


def _active_setup(tmp_path: Path, monkeypatch) -> tuple[ControlPlaneManager, Path, Path, dict[str, object]]:
    manager, workspace = _setup(tmp_path)
    config = _host(monkeypatch, slot="none")
    monkeypatch.setattr(
        "aetnamem.control.openclaw_native.mirror_status",
        lambda state: mirror_status(state, refresh=False),
    )
    state = manager.transition(ControlMode.ACTIVE)
    control_dir = Path(state.control_dir)
    archive = control_dir / "active-frozen"
    archive.mkdir()
    shutil.copy2(workspace / "MEMORY.md", archive / "MEMORY.md")
    entries = _tree_manifest(archive, ("MEMORY.md",))
    applied = {
        "plugins.slots.memory": "none",
        "hooks.internal.entries.session-memory": {"enabled": False},
        "plugins.entries.memory-aetnamem.enabled": True,
    }
    config.update(applied)
    cutover = {
        "format": "aetnamem-openclaw-cutover-v1",
        "migration_id": state.migration_id,
        "status": "active",
        "workspace": str(workspace),
        "archive": str(archive),
        "mirror_db": str(control_dir / "openclaw-mirror.db"),
        "relocated": ["MEMORY.md"],
        "native_snapshot": {
            "entries": entries,
            "snapshot_sha256": _native_snapshot_digest(entries),
        },
        "applied_configuration": applied,
    }
    (control_dir / CUTOVER_NAME).write_text(
        json.dumps(cutover), encoding="utf-8"
    )
    return manager, workspace, archive, config


def _by_name(report: dict) -> dict[str, dict]:
    return {row["name"]: row for row in report["checks"]}


def test_healthy_shadow_verification_is_stable_and_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    manager, workspace = _setup(tmp_path)
    _host(monkeypatch)
    source_before = (workspace / "MEMORY.md").read_bytes()
    mirror = Path(manager.state().control_dir) / "openclaw-mirror.db"
    mirror_before = mirror.read_bytes()

    first = run_verification(manager.state())
    second = run_verification(manager.state())

    assert first["valid"] is True
    assert verification_exit_code(first) == 0
    assert _by_name(first)["shadow_configuration_safe"]["status"] == "pass"
    assert _by_name(first)["shadow_context_probe"]["status"] == "skip"
    assert first["evidence_sha256"] == second["evidence_sha256"]
    assert first["report_sha256"] != second["report_sha256"]
    assert (workspace / "MEMORY.md").read_bytes() == source_before
    assert mirror.read_bytes() == mirror_before


def test_stale_mirror_fails_without_repairing_source_or_mirror(
    tmp_path: Path, monkeypatch
) -> None:
    manager, workspace = _setup(tmp_path)
    _host(monkeypatch)
    mirror = Path(manager.state().control_dir) / "openclaw-mirror.db"
    mirror_before = mirror.read_bytes()
    (workspace / "MEMORY.md").write_text("- Changed after mirror.\n", encoding="utf-8")
    source_before = (workspace / "MEMORY.md").read_bytes()

    report = run_verification(manager.state())

    check = _by_name(report)["mirror_integrity"]
    assert check["status"] == "fail"
    assert check["evidence"]["divergent_paths"][0]["path"] == "MEMORY.md"
    assert mirror.read_bytes() == mirror_before
    assert (workspace / "MEMORY.md").read_bytes() == source_before


def test_unknown_host_is_exit_two_only_when_it_is_the_only_failure(
    tmp_path: Path, monkeypatch
) -> None:
    manager, _workspace = _setup(tmp_path)
    _host(monkeypatch, version="2027.1.0")

    report = run_verification(manager.state())

    assert _by_name(report)["host_version_tested"]["status"] == "fail"
    assert verification_exit_code(report) == 2


def test_openclaw_version_scheme_includes_build_suffix() -> None:
    assert parse_openclaw_version("OpenClaw 2026.7.1-2") == (2026, 7, 1, 2)
    assert evaluate_host_version("2026.7.1-2") == "tested"
    assert evaluate_host_version("2026.7.9-1") == "untested_patch"
    assert evaluate_host_version("2027.1.0") == "untested"


def test_active_config_drift_isolated_to_config_check(tmp_path: Path, monkeypatch) -> None:
    manager, _workspace, _archive, config = _active_setup(tmp_path, monkeypatch)
    config["plugins.slots.memory"] = "memory-native"

    report = run_verification(manager.state())
    failures = [row["name"] for row in report["checks"] if row["status"] == "fail"]

    assert failures == ["config_consistency"]


def test_frozen_archive_tamper_is_named_without_duplicate_failure(
    tmp_path: Path, monkeypatch
) -> None:
    manager, _workspace, archive, _config = _active_setup(tmp_path, monkeypatch)
    (archive / "MEMORY.md").write_text("tampered\n", encoding="utf-8")

    report = run_verification(manager.state())
    failures = [row["name"] for row in report["checks"] if row["status"] == "fail"]

    assert failures == ["frozen_paths_unchanged"]
    frozen = _by_name(report)["frozen_paths_unchanged"]
    assert frozen["evidence"]["differences"][0]["path"] == "MEMORY.md"
    assert _by_name(report)["restore_readiness"]["status"] == "skip"


def test_bridge_version_drift_isolated_to_bridge_check(tmp_path: Path, monkeypatch) -> None:
    manager, _workspace = _setup(tmp_path)
    _host(monkeypatch, bridge_version="9.9.9")

    report = run_verification(manager.state())
    failures = [row["name"] for row in report["checks"] if row["status"] == "fail"]

    assert failures == ["bridge_version_pinned"]
