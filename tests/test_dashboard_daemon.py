from __future__ import annotations

from pathlib import Path

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
        lambda _path: "http://127.0.0.1:9123/auth?code=private",
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
