from __future__ import annotations

from pathlib import Path

import pytest

from aetnamem.dashboard_daemon import manage_dashboard_daemon


class _FakeProcess:
    pid = 4242

    def poll(self):
        return None


def test_dashboard_daemon_start_records_direct_loopback_url(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "dashboard.json"
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._dashboard_url",
        lambda _path, **_kwargs: "http://127.0.0.1:9123/",
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._alive", lambda pid: pid == 4242
    )

    result = manage_dashboard_daemon(
        "start", port=9123, daemon_state_path=state_path
    )

    assert result["running"] is True
    assert result["url"] == "http://127.0.0.1:9123/"
    assert "login_url" not in result
    assert "access_code" not in result
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "dashboard-daemon.log").stat().st_mode & 0o777 == 0o600


def test_dashboard_daemon_remove_preserves_memory_data(tmp_path: Path) -> None:
    state_path = tmp_path / "dashboard.json"
    state_path.write_text(
        '{"format":"aetnamem-dashboard-daemon-v1","pid":999999,"port":8766}\n',
        encoding="utf-8",
    )

    result = manage_dashboard_daemon("remove", daemon_state_path=state_path)

    assert result["removed"] is True
    assert result["data_preserved"] is True
    assert not state_path.exists()


def test_dashboard_daemon_open_uses_direct_url(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "dashboard.json"
    state_path.write_text(
        '{"format":"aetnamem-dashboard-daemon-v1","pid":4242,'
        '"port":8766,"url":"http://127.0.0.1:8766/"}\n',
        encoding="utf-8",
    )
    opened: list[str] = []
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._alive", lambda pid: pid == 4242
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._open_default_browser",
        lambda url: opened.append(url) or True,
    )

    result = manage_dashboard_daemon("open", daemon_state_path=state_path)

    assert result["opened"] is True
    assert opened == ["http://127.0.0.1:8766/"]


def test_dashboard_daemon_start_fails_closed_without_ready_url(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "dashboard.json"
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._dashboard_url",
        lambda _path, **_kwargs: None,
    )
    ticks = iter((0.0, 6.0))
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon.time.monotonic", lambda: next(ticks)
    )
    monkeypatch.setattr(
        "aetnamem.dashboard_daemon._alive", lambda _pid: False
    )

    with pytest.raises(ValueError, match="did not publish a usable URL"):
        manage_dashboard_daemon("start", port=9123, daemon_state_path=state_path)

    assert '"running": false' in state_path.read_text(encoding="utf-8")


def test_dashboard_url_ignores_old_log_entries(tmp_path: Path) -> None:
    from aetnamem.dashboard_daemon import _dashboard_url

    log_path = tmp_path / "dashboard.log"
    log_path.write_text(
        "AetnaMem dashboard: http://127.0.0.1:8766/\n", encoding="utf-8"
    )
    restart_offset = log_path.stat().st_size

    assert _dashboard_url(log_path, after_bytes=restart_offset) is None

    with log_path.open("a", encoding="utf-8") as stream:
        stream.write("AetnaMem dashboard: http://127.0.0.1:9123/\n")

    assert _dashboard_url(log_path, after_bytes=restart_offset) == (
        "http://127.0.0.1:9123/"
    )
