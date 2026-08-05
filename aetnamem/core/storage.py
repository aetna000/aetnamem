from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Literal


SQLITE_HEADER = b"SQLite format 3\x00"
POLICY_FORMAT = "aetnamem-household-encryption-v1"
POLICY_STATES = {
    "plaintext",
    "migration-prepared",
    "encrypting",
    "encrypted",
    "decrypting",
}


@dataclass(frozen=True)
class HouseholdPolicy:
    database_path: str
    state_path: Path | None
    lock_path: Path | None
    state: str = "plaintext"
    backend: str | None = None
    key_id: str | None = None
    control_kdf_salt: str | None = None

    @classmethod
    def memory(cls) -> "HouseholdPolicy":
        return cls(database_path=":memory:", state_path=None, lock_path=None)

    @classmethod
    def load(cls, database_path: str | Path) -> "HouseholdPolicy":
        if str(database_path) == ":memory:":
            return cls.memory()
        path = Path(database_path).expanduser().resolve(strict=False)
        state_path = Path(f"{path}.encryption.json")
        lock_path = Path(f"{path}.lock")
        if not state_path.exists():
            return cls(str(path), state_path, lock_path)
        try:
            value = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid household encryption state: {state_path}") from exc
        if not isinstance(value, dict) or value.get("format") != POLICY_FORMAT:
            raise ValueError(f"unsupported household encryption state: {state_path}")
        state = str(value.get("state") or "")
        if state not in POLICY_STATES:
            raise ValueError(f"invalid household encryption state value: {state!r}")
        backend = value.get("backend")
        if backend not in {"file", "keyring"}:
            raise ValueError("household encryption backend must be file or keyring")
        key_id = str(value.get("key_id") or "")
        salt = str(value.get("control_kdf_salt") or "")
        if not key_id or not salt:
            raise ValueError("household encryption state is missing key identity metadata")
        return cls(str(path), state_path, lock_path, state, str(backend), key_id, salt)

    def document(self) -> dict[str, Any]:
        if self.state_path is None:
            raise ValueError(":memory: has no persistent household policy")
        return {
            "format": POLICY_FORMAT,
            "database_path": self.database_path,
            "state": self.state,
            "backend": self.backend,
            "key_id": self.key_id,
            "control_kdf_salt": self.control_kdf_salt,
        }

    def with_state(self, state: str) -> "HouseholdPolicy":
        if state not in POLICY_STATES:
            raise ValueError(f"invalid household state: {state}")
        return HouseholdPolicy(
            self.database_path,
            self.state_path,
            self.lock_path,
            state,
            self.backend,
            self.key_id,
            self.control_kdf_salt,
        )

    def write(self) -> None:
        if self.state_path is None:
            raise ValueError(":memory: policy cannot be written")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp")
        temporary.write_text(
            json.dumps(self.document(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, self.state_path)


class HouseholdLock:
    def __init__(self, policy: HouseholdPolicy, *, exclusive: bool = False) -> None:
        self.policy = policy
        self.exclusive = exclusive
        self._descriptor: int | None = None

    def acquire(self) -> "HouseholdLock":
        if self.policy.lock_path is None:
            return self
        self.policy.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.policy.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        operation = (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError as exc:
            os.close(descriptor)
            action = "migrate" if self.exclusive else "open"
            raise RuntimeError(
                f"cannot {action} AetnaMem household while another process holds {self.policy.lock_path}"
            ) from exc
        self._descriptor = descriptor
        return self

    def close(self) -> None:
        if self._descriptor is None:
            return
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None

    def __enter__(self) -> "HouseholdLock":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _header(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size == 0:
        return b""
    with path.open("rb") as handle:
        return handle.read(len(SQLITE_HEADER))


def connect(
    path: str | Path,
    *,
    policy: HouseholdPolicy,
    mode: Literal["runtime", "migration"] = "runtime",
    isolation_level: str | None = None,
):
    if str(path) == ":memory:":
        if policy.database_path != ":memory:" or policy.state != "plaintext":
            raise ValueError(":memory: requires the explicit lock-free plaintext policy")
        return sqlite3.connect(":memory:", isolation_level=isolation_level)
    target = Path(path).expanduser().resolve(strict=False)
    state = policy.state
    header = _header(target)
    if mode == "runtime" and state in {"migration-prepared", "encrypting", "decrypting"}:
        raise RuntimeError(
            f"household migration is {state}; migration tooling is not shipped in "
            "this experimental build, so restore a consistent plaintext backup"
        )
    if state == "plaintext":
        if header and header != SQLITE_HEADER:
            raise RuntimeError(
                "household state says plaintext but the database header is not plaintext SQLite"
            )
        return sqlite3.connect(str(target), isolation_level=isolation_level)
    if state == "encrypted":
        if header == SQLITE_HEADER:
            raise RuntimeError(
                "household state says encrypted but the database has a plaintext SQLite header"
            )
        try:
            from sqlcipher3 import dbapi2 as sqlcipher
        except ImportError as exc:
            raise RuntimeError(
                "encrypted household requires a separately provisioned sqlcipher3 runtime"
            ) from exc
        from aetnamem.core.keys import resolve_database_key

        key = resolve_database_key(policy)
        connection = sqlcipher.connect(str(target), isolation_level=isolation_level)
        connection.execute(f"PRAGMA key = \"x'{key}'\"")
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except Exception as exc:
            connection.close()
            raise RuntimeError(
                "encrypted household could not be opened; the key is missing or incorrect"
            ) from exc
        return connection
    if mode != "migration":
        raise RuntimeError(f"household state {state!r} is not available at runtime")
    raise RuntimeError("migration code must choose its source and destination connection explicitly")


def row_factory_for(policy: HouseholdPolicy):
    if policy.state != "encrypted":
        return sqlite3.Row
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except ImportError as exc:
        raise RuntimeError("encrypted household requires sqlcipher3") from exc
    return sqlcipher.Row
