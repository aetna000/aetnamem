from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)
from http.cookiejar import CookieJar

import pytest

from aetnamem.trial import TrialManager, TrialMode
from aetnamem.trial.server import TrialMCPServer


def _manager(tmp_path: Path) -> TrialManager:
    return TrialManager.start(
        host="openclaw",
        state_path=tmp_path / "state.json",
        trial_root=tmp_path / "trials",
    )


def test_mirror_then_active_is_the_customer_transition(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)

    captured = manager.capture(
        "Remember that my preferred editor is Neovim.",
        session_id="session-1",
        authenticated_user=True,
    )
    assert captured["captured"] == 1
    assert captured["raw_message_stored"] is False

    # Side-by-side mode computes recall internally but cannot inject it.
    assert manager.prepare("Which editor?")["inject"] is False
    candidate_id = captured["candidate_ids"][0]
    manager.review([candidate_id], approve=True)

    active = manager.transition(TrialMode.ACTIVE)
    assert active.mode is TrialMode.ACTIVE
    prepared = manager.prepare("Which editor do I prefer?")
    assert prepared["inject"] is True
    assert "Neovim" in prepared["context"]


def test_capture_rejects_non_user_and_does_not_store_raw_prompt(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    raw = "Remember that my favorite color is ultraviolet."
    rejected = manager.capture(
        raw,
        session_id="tool-session",
        authenticated_user=False,
    )
    assert rejected["captured"] == 0

    captured = manager.capture(
        raw,
        session_id="user-session",
        authenticated_user=True,
    )
    assert captured["captured"] == 1
    state = manager.state()
    database_bytes = (Path(state.trial_dir) / "evidence.db").read_bytes()
    assert raw.encode() not in database_bytes
    assert b"ultraviolet" in database_bytes


def test_corrupt_state_fails_closed(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"mode":"active"}', encoding="utf-8")
    manager = TrialManager(state_path)
    status = manager.status()
    assert status["mode"] == "off"
    assert status["changes_model_context"] is False
    assert status["warning"]
    assert manager.prepare("anything")["inject"] is False


def test_transition_chain_detects_tampering(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    state = manager.state()
    store = manager._store(state)
    try:
        store._conn.execute(
            "UPDATE transitions SET actor = 'tampered' WHERE trial_id = ?",
            (state.trial_id,),
        )
        store._conn.commit()
    finally:
        store.close()
    status = manager.status()
    assert status["evidence"]["transition_chain"]["valid"] is False
    assert status["readiness"]["ready_for_preview"] is False


def test_private_mcp_exposes_no_approval_or_mode_change_tools(
    tmp_path: Path,
) -> None:
    server = TrialMCPServer(_manager(tmp_path))
    response = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    names = {
        item["name"] for item in response["result"]["tools"]  # type: ignore[index]
    }
    assert names == {
        "trial_capture",
        "trial_prepare",
        "trial_exposure_shown",
        "trial_status",
    }
    assert not any("approve" in name or "mode" in name for name in names)


def test_state_digest_tampering_turns_integration_off(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    value = json.loads(manager.state_path.read_text(encoding="utf-8"))
    value["mode"] = "active"
    manager.state_path.write_text(json.dumps(value), encoding="utf-8")
    state, warning = manager.effective_state()
    assert state.mode is TrialMode.OFF
    assert warning == "trial state digest mismatch"


def test_openclaw_configuration_is_snapshotted_and_restored(
    tmp_path: Path, monkeypatch
) -> None:
    from aetnamem.trial.hosts import configure_host, restore_host

    manager = _manager(tmp_path)
    state = manager.state()
    entry: dict[str, object] | None = {
        "enabled": False,
        "config": {"existing": "kept"},
    }

    def fake_run(arguments, **kwargs):
        del kwargs
        nonlocal entry
        assert arguments[0] == "/fake/openclaw"
        if arguments[1:3] == ["plugins", "inspect"]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps(
                    {
                        "plugin": {
                            "id": "memory-aetnamem",
                            "version": "0.5.0-experimental.1",
                        }
                    }
                ),
                "",
            )
        operation = arguments[2]
        key = arguments[3]
        if operation == "get":
            if key == "plugins.entries.memory-aetnamem":
                if entry is None:
                    return subprocess.CompletedProcess(arguments, 1, "", "missing")
                return subprocess.CompletedProcess(
                    arguments, 0, json.dumps(entry), ""
                )
            if key.endswith(".config.safeSwitch"):
                value = (
                    entry.get("config", {}).get("safeSwitch")  # type: ignore[union-attr]
                    if entry
                    else None
                )
                return subprocess.CompletedProcess(
                    arguments, 0, json.dumps(value), ""
                )
        if operation == "set":
            value = json.loads(arguments[4])
            if key == "plugins.entries.memory-aetnamem":
                entry = value
            else:
                assert entry is not None
                suffix = key.removeprefix("plugins.entries.memory-aetnamem.")
                if suffix == "enabled":
                    entry["enabled"] = value
                elif suffix == "hooks.allowConversationAccess":
                    entry.setdefault("hooks", {})["allowConversationAccess"] = value  # type: ignore[index]
                elif suffix == "config.command":
                    entry.setdefault("config", {})["command"] = value  # type: ignore[index]
                elif suffix == "config.safeSwitch":
                    entry.setdefault("config", {})["safeSwitch"] = value  # type: ignore[index]
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if operation == "unset":
            entry = None
            return subprocess.CompletedProcess(arguments, 0, "", "")
        raise AssertionError(arguments)

    monkeypatch.setattr("aetnamem.trial.hosts.shutil.which", lambda _: "/fake/openclaw")
    monkeypatch.setattr("aetnamem.trial.hosts.subprocess.run", fake_run)

    configured = configure_host(state, manager.state_path)
    assert configured["configured"] is True
    assert entry is not None
    assert entry["config"]["existing"] == "kept"  # type: ignore[index]
    assert entry["config"]["safeSwitch"]["enabled"] is True  # type: ignore[index]

    restored = restore_host(state)
    assert restored["verified"] is True
    assert restored["plugin_enabled"] is False
    assert restored["safe_switch_enabled"] is False
    assert entry == {"enabled": False, "config": {"existing": "kept"}}


def test_dashboard_uses_http_only_cookie_and_csrf_for_mutations(
    tmp_path: Path,
) -> None:
    from aetnamem.trial.web import TrialDashboardServer

    manager = _manager(tmp_path)
    server = TrialDashboardServer(
        ("127.0.0.1", 0), manager, html="<html>safe</html>"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    try:
        response = opener.open(f"{base}/auth?code={server.login_code}")
        assert response.read() == b"<html>safe</html>"
        # Redirect hides the original Set-Cookie header, but the jar proves
        # the cookie was accepted and the protected page became readable.
        assert opener.open(f"{base}/api/status").status == 200
        session = json.loads(opener.open(f"{base}/api/session").read())

        unprotected = Request(
            f"{base}/api/mode",
            data=json.dumps({"mode": "off"}).encode(),
            headers={"Content-Type": "application/json", "Origin": base},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            opener.open(unprotected)
        assert error.value.code == 403

        protected = Request(
            f"{base}/api/mode",
            data=json.dumps({"mode": "off"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": base,
                "X-CSRF-Token": session["csrf_token"],
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            opener.open(protected)
        assert error.value.code == 409
        result = json.loads(error.value.read())
        assert "Activate AetnaMem or Restore OpenClaw" in result["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dashboard_ships_the_visual_trial_ui_not_the_json_fallback() -> None:
    from aetnamem.trial.web import dashboard_html

    html = dashboard_html()

    assert "Exactly what is mirrored" in html
    assert 'id="sources"' in html
    assert 'id="query"' in html
    assert "Activate AetnaMem" in html
    assert "Restore OpenClaw" in html
    assert 'id="progress"' in html
    assert "This can take a minute." in html
    assert "Refreshing the memory mirror" in html
    assert 'get("/api/status")' in html
    assert 'JSON.stringify(v,null,2)' not in html
    assert "Canary" not in html
    assert "Emergency" not in html
    assert "Recall Preview" not in html
    assert 'id="funnelBars"' not in html
    # Mockup-only comparison figures must never be presented as live evidence.
    assert "112,480" not in html
    assert "35/42" not in html


def test_trial_rollback_defaults_to_human_output_and_keeps_json_opt_in(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aetnamem.cli import _print_trial

    result = {
        "host": "openclaw",
        "mode": "off",
        "changes_model_context": False,
        "makes_extra_provider_calls": False,
        "trial_id": "trial_customer",
        "trial_dir": "/tmp/trial_customer",
        "host_restore": {
            "host": "openclaw",
            "restored": True,
            "verified": True,
            "plugin_present": True,
            "plugin_enabled": True,
            "safe_switch_enabled": False,
        },
    }

    _print_trial("rollback", result, json_output=False)
    human = capsys.readouterr().out
    assert "AetnaMem rollback complete" in human
    assert "Host configuration   restored" in human
    assert "Verification         PASSED" in human
    assert "Memory provider      OpenClaw" in human
    assert "AetnaMem plugin      enabled (restored pre-trial state)" in human
    assert "AetnaMem itself is still enabled" in human
    assert not human.lstrip().startswith("{")

    _print_trial("rollback", result, json_output=True)
    machine = capsys.readouterr().out
    assert json.loads(machine)["host_restore"]["verified"] is True


def test_active_trial_status_does_not_tell_user_to_activate_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aetnamem.cli import _print_trial

    _print_trial(
        "status",
        {
            "host": "openclaw",
            "mode": "active",
            "changes_model_context": True,
            "makes_extra_provider_calls": False,
            "readiness": {
                "ready_for_active": True,
                "reasons": [],
            },
        },
        json_output=False,
    )

    human = capsys.readouterr().out
    assert "AetnaMem is active" in human
    assert "trial rollback" in human
    assert "Ready: inspect/search" not in human
