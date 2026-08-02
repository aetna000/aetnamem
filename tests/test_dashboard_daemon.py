from __future__ import annotations

from pathlib import Path

import pytest

from aetnamem.dashboard_daemon import manage_dashboard_daemon


class _FakeProcess:
    pid = 4242

    def poll(self):
        return None


def test_dashboard_daemon_start_records_private_background_process(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "dashboard.json"
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._login_url",
        lambda _path, **_kwargs: "http://127.0.0.1:9123/auth?code=private",
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._alive",
        lambda pid: pid == 4242,
    )

    result = manage_dashboard_daemon(
        "start",
        port=9123,
        daemon_state_path=state_path,
    )

    assert result["running"] is True
    assert result["port"] == 9123
    assert result["login_url"].endswith("code=private")
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "dashboard-daemon.log").stat().st_mode & 0o777 == 0o600


def test_dashboard_daemon_reuses_private_access_code_after_restart(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "dashboard.json"
    stable_code = "stable-" + "a" * 40
    state_path.write_text(
        '{"format":"aetnamem-dashboard-daemon-v1","pid":999999,'
        f'"port":9123,"access_code":"{stable_code}"}}\n',
        encoding="utf-8",
    )
    launches: list[dict] = []

    def fake_popen(*args, **kwargs):
        del args
        launches.append(kwargs)
        return _FakeProcess()

    monkeypatch.setattr("aetnamem.dashboard_daemon.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._login_url",
        lambda _path, **_kwargs: (
            f"http://127.0.0.1:9123/auth?code={stable_code}"
        ),
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._alive",
        lambda pid: pid == 4242,
    )

    result = manage_dashboard_daemon(
        "start", port=9123, daemon_state_path=state_path
    )

    assert result["access_code"] == stable_code
    assert result["login_url"].endswith(stable_code)
    assert launches[0]["env"]["AETNAMEM_DASHBOARD_ACCESS_CODE"] == stable_code
    persisted = state_path.read_text(encoding="utf-8")
    assert stable_code in persisted


def test_dashboard_daemon_remove_preserves_memory_data(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dashboard.json"
    state_path.write_text(
        '{"format":"aetnamem-dashboard-daemon-v1","pid":999999,"port":8766}\n',
        encoding="utf-8",
    )

    result = manage_dashboard_daemon(
        "remove",
        daemon_state_path=state_path,
    )

    assert result["removed"] is True
    assert result["data_preserved"] is True
    assert not state_path.exists()


def test_dashboard_daemon_open_uses_recorded_access_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "dashboard.json"
    state_path.write_text(
        '{"format":"aetnamem-dashboard-daemon-v1","pid":4242,'
        '"port":8766,"login_url":"http://127.0.0.1:8766/auth?code=stable"}\n',
        encoding="utf-8",
    )
    opened: list[str] = []
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._alive",
        lambda pid: pid == 4242,
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._open_default_browser",
        lambda url: opened.append(url) or True,
    )

    result = manage_dashboard_daemon("open", daemon_state_path=state_path)

    assert result["opened"] is True
    assert opened == ["http://127.0.0.1:8766/auth?code=stable"]


def test_dashboard_daemon_start_fails_closed_without_access_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "dashboard.json"
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._login_url",
        lambda _path, **_kwargs: None,
    )
    ticks = iter((0.0, 6.0))
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon.time.monotonic",
        lambda: next(ticks),
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._alive",
        lambda _pid: False,
    )

    with pytest.raises(ValueError, match="did not publish a usable access URL"):
        manage_dashboard_daemon(
            "start",
            port=9123,
            daemon_state_path=state_path,
        )

    assert '"running": false' in state_path.read_text(encoding="utf-8")


def test_login_url_ignores_consumed_codes_before_restart(tmp_path: Path) -> None:
    from aetnamem.dashboard_daemon import _login_url

    log_path = tmp_path / "dashboard.log"
    log_path.write_text(
        "Dashboard login: http://127.0.0.1:8766/auth?code=consumed\n",
        encoding="utf-8",
    )
    restart_offset = log_path.stat().st_size

    assert _login_url(log_path, after_bytes=restart_offset) is None

    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(
            "Dashboard login: http://127.0.0.1:8766/auth?code=fresh\n"
        )

    assert _login_url(
        log_path, after_bytes=restart_offset
    ) == "http://127.0.0.1:8766/auth?code=fresh"
