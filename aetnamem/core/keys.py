from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat
import uuid
from typing import Any

from aetnamem.core.storage import HouseholdPolicy


KEY_ENV = "AETNAMEM_DB_KEY"
DEFAULT_KEY_PATH = Path.home() / ".aetnamem" / "keys" / "db.key"
KEYRING_SERVICE = "aetnamem"


def _validate_key(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError("AetnaMem database key must be exactly 64 hexadecimal characters")
    return normalized


def _write_file_key(value: str, path: Path | None = None) -> None:
    path = path or DEFAULT_KEY_PATH
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        raise ValueError(f"database key already exists: {path}")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")


def _read_file_key(path: Path | None = None) -> str:
    path = path or DEFAULT_KEY_PATH
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError(f"database key permissions are unsafe ({oct(mode)}); require 0600")
    return _validate_key(path.read_text(encoding="utf-8"))


def initialize_keys(database_path: str | Path, *, backend: str = "file") -> dict[str, Any]:
    if backend not in {"file", "keyring"}:
        raise ValueError("key backend must be file or keyring")
    policy = HouseholdPolicy.load(database_path)
    if policy.state_path is None:
        raise ValueError("persistent keys cannot be initialized for :memory:")
    if policy.state_path.exists():
        return key_status(database_path)
    key = secrets.token_hex(32)
    key_id = f"key_{uuid.uuid4().hex}"
    if backend == "file":
        if DEFAULT_KEY_PATH.exists():
            key = _read_file_key()
        else:
            _write_file_key(key)
    else:
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("keyring backend requires the keyring package") from exc
        keyring.set_password(KEYRING_SERVICE, key_id, key)
    created = HouseholdPolicy(
        database_path=str(Path(database_path).expanduser().resolve(strict=False)),
        state_path=policy.state_path,
        lock_path=policy.lock_path,
        state="plaintext",
        backend=backend,
        key_id=key_id,
        control_kdf_salt=secrets.token_hex(32),
    )
    created.write()
    return key_status(database_path)


def resolve_database_key(policy: HouseholdPolicy) -> str:
    override = os.environ.get(KEY_ENV)
    if override:
        return _validate_key(override)
    if policy.backend == "file":
        try:
            return _read_file_key()
        except FileNotFoundError as exc:
            raise RuntimeError(f"database key file is missing: {DEFAULT_KEY_PATH}") from exc
    if policy.backend == "keyring":
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("keyring backend requires the keyring package") from exc
        value = keyring.get_password(KEYRING_SERVICE, str(policy.key_id))
        if value is None:
            raise RuntimeError(f"database key {policy.key_id} is missing from keyring")
        return _validate_key(value)
    raise RuntimeError("household has no initialized key backend")


def key_status(database_path: str | Path) -> dict[str, Any]:
    policy = HouseholdPolicy.load(database_path)
    source = None
    available = False
    if os.environ.get(KEY_ENV):
        _validate_key(os.environ[KEY_ENV])
        source, available = "environment", True
    elif policy.backend == "file":
        source = "file"
        try:
            _read_file_key()
            available = True
        except (FileNotFoundError, RuntimeError, ValueError):
            available = False
    elif policy.backend == "keyring":
        source = "keyring"
        try:
            import keyring

            available = keyring.get_password(KEYRING_SERVICE, str(policy.key_id)) is not None
        except ImportError:
            available = False
    return {
        "format": "aetnamem-key-status-v1",
        "database_path": policy.database_path,
        "state": policy.state,
        "backend": policy.backend,
        "key_id": policy.key_id,
        "source": source,
        "available": available,
        "key_exposed": False,
    }
