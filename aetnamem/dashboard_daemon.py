from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

from aetnamem.store.sqlite import utc_now


DEFAULT_DAEMON_STATE = Path.home() / ".aetnamem" / "dashboard-daemon.json"
DEFAULT_DAEMON_LOG = Path.home() / ".aetnamem" / "dashboard-daemon.log"


def manage_dashboard_daemon(
    action: str,
    *,
    port: int = 8766,
    trial_state_path: str | Path | None = None,
    daemon_state_path: str | Path = DEFAULT_DAEMON_STATE,
) -> dict[str, Any]:
    state_path = Path(daemon_state_path).expanduser().resolve(strict=False)
    if action == "status":
        return _status(state_path)
    if action == "open":
        current = _status(state_path)
        if not current.get("running"):
            raise ValueError(
                "AetnaMem dashboard daemon is not running; use "
                "`aetnamem dashboard daemon start`"
            )
        login_url = str(current.get("login_url") or "")
        if not login_url:
            raise ValueError(
                "dashboard access URL is unavailable; restart the daemon"
            )
        if not _open_default_browser(login_url):
            raise ValueError(
                "the default browser did not accept the dashboard URL; "
                "copy the Access URL shown by `aetnamem dashboard daemon status`"
            )
        return {**current, "opened": True}
    if action == "start":
        return _start(
            state_path,
            port=port,
            trial_state_path=trial_state_path,
        )
    if action == "stop":
        return _stop(state_path)
    if action == "restart":
        prior = _read(state_path)
        selected_port = int(prior.get("port") or port) if prior else port
        selected_state = (
            prior.get("trial_state_path") if prior else trial_state_path
        )
        _stop(state_path)
        return _start(
            state_path,
            port=selected_port,
            trial_state_path=selected_state,
        )
    if action == "remove":
        stopped = _stop(state_path)
        try:
            state_path.unlink()
        except FileNotFoundError:
            pass
        return {
            "format": "aetnamem-dashboard-daemon-v1",
            "installed": False,
            "running": False,
            "removed": True,
            "data_preserved": True,
            "previous": stopped,
        }
    raise ValueError(f"unknown dashboard daemon action: {action}")


def _start(
    state_path: Path,
    *,
    port: int,
    trial_state_path: str | Path | None,
) -> dict[str, Any]:
    if not 1 <= int(port) <= 65535:
        raise ValueError("dashboard port must be between 1 and 65535")
    current = _status(state_path)
    if current.get("running"):
        raise ValueError(
            f"AetnaMem dashboard daemon is already running on port "
            f"{current.get('port')}; use `aetnamem dashboard daemon restart`"
        )
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path.parent.chmod(0o700)
    log_path = state_path.parent / DEFAULT_DAEMON_LOG.name
    log_path.touch(mode=0o600, exist_ok=True)
    log_path.chmod(0o600)
    # The log is append-only across restarts. Remember its current end so
    # startup cannot mistake an earlier daemon's access URL for the new
    # daemon's key.
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    command = [
        sys.executable,
        "-m",
        "aetnamem.cli",
        "dashboard",
        "--no-open",
        "--port",
        str(port),
    ]
    if trial_state_path is not None:
        command.extend(["--state", str(Path(trial_state_path).expanduser())])
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    value = {
        "format": "aetnamem-dashboard-daemon-v1",
        "pid": process.pid,
        "port": int(port),
        "url": f"http://127.0.0.1:{int(port)}/",
        "trial_state_path": (
            str(Path(trial_state_path).expanduser().resolve(strict=False))
            if trial_state_path is not None
            else None
        ),
        "log_path": str(log_path),
        "started_at": utc_now(),
    }
    _write(state_path, value)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = _tail(log_path)
            raise ValueError(
                f"AetnaMem dashboard daemon exited during startup: {detail}"
            )
        login_url = _login_url(log_path, after_bytes=log_offset)
        if login_url:
            value["login_url"] = login_url
            _write(state_path, value)
            break
        time.sleep(0.1)
    if not value.get("login_url"):
        detail = _tail(log_path)
        _stop(state_path)
        raise ValueError(
            "AetnaMem dashboard daemon did not publish a usable access URL "
            f"during startup: {detail}"
        )
    return {**value, "running": process.poll() is None, "installed": True}


def _stop(state_path: Path) -> dict[str, Any]:
    value = _read(state_path)
    if not value:
        return {
            "format": "aetnamem-dashboard-daemon-v1",
            "installed": False,
            "running": False,
            "stopped": True,
        }
    pid = int(value.get("pid") or 0)
    if pid > 0 and _alive(pid):
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _alive(pid):
            time.sleep(0.1)
        if _alive(pid):
            raise ValueError(
                f"dashboard process {pid} did not stop; inspect {value.get('log_path')}"
            )
    value.update({"running": False, "stopped": True, "stopped_at": utc_now()})
    _write(state_path, value)
    return value


def _status(state_path: Path) -> dict[str, Any]:
    value = _read(state_path)
    if not value:
        return {
            "format": "aetnamem-dashboard-daemon-v1",
            "installed": False,
            "running": False,
        }
    pid = int(value.get("pid") or 0)
    value["installed"] = True
    value["running"] = pid > 0 and _alive(pid)
    return value


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _open_default_browser(url: str) -> bool:
    """Open a URL with the operating system, bypassing editor link handlers."""
    try:
        if sys.platform == "darwin":
            completed = subprocess.run(
                ["/usr/bin/open", url],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return completed.returncode == 0
        if os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        for command in (["xdg-open", url], ["gio", "open", url]):
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except FileNotFoundError:
                continue
            if completed.returncode == 0:
                return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def _write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _login_url(path: Path, *, after_bytes: int = 0) -> str | None:
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, int(after_bytes)))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    prefix = "Dashboard login: "
    for line in reversed(lines):
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _tail(path: Path, lines: int = 12) -> str:
    try:
        values = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return "no log output"
    return "\n".join(values[-lines:]) or "no log output"
