from __future__ import annotations

import re


TESTED_OPENCLAW_VERSIONS = ("2026.7.1-2",)

_VERSION_RE = re.compile(r"(?<!\d)(\d{4})\.(\d+)\.(\d+)(?:-(\d+))?(?!\d)")


def parse_openclaw_version(value: str) -> tuple[int, int, int, int | None]:
    match = _VERSION_RE.search(value.strip())
    if match is None:
        raise ValueError(f"could not parse OpenClaw version: {value!r}")
    year, minor, patch, suffix = match.groups()
    return int(year), int(minor), int(patch), int(suffix) if suffix else None


def normalize_openclaw_version(value: str) -> str:
    year, minor, patch, suffix = parse_openclaw_version(value)
    base = f"{year}.{minor}.{patch}"
    return f"{base}-{suffix}" if suffix is not None else base


def evaluate_host_version(value: str) -> str:
    parsed = parse_openclaw_version(value)
    tested = [parse_openclaw_version(item) for item in TESTED_OPENCLAW_VERSIONS]
    if parsed in tested:
        return "tested"
    if any(parsed[:2] == candidate[:2] for candidate in tested):
        return "untested_patch"
    return "untested"
