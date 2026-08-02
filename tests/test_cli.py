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

def test_cli_version_reports_installed_distribution_version() -> None:
    from importlib.metadata import version

    result = _run("--version")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"aetnamem {version('aetnamem')}"


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


def test_cli_read_only_search_trace_and_report_files(tmp_path: Path) -> None:
    db = str(tmp_path / "mem.db")
    stored = _run(
        "remember",
        db,
        "user-1",
        "My preferred airport is Sydney.",
        "--session",
        "s1",
        "--turn",
        "1",
    )
    record_id = json.loads(stored.stdout)["records"][0]["id"]
    assert _run(
        "recall", db, "user-1", "Which airport?", "--session", "s1"
    ).returncode == 0
    assert _run(
        "log-action",
        db,
        "user-1",
        "tool_call",
        "--payload",
        '{"tool":"flights.search","status":"ok"}',
        "--session",
        "s1",
        "--turn",
        "2",
    ).returncode == 0

    before = json.loads(_run("audit", db, "user-1").stdout)["audit_log"]
    searched = _run(
        "search", db, "preferred airport", "--subject", "user-1", "--format", "json"
    )
    assert searched.returncode == 0, searched.stderr
    search_report = json.loads(searched.stdout)
    assert search_report["format"] == "aetnamem-search-v1"
    assert search_report["audit_chain_valid"] is True
    assert any(
        item["kind"] == "memory" and item["id"] == record_id
        for item in search_report["results"]
    )
    after = json.loads(_run("audit", db, "user-1").stdout)["audit_log"]
    assert len(after) == len(before), "audit search must not record a memory recall"

    text_path = tmp_path / "memories.txt"
    written = _run(
        "memories", db, "--subject", "user-1", "--output", str(text_path)
    )
    assert written.returncode == 0, written.stderr
    assert written.stdout == ""
    assert "User's preferred airport is Sydney." in text_path.read_text()

    json_path = tmp_path / "trace.json"
    traced = _run(
        "trace",
        db,
        "airport",
        "--subject",
        "user-1",
        "--output",
        str(json_path),
    )
    assert traced.returncode == 0, traced.stderr
    trace_report = json.loads(json_path.read_text())
    assert trace_report["format"] == "aetnamem-trace-v1"
    kinds = {item["kind"] for item in trace_report["timeline"]}
    assert {"memory", "retrieval", "event"} <= kinds
    assert any(
        item["data"].get("event_type") == "agent.tool_call"
        for item in trace_report["timeline"]
    )
