from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from aetnamem import Memory
from aetnamem.trial import TrialManager
from aetnamem.trial.openclaw_native import (
    CUTOVER_NAME,
    NATIVE_BASELINE_MANIFEST_NAME,
    NATIVE_BASELINE_NAME,
    NATIVE_SNAPSHOT_MANIFEST_NAME,
    activate_takeover,
    discover_sources,
    _focused_excerpt,
    inspect_native_memory_capabilities,
    restore_takeover,
    search_mirror,
    sync_mirror,
    trace_mirror,
)


def _manager(tmp_path: Path) -> TrialManager:
    return TrialManager.start(
        host="openclaw",
        state_path=tmp_path / "state.json",
        trial_root=tmp_path / "trials",
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "MEMORY.md").write_text(
        "# Memory\n\n- JT prefers TypeScript for new projects.\n",
        encoding="utf-8",
    )
    (workspace / "memory" / "2026-07-30.md").write_text(
        "# Daily note\n\nThe deployment failed before the cache was cleared.\n",
        encoding="utf-8",
    )
    (workspace / "memory" / "attachments").mkdir()
    (workspace / "memory" / "attachments" / "opaque.bin").write_bytes(
        b"\x00native-memory\xff"
    )
    (workspace / "memory" / "empty").mkdir()
    (workspace / "AGENTS.md").write_text(
        "# Instructions\n\nRun tests before deployment.\n", encoding="utf-8"
    )
    (workspace / "TOOLS.md").write_text(
        "# Tools\n\nUse git status.\n", encoding="utf-8"
    )
    return workspace


def test_search_excerpt_returns_only_the_matching_sentence() -> None:
    content = (
        "They like red cars. - JT said they hate blueberries. "
        "- JT said they like kebab for food."
    )

    assert _focused_excerpt(content, "kebab") == (
        "JT said they like kebab for food."
    )


def test_shadow_mirror_imports_native_planes_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)

    sources = discover_sources(workspace)
    assert {source.plane for source in sources} == {
        "semantic",
        "episodic",
        "procedural",
    }

    status = sync_mirror(manager.state(), workspace=workspace)
    assert status["synced"] is True
    assert status["source_count"] == 4
    assert status["record_count"] >= 4
    assert status["audit_verified"] is True
    assert status["native_baseline"]["snapshot_sha256"]
    assert (
        Path(manager.state().trial_dir)
        / NATIVE_BASELINE_NAME
        / "memory"
        / "attachments"
        / "opaque.bin"
    ).read_bytes() == b"\x00native-memory\xff"
    assert (Path(manager.state().trial_dir) / NATIVE_BASELINE_MANIFEST_NAME).is_file()

    search = search_mirror(manager.state(), "TypeScript projects")
    assert any("TypeScript" in row["content"] for row in search["records"])

    trace = trace_mirror(manager.state(), "TypeScript")
    assert trace["audit_chain_valid"] is True
    episodes = [item for item in trace["timeline"] if item.get("kind") == "episode"]
    assert episodes
    raw = episodes[0]["data"]["raw"]
    assert raw["relative_path"] == "MEMORY.md"
    assert raw["source_sha256"]
    assert raw["plane"] == "semantic"


def test_shadow_mirror_resynchronizes_when_native_memory_changes(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    first = sync_mirror(manager.state(), workspace=workspace)

    with (workspace / "MEMORY.md").open("a", encoding="utf-8") as sink:
        sink.write("- JT prefers PostgreSQL for durable application state.\n")
    second = sync_mirror(manager.state(), workspace=workspace)

    assert second["manifest_sha256"] != first["manifest_sha256"]
    assert (
        second["native_baseline"]["snapshot_sha256"]
        == first["native_baseline"]["snapshot_sha256"]
    )
    assert second["shadow_history"]["observed_change_versions"] == 1
    assert (
        second["shadow_history"]["latest_observed_sha256"]
        != second["shadow_history"]["initial_baseline_sha256"]
    )
    results = search_mirror(manager.state(), "PostgreSQL application state")
    assert any("PostgreSQL" in row["content"] for row in results["records"])


def test_takeover_freezes_native_files_and_rollback_restores_them(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    mirror = sync_mirror(manager.state(), workspace=workspace)
    with (workspace / "memory" / "2026-07-30.md").open("a", encoding="utf-8") as sink:
        sink.write("\nThe switch-time preference is lossless snapshots.\n")
    configured: dict[str, object] = {}
    commands: list[list[str]] = []

    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native.sync_mirror",
        lambda _state, **_kwargs: sync_mirror(_state, workspace=workspace),
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._optional_json",
        lambda arguments: (
            {"enabled": True}
            if "hooks.internal.entries.session-memory" in arguments
            else str(workspace)
            if any(str(value).endswith("config.nativeWorkspace") for value in arguments)
            else None
        ),
    )

    def set_json(_executable: str, key: str, value: object) -> None:
        configured[key] = value

    def run(arguments: list[str], *, allow_missing: bool = False):
        del allow_missing
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("aetnamem.trial.openclaw_native._set_json", set_json)
    monkeypatch.setattr("aetnamem.trial.openclaw_native._run", run)
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._json_command",
        lambda arguments: (
            {
                "plugin": {
                    "status": "loaded",
                    "toolNames": ["memory_search", "memory_get"],
                },
                "typedHooks": [
                    {"name": "before_prompt_build"},
                    {"name": "agent_end"},
                    {"name": "before_message_write"},
                    {"name": "before_tool_call"},
                ],
            }
            if "plugins" in arguments
            else {"rpc": {"ok": True}}
        ),
    )

    active = activate_takeover(manager.state(), manager.state_path)
    assert active["active"] is True
    assert active["native_snapshot_verified"] is True
    assert active["compatibility_tools_verified"] is True
    assert active["capture_hooks_verified"] is True
    assert active["native_write_guard_verified"] is True
    assert not (workspace / "MEMORY.md").exists()
    assert not (workspace / "memory").exists()
    assert configured["plugins.slots.memory"] == "none"
    assert (
        configured["plugins.entries.memory-aetnamem.config.takeoverActive"]
        is True
    )
    assert (
        configured["plugins.entries.memory-aetnamem.config.dbPath"]
        == mirror["mirror_db"]
    )
    assert (
        configured["plugins.entries.memory-aetnamem.config.nativeWorkspace"]
        == str(workspace)
    )
    assert (
        configured["plugins.entries.memory-aetnamem.hooks.allowConversationAccess"]
        is True
    )
    assert any(command[1:3] == ["hooks", "disable"] for command in commands)

    restored = restore_takeover(manager.state())
    assert restored["native_memory_restored"] is True
    assert (workspace / "MEMORY.md").is_file()
    assert (workspace / "memory" / "2026-07-30.md").is_file()
    assert "lossless snapshots" in (workspace / "memory" / "2026-07-30.md").read_text(
        encoding="utf-8"
    )
    assert (workspace / "memory" / "attachments" / "opaque.bin").read_bytes() == (
        b"\x00native-memory\xff"
    )
    assert (workspace / "memory" / "empty").is_dir()
    snapshot = json.loads(
        (Path(manager.state().trial_dir) / NATIVE_SNAPSHOT_MANIFEST_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["file_count"] == 5
    assert snapshot["snapshot_sha256"]
    assert all(
        row.get("sha256") for row in snapshot["entries"] if row["type"] == "file"
    )
    cutover = json.loads(
        (Path(manager.state().trial_dir) / CUTOVER_NAME).read_text(encoding="utf-8")
    )
    assert cutover["status"] == "rolled_back"

    # A completed rollback is a safe terminal state, not an incomplete
    # cutover. A later activation keeps the prior receipt and snapshot as
    # evidence while using a new archive.
    first_archive = cutover["archive"]
    reactivated = activate_takeover(manager.state(), manager.state_path)
    assert reactivated["active"] is True
    second_cutover = json.loads(
        (Path(manager.state().trial_dir) / CUTOVER_NAME).read_text(encoding="utf-8")
    )
    assert second_cutover["archive"] != first_archive
    history = list(
        (Path(manager.state().trial_dir) / "openclaw-cutover-history").glob(
            "rolled_back-*.json"
        )
    )
    assert len(history) == 1
    assert json.loads(history[0].read_text(encoding="utf-8"))["archive"] == first_archive
    assert restore_takeover(manager.state())["native_memory_restored"] is True


def test_rollback_preserves_post_switch_native_files_before_restore(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    mirror = sync_mirror(manager.state(), workspace=workspace)
    configured: dict[str, object] = {}

    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native.sync_mirror",
        lambda _state, **_kwargs: sync_mirror(_state, workspace=workspace),
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._optional_json",
        lambda arguments: (
            {"enabled": True}
            if "hooks.internal.entries.session-memory" in arguments
            else str(workspace)
            if any(str(value).endswith("config.nativeWorkspace") for value in arguments)
            else None
        ),
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._set_json",
        lambda _executable, key, value: configured.__setitem__(key, value),
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments, 0, "", ""
        ),
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._json_command",
        lambda arguments: (
            {
                "plugin": {
                    "status": "loaded",
                    "toolNames": ["memory_search", "memory_get"],
                },
                "typedHooks": [
                    {"name": "before_prompt_build"},
                    {"name": "agent_end"},
                    {"name": "before_message_write"},
                    {"name": "before_tool_call"},
                ],
            }
            if "plugins" in arguments
            else {"rpc": {"ok": True}}
        ),
    )

    activate_takeover(manager.state(), manager.state_path)
    active_memory = Memory(mirror["mirror_db"])
    try:
        active_memory.remember(
            manager.state().subject_id,
            "Remember that the post-switch code word is saffron.",
            source_type="user_message",
            session_id="agent:main:active-test",
        )
    finally:
        active_memory.close()
    (workspace / "memory").mkdir()
    (workspace / "memory" / "during-active.md").write_text(
        "This appeared after takeover.\n",
        encoding="utf-8",
    )
    (workspace / "MEMORY.md").write_text(
        "# Recreated\n\n- Post-switch fact.\n",
        encoding="utf-8",
    )

    restored = restore_takeover(manager.state())

    assert "TypeScript" in (workspace / "MEMORY.md").read_text(encoding="utf-8")
    assert (workspace / "memory" / "2026-07-30.md").is_file()
    assert not (workspace / "memory" / "during-active.md").exists()
    preserved = restored["post_switch_native_preserved"]
    assert {row["relative_path"] for row in preserved} == {
        "MEMORY.md",
        "memory",
    }
    preservation_root = Path(
        json.loads(
            (Path(manager.state().trial_dir) / CUTOVER_NAME).read_text(
                encoding="utf-8"
            )
        )["post_switch_native_preservation_root"]
    )
    assert "Post-switch fact" in (
        preservation_root / "MEMORY.md"
    ).read_text(encoding="utf-8")
    assert (
        preservation_root / "memory" / "during-active.md"
    ).read_text(encoding="utf-8") == "This appeared after takeover.\n"
    active_export = restored["active_memory_export"]
    assert active_export["record_count"] == 1
    assert "saffron" in Path(active_export["path"]).read_text(encoding="utf-8")
    assert Path(active_export["path"]).parent == workspace / "memory"


def test_shadow_refuses_a_corrupted_pre_shadow_baseline(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    sync_mirror(manager.state(), workspace=workspace)
    frozen = Path(manager.state().trial_dir) / NATIVE_BASELINE_NAME / "MEMORY.md"
    frozen.write_text("corrupted", encoding="utf-8")

    with pytest.raises(ValueError, match="baseline no longer verifies"):
        sync_mirror(manager.state(), workspace=workspace)

    assert "TypeScript" in (workspace / "MEMORY.md").read_text(encoding="utf-8")


def test_takeover_refuses_unverifiable_native_memory_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    mirror = sync_mirror(manager.state(), workspace=workspace)
    (workspace / "memory" / "linked.md").symlink_to(workspace / "MEMORY.md")
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native.sync_mirror",
        lambda _state, **_kwargs: mirror,
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._optional_json",
        lambda _arguments: None,
    )
    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0, "", ""),
    )

    with pytest.raises(ValueError, match="symlink"):
        activate_takeover(manager.state(), manager.state_path)

    assert (workspace / "MEMORY.md").is_file()
    assert (workspace / "memory" / "2026-07-30.md").is_file()
    failed = json.loads(
        (Path(manager.state().trial_dir) / CUTOVER_NAME).read_text(encoding="utf-8")
    )
    assert failed["status"] == "rolled_back_after_failure"


def test_capability_check_blocks_native_corpora_that_takeover_cannot_preserve(
    monkeypatch,
) -> None:
    def optional(arguments: list[str]):
        key = arguments[3]
        if key == "agents.defaults.memorySearch":
            return {
                "sources": ["memory", "sessions"],
                "extraPaths": ["/private/team-memory"],
            }
        if key == "plugins.entries.memory-wiki":
            return {"enabled": True}
        return None

    monkeypatch.setattr(
        "aetnamem.trial.openclaw_native._optional_json",
        optional,
    )
    report = inspect_native_memory_capabilities("/fake/openclaw")

    assert report["safe_to_switch"] is False
    assert any("non-memory sources" in row for row in report["blocking_reasons"])
    assert any("extraPaths" in row for row in report["blocking_reasons"])
    assert any("memory-wiki" in row for row in report["blocking_reasons"])
