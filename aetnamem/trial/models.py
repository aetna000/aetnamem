from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex


STATE_FORMAT = "aetnamem-safe-switch-state-v1"


class TrialMode(str, Enum):
    OFF = "off"
    CAPTURE = "capture"
    PREVIEW = "preview"
    CANARY = "canary"
    ACTIVE = "active"

    @property
    def captures(self) -> bool:
        return self is not TrialMode.OFF

    @property
    def previews(self) -> bool:
        return self in {TrialMode.PREVIEW, TrialMode.CANARY, TrialMode.ACTIVE}

    @property
    def influences_agent(self) -> bool:
        return self in {TrialMode.CANARY, TrialMode.ACTIVE}


@dataclass(frozen=True)
class TrialState:
    trial_id: str
    host: str
    subject_id: str
    trial_dir: str
    mode: TrialMode
    revision: int
    created_at: str
    updated_at: str
    canary_turns: int = 0
    format: str = STATE_FORMAT
    state_sha256: str = ""

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "trial_id": self.trial_id,
            "host": self.host,
            "subject_id": self.subject_id,
            "trial_dir": self.trial_dir,
            "mode": self.mode.value,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "canary_turns": self.canary_turns,
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "state_sha256": self.digest}

    def with_digest(self) -> "TrialState":
        return replace(self, state_sha256=self.digest)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TrialState":
        if value.get("format") != STATE_FORMAT:
            raise ValueError(f"unsupported trial state format: {value.get('format')!r}")
        try:
            state = cls(
                trial_id=str(value["trial_id"]),
                host=str(value["host"]),
                subject_id=str(value["subject_id"]),
                trial_dir=str(value["trial_dir"]),
                mode=TrialMode(str(value["mode"])),
                revision=int(value["revision"]),
                created_at=str(value["created_at"]),
                updated_at=str(value["updated_at"]),
                canary_turns=int(value.get("canary_turns", 0)),
                state_sha256=str(value.get("state_sha256") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("malformed trial state") from exc
        if not state.trial_id or not state.subject_id or state.revision < 0:
            raise ValueError("invalid trial state identity or revision")
        if state.canary_turns < 0:
            raise ValueError("canary_turns must not be negative")
        if state.state_sha256 != state.digest:
            raise ValueError("trial state digest mismatch")
        return state

    def public_status(self, *, warning: str | None = None) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "writes_local_data": self.mode.captures,
            "changes_model_context": self.mode.influences_agent,
            "makes_extra_provider_calls": False,
            "warning": warning,
        }


def fail_closed_state(path: str, *, warning: str) -> TrialState:
    """Return a non-persistent OFF state for a missing or corrupt state file."""
    return TrialState(
        trial_id="unavailable",
        host="unknown",
        subject_id="unknown",
        trial_dir=str(path),
        mode=TrialMode.OFF,
        revision=0,
        created_at="",
        updated_at="",
    ).with_digest()
