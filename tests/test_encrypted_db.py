from __future__ import annotations

from pathlib import Path
import shutil

import pytest

import aetnamem.service.encrypted_db as encrypted_db


class FakeKeychain:
    def __init__(self, _service: str = "aetnamem") -> None:
        self.value = "a" * 64

    def ensure(self, _account: str) -> str:
        return self.value


@pytest.fixture
def manager_factory(monkeypatch):
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required for encrypted database tests")
    monkeypatch.setattr(encrypted_db, "MacKeychain", FakeKeychain)
    return encrypted_db.EncryptedDatabaseManager


def test_encrypted_database_roundtrip(tmp_path: Path, manager_factory) -> None:
    sealed = tmp_path / "memories.db.enc"
    original = b"SQLite format 3\x00" + bytes(range(256)) * 8

    with manager_factory(sealed) as manager:
        manager.runtime_path.write_bytes(original)
        manager.seal()

    assert sealed.read_bytes() != original
    assert (tmp_path / "memories.db.enc.hmac").is_file()

    with manager_factory(sealed) as restored:
        assert restored.runtime_path.read_bytes() == original


def test_encrypted_database_rejects_tampering(tmp_path: Path, manager_factory) -> None:
    sealed = tmp_path / "memories.db.enc"

    with manager_factory(sealed) as manager:
        manager.runtime_path.write_bytes(b"SQLite format 3\x00test data")
        manager.seal()

    tampered = bytearray(sealed.read_bytes())
    tampered[-1] ^= 1
    sealed.write_bytes(tampered)

    with pytest.raises(RuntimeError, match="HMAC mismatch"):
        with manager_factory(sealed):
            pass


def test_encrypted_database_requires_hmac(tmp_path: Path, manager_factory) -> None:
    sealed = tmp_path / "memories.db.enc"

    with manager_factory(sealed) as manager:
        manager.runtime_path.write_bytes(b"SQLite format 3\x00test data")
        manager.seal()

    (tmp_path / "memories.db.enc.hmac").unlink()

    with pytest.raises(RuntimeError, match="HMAC is missing"):
        with manager_factory(sealed):
            pass
