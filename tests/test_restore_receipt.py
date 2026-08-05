from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from aetnamem.control import ControlPlaneManager
from aetnamem.control.openclaw_native import (
    CUTOVER_NAME,
    NATIVE_BASELINE_MANIFEST_NAME,
    NATIVE_BASELINE_NAME,
    RESTORE_STAGING_NAME,
    restore_drill,
    restore_takeover,
    sync_mirror,
)
from aetnamem.control.store import ControlStore
from aetnamem.core.canonical import canonical_json, sha256_hex


def _manager(tmp_path: Path) -> ControlPlaneManager:
    return ControlPlaneManager.start(
        host="openclaw",
        state_path=tmp_path / "state.json",
        control_root=tmp_path / "migrations",
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "MEMORY.md").write_text(
        "# Memory\n\n- User prefers deterministic restores.\n", encoding="utf-8"
    )
    (workspace / "memory" / "2026-08-03.md").write_text(
        "# Daily\n\nThe restore drill was requested.\n", encoding="utf-8"
    )
    return workspace


def _write_cutover(manager: ControlPlaneManager, workspace: Path) -> None:
    state = manager.state()
    sync_mirror(state, workspace=workspace)
    control_dir = Path(state.control_dir)
    snapshot = json.loads(
        (control_dir / NATIVE_BASELINE_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    cutover = {
        "format": "aetnamem-openclaw-cutover-v1",
        "migration_id": state.migration_id,
        "status": "active",
        "workspace": str(workspace),
        "archive": str(control_dir / NATIVE_BASELINE_NAME),
        "mirror_db": str(control_dir / "openclaw-mirror.db"),
        "native_snapshot": snapshot,
        "relocated": ["MEMORY.md", "memory"],
        "prior_memory_slot": "memory-native",
        "prior_session_memory_hook": {"enabled": True},
        "prior_plugin_entry": None,
        "prior_tools_also_allow": [],
    }
    (control_dir / CUTOVER_NAME).write_text(
        json.dumps(cutover, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _tree_digest(root: Path) -> str:
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        rows.append(
            {
                "path": relative,
                "type": "directory" if path.is_dir() else "file",
                "sha256": sha256_hex(path.read_bytes()) if path.is_file() else None,
            }
        )
    return sha256_hex(canonical_json(rows))


def _fake_openclaw(monkeypatch):
    config: dict[str, object] = {
        "plugins.slots.memory": "none",
        "hooks.internal.entries.session-memory": {"enabled": False},
        "plugins.entries.memory-aetnamem": {"enabled": True},
        "tools.alsoAllow": ["memory_remember", "aetnamem_observe"],
    }
    monkeypatch.setattr(
        "aetnamem.control.openclaw_native.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.control.openclaw_native._set_json",
        lambda _executable, key, value: config.__setitem__(key, value),
    )
    monkeypatch.setattr(
        "aetnamem.control.openclaw_native._optional_json",
        lambda arguments: config.get(arguments[3]),
    )

    def run(arguments: list[str], **_kwargs):
        if len(arguments) > 3 and arguments[1:3] == ["config", "unset"]:
            config.pop(arguments[3], None)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("aetnamem.control.openclaw_native._run", run)
    monkeypatch.setattr(
        "aetnamem.control.openclaw_native._json_command",
        lambda _arguments: {"rpc": {"ok": True}},
    )
    return config


def test_restore_drill_proves_only_staging_and_config_readability(
    tmp_path: Path, monkeypatch
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    _write_cutover(manager, workspace)
    before = _tree_digest(workspace)
    config_gets: list[str] = []

    monkeypatch.setattr(
        "aetnamem.control.openclaw_native.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )

    def optional(arguments: list[str]):
        config_gets.append(arguments[3])
        return {"enabled": True}

    monkeypatch.setattr(
        "aetnamem.control.openclaw_native._optional_json", optional
    )
    monkeypatch.setattr(
        "aetnamem.control.openclaw_native._run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments, 0, "openclaw 2026.7.1-2\n", ""
        ),
    )

    report = restore_drill(manager.state())

    assert report["valid"] is True
    assert report["files_restoration_tested"] is True
    assert report["saved_config_readable"] is True
    assert report["live_rollback_performed"] is False
    assert report["evidence_sha256"]
    assert report["report_sha256"]
    assert _tree_digest(workspace) == before
    assert set(config_gets) == {
        "plugins.slots.memory",
        "hooks.internal.entries.session-memory",
        "plugins.entries.memory-aetnamem",
        "tools.alsoAllow",
    }
    assert not (Path(manager.state().control_dir) / RESTORE_STAGING_NAME / "drill").exists()

    store = ControlStore(Path(manager.state().control_dir) / "evidence.db")
    try:
        latest = store.latest_evidence(
            manager.state().migration_id, kind="restore_drill"
        )
        assert latest is not None
        assert latest["body"]["report_sha256"] == report["report_sha256"]
        assert store.verify_evidence_chain(
            manager.state().migration_id, kind="restore_drill"
        )["valid"] is True
    finally:
        store.close()


def test_restore_drill_rejects_tampered_archive_without_live_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    _write_cutover(manager, workspace)
    before = _tree_digest(workspace)
    frozen = Path(manager.state().control_dir) / NATIVE_BASELINE_NAME / "MEMORY.md"
    frozen.write_text("tampered", encoding="utf-8")
    monkeypatch.setattr(
        "aetnamem.control.openclaw_native.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )

    import pytest

    with pytest.raises(ValueError, match="restore preflight"):
        restore_drill(manager.state())
    assert _tree_digest(workspace) == before


def test_restore_receipt_separates_baseline_from_active_additions(
    tmp_path: Path, monkeypatch
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    _write_cutover(manager, workspace)
    _fake_openclaw(monkeypatch)
    shutil.rmtree(workspace / "memory")
    (workspace / "MEMORY.md").unlink()

    from aetnamem import Memory

    mirror = Path(manager.state().control_dir) / "openclaw-mirror.db"
    memory = Memory(mirror)
    try:
        memory.remember(
            manager.state().subject_id,
            "Remember that the active-period code word is juniper.",
            source_type="user_message",
            session_id="agent:main:active",
        )
    finally:
        memory.close()

    receipt = restore_takeover(manager.state())

    assert receipt["format"] == "aetnamem-restore-receipt-v1"
    assert receipt["valid"] is True
    assert all(row["matched"] for row in receipt["files"])
    export = receipt["active_memory_export"]
    assert export["record_count"] == 1
    assert len(export["additions"]) == 1
    assert "juniper" in Path(export["path"]).read_text(encoding="utf-8")
    assert not any(
        row["path"].endswith(Path(export["path"]).name) for row in receipt["files"]
    )
    assert receipt["gateway"]["verified"] is True
    assert receipt["mirror_integrity"]["valid"] is True

    from aetnamem import Memory

    audit = Memory(mirror)
    try:
        restored_events = [
            row
            for row in audit.store.list_audit_events(manager.state().subject_id)
            if row["event_type"] == "control.restored"
        ]
        assert len(restored_events) == 1
        assert restored_events[0]["payload"]["receipt_sha256"] == receipt["report_sha256"]
    finally:
        audit.close()

    repeated = restore_takeover(manager.state())
    assert repeated["report_sha256"] == receipt["report_sha256"]

    store = ControlStore(Path(manager.state().control_dir) / "evidence.db")
    try:
        assert store.verify_evidence_chain(
            manager.state().migration_id, kind="restore"
        )["valid"] is True
        assert len(
            store.list_evidence(manager.state().migration_id, kind="restore")
        ) == 1
    finally:
        store.close()


def test_restore_preflight_failure_writes_invalid_receipt_and_changes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    _write_cutover(manager, workspace)
    _fake_openclaw(monkeypatch)
    before = _tree_digest(workspace)
    frozen = Path(manager.state().control_dir) / NATIVE_BASELINE_NAME / "MEMORY.md"
    frozen.write_text("tampered", encoding="utf-8")

    import pytest

    with pytest.raises(ValueError, match="restore preflight"):
        restore_takeover(manager.state())
    assert _tree_digest(workspace) == before
    receipt = json.loads(
        (Path(manager.state().control_dir) / "openclaw-restore-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["valid"] is False
    assert receipt["journal"]["steps"] == []


def test_interrupted_restore_resumes_without_reapplying_completed_file_step(
    tmp_path: Path, monkeypatch
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    _write_cutover(manager, workspace)
    _fake_openclaw(monkeypatch)
    shutil.rmtree(workspace / "memory")
    (workspace / "MEMORY.md").unlink()

    import aetnamem.control.openclaw_native as native
    import pytest

    original = native._complete_restore_step
    interrupted = {"raised": False}

    def fail_after_memory(journal, journal_path, name, evidence):
        original(journal, journal_path, name, evidence)
        if name == "file:MEMORY.md" and not interrupted["raised"]:
            interrupted["raised"] = True
            raise RuntimeError("injected interruption")

    monkeypatch.setattr(native, "_complete_restore_step", fail_after_memory)
    with pytest.raises(RuntimeError, match="injected interruption"):
        restore_takeover(manager.state())
    assert (workspace / "MEMORY.md").is_file()
    assert not (workspace / "memory").exists()

    monkeypatch.setattr(native, "_complete_restore_step", original)
    receipt = restore_takeover(manager.state())
    assert receipt["valid"] is True
    assert receipt["journal"]["resumed"] is True
    assert (workspace / "memory" / "2026-08-03.md").is_file()
