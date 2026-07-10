"""Root-confined reference filesystem adapter.

This adapter is deliberately narrow: UTF-8 file writes and file deletion.
It never exposes a raw filesystem handle to agent code, refuses symlink/root
escape, uses compare-before-write preconditions, and verifies compensation.
Filesystem observers and hooks may still produce external side effects, so
the classification is ``verified_compensatable``, never exact transaction.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any

from aetnamem.actions.adapters.base import ActionContext
from aetnamem.actions.models import (
    AdapterReceipt,
    EffectClass,
    PreparedOperation,
    VerificationResult,
)


class FilesystemAdapter:
    name = "filesystem"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"filesystem adapter root is not a directory: {self.root}")

    def manifest(self) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "version": "1",
            "root": str(self.root),
            "operations": ["write_text", "delete_file"],
            "effect_class": EffectClass.VERIFIED_COMPENSATABLE.value,
            "supports_idempotency": True,
            "supports_verification": True,
            "supports_verified_compensation": True,
        }

    def prepare(
        self,
        operation: str,
        arguments: dict[str, Any],
        context: ActionContext,
    ) -> PreparedOperation:
        if operation not in {"write_text", "delete_file"}:
            raise ValueError(f"unsupported filesystem operation: {operation}")
        target, relative = self._target(arguments.get("path"))
        before = self._snapshot(target)
        normalized: dict[str, Any] = {"path": relative}
        sensitive: tuple[str, ...] = ()
        if operation == "write_text":
            content = arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("write_text requires string content")
            normalized["content"] = content
            after_sha256 = _sha256(content.encode("utf-8"))
            sensitive = ("content",)
        else:
            after_sha256 = None

        return PreparedOperation(
            adapter=self.name,
            operation=operation,
            arguments=normalized,
            preview={
                "path": relative,
                "before_sha256": before["sha256"],
                "after_sha256": after_sha256,
                "before_exists": before["exists"],
                "after_exists": operation == "write_text",
                "after_mode": before["mode"] if before["exists"] else 0o600,
            },
            preconditions=before,
            effect_class=EffectClass.VERIFIED_COMPENSATABLE,
            sensitive_fields=sensitive,
        )

    def revalidate(self, prepared: PreparedOperation) -> VerificationResult:
        target, _ = self._target(prepared.arguments["path"])
        current = self._snapshot(target)
        expected = prepared.preconditions
        matches = (
            current["exists"] == expected.get("exists")
            and current["sha256"] == expected.get("sha256")
            and current["kind"] == expected.get("kind")
            and current["mode"] == expected.get("mode")
        )
        return VerificationResult(
            verified=matches,
            observation=_public_snapshot(current),
            reason=None if matches else "filesystem precondition changed",
        )

    def execute(
        self,
        prepared: PreparedOperation,
        *,
        idempotency_key: str,
    ) -> AdapterReceipt:
        target, relative = self._target(prepared.arguments["path"])
        if not target.parent.is_dir():
            raise FileNotFoundError(
                f"parent directory must already exist for guarded writes: {target.parent}"
            )

        if prepared.operation == "write_text":
            content = prepared.arguments["content"].encode("utf-8")
            expected_after = prepared.preview["after_sha256"]
            current = self._snapshot(target)
            if current["sha256"] != expected_after:
                self._atomic_write(target, content)
                if prepared.preconditions.get("mode") is not None:
                    target.chmod(int(prepared.preconditions["mode"]))
        elif prepared.operation == "delete_file":
            if target.exists() or target.is_symlink():
                target.unlink()
        else:  # defensive against forged persisted payloads
            raise ValueError(f"unsupported filesystem operation: {prepared.operation}")

        observed = self._snapshot(target)
        return AdapterReceipt(
            provider_request_id=idempotency_key,
            result={"path": relative, "operation": prepared.operation},
            observed_after=_public_snapshot(observed),
        )

    def verify(
        self,
        prepared: PreparedOperation,
        receipt: AdapterReceipt,
    ) -> VerificationResult:
        target, _ = self._target(prepared.arguments["path"])
        current = self._snapshot(target)
        expected_exists = bool(prepared.preview["after_exists"])
        expected_sha = prepared.preview["after_sha256"]
        expected_mode = prepared.preview["after_mode"] if expected_exists else None
        verified = (
            current["exists"] == expected_exists
            and current["sha256"] == expected_sha
            and current["mode"] == expected_mode
        )
        return VerificationResult(
            verified=verified,
            observation=_public_snapshot(current),
            reason=None if verified else "filesystem postcondition not observed",
        )

    def compensate(
        self,
        prepared: PreparedOperation,
        receipt: AdapterReceipt,
        *,
        idempotency_key: str,
    ) -> AdapterReceipt:
        target, relative = self._target(prepared.arguments["path"])
        current_verification = self.verify(prepared, receipt)
        if not current_verification.verified:
            raise RuntimeError(
                "refusing compensation because the file changed after execution"
            )
        before = prepared.preconditions
        if before["exists"]:
            encoded = before.get("content_b64")
            if not isinstance(encoded, str):
                raise RuntimeError("persisted before-image is unavailable")
            self._atomic_write(target, base64.b64decode(encoded.encode("ascii")))
            if before.get("mode") is not None:
                target.chmod(int(before["mode"]))
        elif target.exists() or target.is_symlink():
            target.unlink()
        observed = self._snapshot(target)
        return AdapterReceipt(
            provider_request_id=idempotency_key,
            result={"path": relative, "compensated": True},
            observed_after=_public_snapshot(observed),
        )

    def verify_compensation(
        self,
        prepared: PreparedOperation,
        receipt: AdapterReceipt,
    ) -> VerificationResult:
        target, _ = self._target(prepared.arguments["path"])
        current = self._snapshot(target)
        before = prepared.preconditions
        verified = (
            current["exists"] == before["exists"]
            and current["sha256"] == before["sha256"]
            and current["kind"] == before["kind"]
            and current["mode"] == before["mode"]
        )
        return VerificationResult(
            verified=verified,
            observation=_public_snapshot(current),
            reason=None if verified else "filesystem before-state was not restored",
        )

    def _target(self, relative_value: Any) -> tuple[Path, str]:
        if not isinstance(relative_value, str) or not relative_value.strip():
            raise ValueError("filesystem operation requires a relative path")
        relative = Path(relative_value)
        if relative.is_absolute():
            raise ValueError("filesystem path must be relative to the configured root")
        lexical_target = self.root / relative
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("symbolic-link paths are not supported")
        target = lexical_target.resolve(strict=False)
        try:
            normalized = str(target.relative_to(self.root))
        except ValueError as exc:
            raise ValueError("filesystem path escapes the configured root") from exc
        return target, normalized

    @staticmethod
    def _snapshot(target: Path) -> dict[str, Any]:
        if not target.exists() and not target.is_symlink():
            return {
                "exists": False,
                "kind": "absent",
                "sha256": None,
                "content_b64": None,
                "mode": None,
            }
        if target.is_symlink():
            raise ValueError("symbolic-link targets are not supported")
        if not target.is_file():
            raise ValueError("guarded filesystem operations support regular files only")
        data = target.read_bytes()
        return {
            "exists": True,
            "kind": "file",
            "sha256": _sha256(data),
            "content_b64": base64.b64encode(data).decode("ascii"),
            "mode": target.stat().st_mode & 0o777,
        }

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".aetna000-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": snapshot["exists"],
        "kind": snapshot["kind"],
        "sha256": snapshot["sha256"],
        "mode": snapshot["mode"],
    }
