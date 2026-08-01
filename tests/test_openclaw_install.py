from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetnamem.openclaw_install import (
    CommandResult,
    OPENCLAW_PLUGIN_VERSION,
    install_openclaw,
)


class FakeTrialManager:
    instance: "FakeTrialManager | None" = None

    def __init__(self, state_path: Path, trial_root: Path) -> None:
        self.state_path = state_path
        self.trial_root = trial_root
        self.mode = "capture"
        self.transitions: list[tuple[object, str]] = []

    @classmethod
    def start(
        cls, *, host: str, state_path: str | Path, trial_root: str | Path
    ) -> "FakeTrialManager":
        assert host == "openclaw"
        cls.instance = cls(Path(state_path), Path(trial_root))
        return cls.instance

    def state(self) -> object:
        return object()

    def status(self) -> dict[str, object]:
        return {
            "trial_id": "trial_test",
            "trial_dir": str(self.trial_root / "trial_test"),
            "mode": self.mode,
            "changes_model_context": False,
            "mirror": {
                "audit_verified": True,
                "mirror_db": str(self.trial_root / "trial_test" / "openclaw-mirror.db"),
                "native_baseline": {
                    "snapshot_sha256": "a" * 64,
                    "file_count": 3,
                    "total_bytes": 1024,
                },
            },
        }

    def transition(self, mode: object, *, actor: str) -> None:
        self.mode = getattr(mode, "value", str(mode))
        self.transitions.append((mode, actor))


class FakeOpenClaw:
    def __init__(self, *, gateway_ok: bool = True) -> None:
        self.plugin_version: str | None = None
        self.entry: dict[str, object] | None = None
        self.gateway_ok = gateway_ok
        self.commands: list[list[str]] = []

    def run(self, arguments: list[str]) -> CommandResult:
        self.commands.append(arguments)
        if arguments[0].endswith("aetnamem"):
            return CommandResult(0, "aetnamem 0.7.0a3\n", "")
        if arguments[1:] == ["--version"]:
            return CommandResult(0, "OpenClaw 2026.7.1-2\n", "")
        if arguments[1:3] == ["plugins", "inspect"]:
            if self.plugin_version is None:
                return CommandResult(1, "", "Plugin not installed")
            return CommandResult(
                0,
                json.dumps(
                    {
                        "plugin": {
                            "id": "memory-aetnamem",
                            "version": self.plugin_version,
                            "status": "loaded",
                        },
                        "diagnostics": [],
                    }
                ),
                "",
            )
        if arguments[1:3] == ["plugins", "install"]:
            spec = next(item for item in arguments if "@" in item)
            self.plugin_version = spec.rsplit("@", 1)[1]
            return CommandResult(0, "Installed plugin: memory-aetnamem\n", "")
        if arguments[1:3] == ["plugins", "uninstall"]:
            self.plugin_version = None
            self.entry = None
            return CommandResult(0, "Uninstalled\n", "")
        if arguments[1:3] == ["config", "get"]:
            key = arguments[3]
            if self.entry is None:
                return CommandResult(1, "", "No value found")
            if key == "plugins.entries.memory-aetnamem":
                value: object = self.entry
            elif key.endswith(".config"):
                value = self.entry.get("config", {})
            else:
                raise AssertionError(arguments)
            return CommandResult(0, json.dumps(value), "")
        if arguments[1:3] == ["config", "set"]:
            key = arguments[3]
            value = json.loads(arguments[4])
            if key == "plugins.entries.memory-aetnamem":
                self.entry = value
            else:
                self.entry = self.entry or {}
                if key.endswith(".config.command"):
                    self.entry.setdefault("config", {})["command"] = value  # type: ignore[index]
                elif key.endswith(".enabled"):
                    self.entry["enabled"] = value
                else:
                    raise AssertionError(arguments)
            return CommandResult(0, "", "")
        if arguments[1:3] == ["config", "unset"]:
            self.entry = None
            return CommandResult(0, "", "")
        if arguments[1:3] == ["gateway", "restart"]:
            return CommandResult(0, "Restarted\n", "")
        if arguments[1:3] == ["gateway", "status"]:
            if not self.gateway_ok:
                return CommandResult(1, "", "RPC probe failed")
            return CommandResult(0, json.dumps({"rpc": {"ok": True}}), "")
        raise AssertionError(arguments)


def test_installer_owns_bridge_setup_and_starts_capture_only_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = tmp_path / "aetnamem"
    engine.write_text("#!/bin/sh\n", encoding="utf-8")
    engine.chmod(0o755)
    fake = FakeOpenClaw()
    monkeypatch.setattr(
        "aetnamem.openclaw_install.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.openclaw_install.TrialManager",
        FakeTrialManager,
    )

    def configure(_state, state_path, *, aetnamem_executable):
        assert Path(state_path) == tmp_path / "state.json"
        assert aetnamem_executable == str(engine.resolve())
        assert fake.entry is not None
        fake.entry.setdefault("config", {})["safeSwitch"] = {  # type: ignore[index]
            "enabled": True,
            "statePath": str(state_path),
        }
        fake.entry["config"]["command"] = aetnamem_executable  # type: ignore[index]
        fake.entry["enabled"] = True
        return {"host": "openclaw", "configured": True}

    monkeypatch.setattr("aetnamem.trial.hosts.configure_host", configure)

    progress: list[tuple[int, int, str]] = []
    result = install_openclaw(
        state_path=tmp_path / "state.json",
        trial_root=tmp_path / "trials",
        runner=fake.run,
        engine_executable=str(engine),
        progress=lambda step, total, label: progress.append((step, total, label)),
    )

    assert result["installed"] is True
    assert result["plugin_version"] == OPENCLAW_PLUGIN_VERSION
    assert result["gateway_verified"] is True
    assert result["trial_mode"] == "capture"
    assert result["changes_model_context"] is False
    assert fake.entry is not None
    assert fake.entry["config"]["command"] == str(engine.resolve())  # type: ignore[index]
    install = next(command for command in fake.commands if command[1:3] == ["plugins", "install"])
    assert install[3] == f"npm:openclaw-memory-aetnamem@{OPENCLAW_PLUGIN_VERSION}"
    assert [step for step, _total, _label in progress] == list(range(1, 9))
    assert all(total == 8 for _step, total, _label in progress)
    assert "memory" in progress[4][2].casefold()
    assert "mirror" in progress[-1][2].casefold()


def test_installer_restores_prior_state_when_gateway_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = tmp_path / "aetnamem"
    engine.write_text("#!/bin/sh\n", encoding="utf-8")
    engine.chmod(0o755)
    fake = FakeOpenClaw(gateway_ok=False)
    monkeypatch.setattr(
        "aetnamem.openclaw_install.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.openclaw_install.TrialManager",
        FakeTrialManager,
    )

    def configure(_state, state_path, *, aetnamem_executable):
        fake.entry = {
            "enabled": True,
            "config": {
                "command": aetnamem_executable,
                "safeSwitch": {"enabled": True, "statePath": str(state_path)},
            },
        }
        return {"host": "openclaw", "configured": True}

    monkeypatch.setattr("aetnamem.trial.hosts.configure_host", configure)

    with pytest.raises(ValueError, match="prior OpenClaw plugin configuration was restored"):
        install_openclaw(
            state_path=tmp_path / "state.json",
            trial_root=tmp_path / "trials",
            runner=fake.run,
            engine_executable=str(engine),
        )

    assert fake.plugin_version is None
    assert fake.entry is None
    assert FakeTrialManager.instance is not None
    assert FakeTrialManager.instance.mode == "off"


def test_installer_restores_previous_bridge_version_and_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = tmp_path / "aetnamem"
    engine.write_text("#!/bin/sh\n", encoding="utf-8")
    engine.chmod(0o755)
    fake = FakeOpenClaw(gateway_ok=False)
    fake.plugin_version = "0.4.0"
    prior_entry = {
        "enabled": False,
        "config": {"command": "/old/aetnamem", "subject": "existing-user"},
    }
    fake.entry = json.loads(json.dumps(prior_entry))
    monkeypatch.setattr(
        "aetnamem.openclaw_install.shutil.which",
        lambda name: "/fake/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr(
        "aetnamem.openclaw_install.TrialManager",
        FakeTrialManager,
    )

    def configure(_state, state_path, *, aetnamem_executable):
        assert fake.entry is not None
        fake.entry["enabled"] = True
        fake.entry.setdefault("config", {})["command"] = aetnamem_executable  # type: ignore[index]
        fake.entry["config"]["safeSwitch"] = {  # type: ignore[index]
            "enabled": True,
            "statePath": str(state_path),
        }
        return {"host": "openclaw", "configured": True}

    monkeypatch.setattr("aetnamem.trial.hosts.configure_host", configure)

    with pytest.raises(ValueError, match="prior OpenClaw plugin configuration was restored"):
        install_openclaw(
            state_path=tmp_path / "state.json",
            trial_root=tmp_path / "trials",
            runner=fake.run,
            engine_executable=str(engine),
        )

    assert fake.plugin_version == "0.4.0"
    assert fake.entry == prior_entry
