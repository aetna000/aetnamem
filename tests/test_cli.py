from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "aetnamem.cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def test_cli_remember_recall_forget_roundtrip(tmp_path: Path) -> None:
    db = str(tmp_path / "mem.db")

    stored = _run("remember", db, "user-1", "My favorite color is teal.", "--session", "s1")
    assert stored.returncode == 0, stored.stderr
    assert json.loads(stored.stdout)["records"]

    recalled = _run("recall", db, "user-1", "What is my favorite color?")
    assert recalled.returncode == 0
    assert "teal" in json.loads(recalled.stdout)[0]["content"]

    forgotten = _run("forget", db, "user-1", "--utterance", "Forget my favorite color.")
    assert forgotten.returncode == 0
    payload = json.loads(forgotten.stdout)
    assert payload["deleted"] is True
    assert payload["receipt"]["format"] == "aetnamem-deletion-receipt-v1"

    listed = _run("list", db, "user-1")
    assert json.loads(listed.stdout) == []

    verified = _run("verify", db)
    assert verified.returncode == 0
    assert json.loads(verified.stdout)["valid"] is True


def test_cli_log_action(tmp_path: Path) -> None:
    db = str(tmp_path / "mem.db")
    result = _run(
        "log-action", db, "user-1", "tool_call",
        "--payload", '{"tool": "calendar.create"}', "--session", "s1",
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["event_id"].startswith("aud_")

    audit = _run("audit", db, "user-1")
    events = json.loads(audit.stdout)["audit_log"]
    assert events[0]["event_type"] == "agent.tool_call"
