from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from aetnamem import Memory


def test_remember_and_audit_append_roll_back_together(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = Memory(":memory:")
    original = memory.store.append_audit_event
    calls = 0

    def fail_second_event(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated audit failure")
        return original(**kwargs)

    monkeypatch.setattr(memory.store, "append_audit_event", fail_second_event)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        memory.remember("user-1", "My favorite color is teal.")

    assert memory.store.list_episodes("user-1") == []
    assert memory.list("user-1", include_inactive=True) == []
    assert memory.store.list_audit_events("user-1") == []


def test_forget_purge_and_receipt_event_roll_back_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Memory(":memory:")
    memory.remember("user-1", "My backup email is private@example.com.")
    original = memory.store.append_audit_event

    def fail_forget(**kwargs):
        if kwargs.get("event_type") == "memory.forget":
            raise RuntimeError("simulated receipt failure")
        return original(**kwargs)

    monkeypatch.setattr(memory.store, "append_audit_event", fail_forget)
    with pytest.raises(RuntimeError, match="simulated receipt failure"):
        memory.forget("user-1", utterance="Forget my backup email.")

    [record] = memory.list("user-1")
    assert record["content"]
    [episode] = memory.store.list_episodes("user-1")
    assert episode["message"] != "[purged]"
    assert memory.verify("user-1")["valid"] is True


def test_concurrent_connections_cannot_fork_audit_head(tmp_path: Path) -> None:
    path = tmp_path / "mem.db"

    def write(worker: int) -> None:
        memory = Memory(path)
        try:
            for index in range(15):
                memory.log_action(
                    "user-1",
                    "worker_event",
                    {"worker": worker, "index": index},
                )
        finally:
            memory.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(4)))

    memory = Memory(path)
    assert len(memory.store.list_audit_events("user-1")) == 60
    assert memory.store.verify_audit_chain("user-1") is True
