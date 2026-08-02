from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator

from aetnamem.control.models import ControlState, fail_closed_state


def load_state(path: str | Path) -> ControlState:
    source = _safe_path(path, must_exist=True)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("migration state must be a JSON object")
    return ControlState.from_dict(value)


def load_effective_state(path: str | Path) -> tuple[ControlState, str | None]:
    try:
        return load_state(path), None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return fail_closed_state(str(Path(path).expanduser()), warning=str(exc)), str(exc)


def write_state(path: str | Path, state: ControlState) -> ControlState:
    target = _safe_path(path, must_exist=False)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.parent.is_symlink():
        raise ValueError("migration state parent must not be a symlink")
    normalized = state.with_digest()
    serialized = json.dumps(normalized.to_dict(), indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        os.chmod(target, 0o600)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return normalized


@contextmanager
def state_lock(path: str | Path) -> Iterator[None]:
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = target.with_suffix(target.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - supported targets provide fcntl
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover
            pass
        os.close(descriptor)


def _safe_path(path: str | Path, *, must_exist: bool) -> Path:
    target = Path(path).expanduser()
    if target.is_symlink():
        raise ValueError("migration state path must not be a symlink")
    resolved = target.resolve(strict=False)
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    if resolved.exists():
        mode = resolved.stat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("migration state path must be a regular file")
    return resolved
