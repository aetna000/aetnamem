from __future__ import annotations

import platform
import secrets
import subprocess


class MacKeychain:
    """Small wrapper around the macOS ``security`` command."""

    def __init__(self, service: str = "aetnamem") -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("MacKeychain is only supported on macOS")
        self.service = service

    def get(self, account: str) -> str | None:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", self.service, "-a", account, "-w"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def set(self, account: str, value: str) -> None:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self.service,
                "-a",
                account,
                "-w",
                value,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

    def ensure(self, account: str, *, nbytes: int = 32) -> str:
        existing = self.get(account)
        if existing:
            return existing
        value = secrets.token_hex(nbytes)
        self.set(account, value)
        return value
