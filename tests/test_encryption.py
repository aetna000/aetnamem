from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetnamem import Memory
from aetnamem.core.keys import initialize_keys, key_status, resolve_database_key
from aetnamem.core.storage import HouseholdLock, HouseholdPolicy


def test_keys_init_is_inert_for_existing_plaintext_database(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "memory.db"
    memory = Memory(database)
    try:
        memory.remember("user", "I prefer TypeScript", force=True)
    finally:
        memory.close()
    before = database.read_bytes()
    key_path = tmp_path / "keys" / "db.key"
    monkeypatch.setattr("aetnamem.core.keys.DEFAULT_KEY_PATH", key_path)

    status = initialize_keys(database, backend="file")

    assert status["state"] == "plaintext"
    assert status["backend"] == "file"
    assert status["key_exposed"] is False
    assert database.read_bytes() == before
    assert key_path.stat().st_mode & 0o777 == 0o600
    state = json.loads(Path(f"{database}.encryption.json").read_text(encoding="utf-8"))
    assert state["state"] == "plaintext"
    assert state["key_id"]
    assert state["control_kdf_salt"]
    reopened = Memory(database)
    try:
        assert reopened.recall("user", "TypeScript")
    finally:
        reopened.close()


def test_environment_key_overrides_recorded_backend(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "memory.db"
    key_path = tmp_path / "keys" / "db.key"
    monkeypatch.setattr("aetnamem.core.keys.DEFAULT_KEY_PATH", key_path)
    initialize_keys(database, backend="file")
    override = "ab" * 32
    monkeypatch.setenv("AETNAMEM_DB_KEY", override)

    policy = HouseholdPolicy.load(database)

    assert resolve_database_key(policy) == override
    assert key_status(database)["source"] == "environment"


def test_runtime_refuses_in_progress_or_header_mismatch(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    memory = Memory(database)
    memory.close()
    policy = HouseholdPolicy.load(database)
    prepared = HouseholdPolicy(
        policy.database_path,
        policy.state_path,
        policy.lock_path,
        "encrypting",
        "file",
        "key_test",
        "cd" * 32,
    )
    prepared.write()
    with pytest.raises(RuntimeError, match="migration tooling is not shipped"):
        Memory(database)

    prepared.with_state("encrypted").write()
    with pytest.raises(RuntimeError, match="plaintext SQLite header"):
        Memory(database)


def test_household_lock_blocks_migration_and_new_holders(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    policy = HouseholdPolicy.load(database)
    memory = Memory(database)
    try:
        with pytest.raises(RuntimeError, match="another process"):
            HouseholdLock(policy, exclusive=True).acquire()
    finally:
        memory.close()

    migration = HouseholdLock(policy, exclusive=True).acquire()
    try:
        with pytest.raises(RuntimeError, match="another process"):
            Memory(database)
    finally:
        migration.close()
