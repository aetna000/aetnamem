"""Canonical serialization and hashing.

Everything that is hashed — audit events, checkpoints, deletion receipts —
must serialize through these two functions, and the recipe is frozen in
docs/audit-log-spec.md so third-party verifiers can reimplement it without
reading this code.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()
