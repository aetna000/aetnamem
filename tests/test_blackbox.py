from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetnamem.control.blackbox import EVENT_FORMAT, format_flight_report
from aetnamem.control.manager import ControlPlaneManager
from aetnamem.control.store import ControlStore


def _manager(tmp_path: Path) -> ControlPlaneManager:
    return ControlPlaneManager.start(
        host="openclaw",
        state_path=tmp_path / "control.json",
        control_root=tmp_path / "migrations",
        subject_id="user-1",
    )


def test_blackbox_records_content_minimizing_verified_flight(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    prompt = "send the private report"
    response = "Done. I sent the report."
    manager.record_blackbox_event(
        event_type="model.input",
        run_id="run-1",
        session_id="session-1",
        payload={
            "provider": "openai",
            "model": "gpt-test",
            "prompt_sha256": "1" * 64,
            "prompt_chars": len(prompt),
            "system_sha256": "2" * 64,
            "system_chars": 100,
            "history_sha256": "3" * 64,
            "history_count": 2,
            "images_count": 0,
            "tools_count": 1,
        },
    )
    manager.record_blackbox_event(
        event_type="tool.requested",
        run_id="run-1",
        session_id="session-1",
        tool_call_id="tool-1",
        payload={
            "tool_name": "email.send",
            "params_sha256": "4" * 64,
            "param_keys": ["recipient", "subject"],
            "derived_path_sha256": [],
        },
    )
    manager.record_blackbox_event(
        event_type="tool.completed",
        run_id="run-1",
        session_id="session-1",
        tool_call_id="tool-1",
        payload={
            "tool_name": "email.send",
            "result_sha256": "5" * 64,
            "outcome": "completed",
            "duration_ms": 42,
        },
    )
    manager.record_blackbox_event(
        event_type="model.output",
        run_id="run-1",
        session_id="session-1",
        payload={
            "provider": "openai",
            "model": "gpt-test",
            "response_sha256": "6" * 64,
            "response_chars": len(response),
            "response_count": 1,
            "usage": {"input": 100, "output": 20, "total": 120},
        },
    )
    manager.record_blackbox_event(
        event_type="turn.ended",
        run_id="run-1",
        session_id="session-1",
        payload={
            "success": True,
            "cancelled": False,
            "messages_sha256": "7" * 64,
            "messages_count": 4,
        },
    )

    report = manager.verify_blackbox_flight("run-1")
    assert report["timeline_chain_valid"] is True
    assert report["structurally_complete"] is True
    assert report["verdict"] == "observed_tools_reached_terminal_events"
    assert report["coverage"]["response_digest_bound"] is True
    assert report["raw_content_stored"] is False
    serialized = json.dumps(report)
    assert prompt not in serialized
    assert response not in serialized
    assert "private report" not in serialized
    assert "does not prove that an external real-world outcome occurred" in report[
        "claim_boundary"
    ]
    assert "email.send" in format_flight_report(report)


def test_blackbox_reports_missing_completion_without_claiming_success(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager.record_blackbox_event(
        event_type="tool.requested",
        run_id="run-gap",
        tool_call_id="tool-gap",
        payload={
            "tool_name": "filesystem.write",
            "params_sha256": "a" * 64,
            "param_keys": ["path"],
            "derived_path_sha256": ["d" * 64],
        },
    )
    manager.record_blackbox_event(
        event_type="turn.ended",
        run_id="run-gap",
        payload={
            "success": True,
            "cancelled": False,
            "messages_sha256": "b" * 64,
            "messages_count": 1,
        },
    )
    report = manager.verify_blackbox_flight("run-gap")
    assert report["verdict"] == "incomplete_evidence"
    assert report["structurally_complete"] is False
    assert report["tools"]["missing_completions"] == ["tool-gap"]


def test_blackbox_rejects_raw_or_unknown_payload_fields(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(ValueError, match="unsupported blackbox payload"):
        manager.record_blackbox_event(
            event_type="model.output",
            run_id="run-raw",
            payload={"response_text": "secret"},
        )


def test_blackbox_global_chain_detects_tampering(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.record_blackbox_event(
        event_type="turn.ended",
        run_id="run-tamper",
        payload={
            "success": True,
            "cancelled": False,
            "messages_sha256": "c" * 64,
            "messages_count": 1,
        },
    )
    state = manager.state()
    store = ControlStore(Path(state.control_dir) / "evidence.db")
    try:
        entry = store.list_evidence(state.migration_id, kind="agent_blackbox")[0]
        body = dict(entry["body"])
        assert body["format"] == EVENT_FORMAT
        body["event_type"] = "turn.rewritten"
        store._conn.execute(
            "UPDATE evidence SET body_json = ? WHERE id = ?",
            (json.dumps(body, separators=(",", ":"), sort_keys=True), entry["id"]),
        )
        store._conn.commit()
    finally:
        store.close()
    report = manager.verify_blackbox_flight("run-tamper")
    assert report["timeline_chain_valid"] is False
    assert report["verdict"] == "tampered_or_invalid_chain"
