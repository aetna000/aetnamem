from __future__ import annotations

from contextlib import AbstractContextManager
import hmac
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import tempfile

from aetnamem.service.secrets import MacKeychain


class EncryptedDatabaseManager(AbstractContextManager["EncryptedDatabaseManager"]):
    """Mac-only at-rest encryption wrapper for the SQLite database.

    The live SQLite database is plaintext while the local sidecar is running.
    On clean shutdown it is sealed to ``encrypted_path`` and the runtime copy is
    removed. This is not a SQLCipher replacement; it is a zero-Python-dependency
    macOS protection layer for a desktop app whose idle state should not leave a
    readable SQLite file on disk.
    """

    def __init__(
        self,
        encrypted_path: str | Path,
        *,
        keychain_service: str = "aetnamem",
        keychain_account: str = "database-key",
    ) -> None:
        self.encrypted_path = Path(encrypted_path).expanduser()
        self.hmac_path = self.encrypted_path.with_suffix(self.encrypted_path.suffix + ".hmac")
        self.keychain = MacKeychain(keychain_service)
        self.keychain_account = keychain_account
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self.runtime_path: Path | None = None
        self._key: str | None = None

    def __enter__(self) -> "EncryptedDatabaseManager":
        if shutil.which("openssl") is None:
            raise RuntimeError("openssl is required for --encrypted-db")
        self._key = self.keychain.ensure(self.keychain_account)
        self._tmpdir = tempfile.TemporaryDirectory(prefix="aetnamem-db-")
        self.runtime_path = Path(self._tmpdir.name) / "memories.db"
        if self.encrypted_path.exists():
            self._verify_hmac()
            self._openssl("decrypt", self.encrypted_path, self.runtime_path)
        else:
            self.encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        return self

    def seal(self) -> None:
        if self.runtime_path is None or self._key is None:
            return
        if not self.runtime_path.exists():
            return
        tmp = self.encrypted_path.with_suffix(self.encrypted_path.suffix + ".tmp")
        self._openssl("encrypt", self.runtime_path, tmp)
        digest = hmac.new(self._key.encode("utf-8"), tmp.read_bytes(), sha256).hexdigest()
        tmp.replace(self.encrypted_path)
        self.hmac_path.write_text(digest + "\n", encoding="utf-8")

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()

    def _verify_hmac(self) -> None:
        if self._key is None:
            raise RuntimeError("encryption key is not loaded")
        if not self.hmac_path.exists():
            raise RuntimeError("encrypted database HMAC is missing")
        expected = self.hmac_path.read_text(encoding="utf-8").strip()
        actual = hmac.new(self._key.encode("utf-8"), self.encrypted_path.read_bytes(), sha256).hexdigest()
        if not hmac.compare_digest(expected, actual):
            raise RuntimeError("encrypted database HMAC mismatch")

    def _openssl(self, mode: str, src: Path, dst: Path) -> None:
        if self._key is None:
            raise RuntimeError("encryption key is not loaded")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=True) as key_file:
            key_file.write(self._key)
            key_file.flush()
            command = [
                "openssl",
                "enc",
                "-aes-256-cbc",
                "-pbkdf2",
                "-salt",
                "-in",
                str(src),
                "-out",
                str(dst),
                "-pass",
                f"file:{key_file.name}",
            ]
            if mode == "decrypt":
                command.insert(2, "-d")
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=True)
