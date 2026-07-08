"""Policy gates: the small set of rules every candidate fact must pass.

These functions are the product. They are deterministic, source-agnostic, and
unit-tested directly — nothing in here may reference the vocabulary of any
particular benchmark scenario.
"""

from __future__ import annotations

import re
from typing import Any

TRUSTED_SOURCE_TYPES = frozenset({"user_message"})

TRUST_TIER_USER = "trusted_user"
TRUST_TIER_CONFIRMED = "user_confirmed"
TRUST_TIER_UNTRUSTED = "untrusted_content"

_EMBEDDED_SOURCE_RE = re.compile(
    r"<(?P<tag>webpage|web_page|tool_output|tool(?:_[a-z]+)*)\b", re.I
)

_FORGET_RE = re.compile(r"\b(?:forget|delete|remove|erase)\b", re.I)

_NEEDLE_RE = re.compile(
    r"\b(?:forget|delete|remove|erase)\b(?:\s+(?:that|about|what))?\s+(?P<rest>.+)",
    re.I | re.S,
)

_POSSESSIVE_PREFIX_RE = re.compile(r"^(?:my|our|the|his|her|their)\s+", re.I)

_WORD_RE = re.compile(r"[a-z0-9@.\-+_]+")


def classify_source(message: str) -> str:
    """Classify where a message's content really comes from.

    A user turn that embeds third-party content (a fetched webpage, a tool
    result) is classified by the embedded content, because that is what an
    extractor would be reading.
    """
    match = _EMBEDDED_SOURCE_RE.search(message)
    if match is None:
        return "user_message"
    tag = match.group("tag").lower()
    if tag in ("webpage", "web_page"):
        return "webpage"
    return "tool_output"


def trust_tier_for_source(source_type: str) -> str:
    if source_type in TRUSTED_SOURCE_TYPES:
        return TRUST_TIER_USER
    return TRUST_TIER_UNTRUSTED


def initial_status(trust_tier: str) -> str:
    """Untrusted extractions land quarantined; only promote() activates them."""
    if trust_tier in (TRUST_TIER_USER, TRUST_TIER_CONFIRMED):
        return "active"
    return "quarantined"


def normalize_content(text: str) -> str:
    tokens = (token.strip("._-+@") for token in _WORD_RE.findall(text.lower()))
    return " ".join(token for token in tokens if token)


def find_duplicate(
    content: str,
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return an existing record whose content is equivalent, if any."""
    norm = normalize_content(content)
    if not norm:
        return None
    for record in records:
        if normalize_content(str(record.get("content") or "")) == norm:
            return record
    return None


def records_to_supersede(
    fact_key: str | None,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Active records that a new fact with `fact_key` replaces.

    Supersession is keyed on the extracted fact slot (e.g. "preferred
    airport", "backup email"), never on content keywords.
    """
    if not fact_key:
        return []
    return [record for record in records if record.get("fact_key") == fact_key]


def is_forget_request(message: str) -> bool:
    """True only for deletion requests issued by the user themselves.

    Embedded webpage/tool content can never trigger deletion — that would be
    an injection vector.
    """
    if classify_source(message) != "user_message":
        return False
    return bool(_FORGET_RE.search(message))


def forget_needle(utterance: str) -> str:
    """Reduce a forget utterance to the phrase identifying what to delete."""
    text = utterance.strip()
    match = _NEEDLE_RE.search(text)
    rest = match.group("rest") if match else text
    rest = _POSSESSIVE_PREFIX_RE.sub("", rest.strip())
    rest = re.sub(r"\s*\b(?:please|now)\b\s*$", "", rest, flags=re.I)
    return rest.strip(" .?!").lower()
