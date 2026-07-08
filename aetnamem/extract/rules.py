"""Deterministic rules extractor.

v0 extraction is intentionally pattern-based, not model-based, so benchmark
failures are debuggable. The patterns are generic sentence shapes ("my X is
Y", "use Y as my X", "remember that ...", "I avoid X") — they must never
encode the vocabulary of a specific benchmark scenario.

Every candidate carries a `fact_key`: the normalized fact slot ("preferred
airport", "backup email", "favorite color") that the supersession gate keys
on. Facts without a recognizable slot get `fact_key=None` and never supersede
anything implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from aetnamem.core.policy import (
    classify_source,
    initial_status,
    is_forget_request,
    trust_tier_for_source,
)


@dataclass(frozen=True)
class CandidateFact:
    content: str
    confidence: float
    source_type: str
    trust_tier: str
    fact_key: str | None = None
    scope: str = "user_private"


_REMEMBER_RE = re.compile(r"\bremember that\b\s*(?P<fact>.+)", re.I | re.S)

# "my preferred airport is SFO", "my backup email is a@b.com"
_COPULAR_RE = re.compile(
    r"\bmy\s+(?P<attr>[a-z][a-z0-9 ]{1,60}?)\s+(?:is|are)\s+(?P<value>\S.*?)\s*$",
    re.I,
)

# "use OAK as my preferred airport (going forward)"
_USE_AS_RE = re.compile(
    r"\buse\s+(?P<value>\S.*?)\s+as\s+my\s+(?P<attr>[a-z][a-z0-9 ]{1,60}?)"
    r"(?:\s+(?:going\s+forward|from\s+now\s+on))?\s*[.?!]*\s*$",
    re.I,
)

# "I avoid beef at business dinners", "I don't eat shellfish"
_AVOID_RE = re.compile(
    r"\bI\s+(?:avoid|never\s+eat|don'?t\s+eat|do\s+not\s+eat|dislike)\s+"
    r"(?P<what>[^.?!\n]+)",
    re.I,
)

_EMBEDDED_BLOCK_RE = re.compile(
    r"<(?P<tag>webpage|web_page|tool_output|tool(?:_[a-z]+)*)\b[^>]*>"
    r"(?P<body>.*?)(?:</(?P=tag)>|$)",
    re.I | re.S,
)

_QUESTION_LEAD_RE = re.compile(
    r"^\s*(?:am|are|is|do|does|did|can|could|should|would|will|what|which|who|where|when|why|how)\b",
    re.I,
)


def extract_facts(message: str, *, source_type: str | None = None) -> list[CandidateFact]:
    """Extract at most one candidate fact from a message.

    Trusted user statements yield active candidates. Content embedded from
    untrusted sources is still extracted — with low confidence and an
    untrusted trust tier — so the policy layer can quarantine it with full
    provenance instead of silently dropping it.
    """
    source = source_type or classify_source(message)

    if source != "user_message":
        body = _embedded_body(message)
        return _candidates_from_text(body, source) if body else []

    if is_forget_request(message):
        return []
    return _candidates_from_text(message, source)


def _candidates_from_text(text: str, source_type: str) -> list[CandidateFact]:
    trust_tier = trust_tier_for_source(source_type)
    trusted = initial_status(trust_tier) == "active"

    parsed = _parse_statement(text)
    if parsed is None:
        return []
    content, fact_key, confidence = parsed

    return [
        CandidateFact(
            content=content,
            confidence=confidence if trusted else min(confidence, 0.3),
            source_type=source_type,
            trust_tier=trust_tier,
            fact_key=fact_key,
        )
    ]


def _parse_statement(text: str) -> tuple[str, str | None, float] | None:
    """Return (content, fact_key, confidence) for a declarative statement."""
    remember = _REMEMBER_RE.search(text)
    if remember:
        payload = _clean(remember.group("fact"))
        structured = _parse_slot(payload)
        if structured:
            return structured
        if payload:
            return _third_person(payload), None, 0.85
        return None

    if _QUESTION_LEAD_RE.match(text):
        return None

    structured = _parse_slot(text)
    if structured:
        return structured

    avoid = _AVOID_RE.search(text)
    if avoid:
        what = _clean(avoid.group("what")).rstrip(" .?!")
        if what:
            return f"User avoids {what}.", None, 0.8

    return None


def _parse_slot(text: str) -> tuple[str, str, float] | None:
    """Parse "my <attr> is <value>" / "use <value> as my <attr>" shapes."""
    use_as = _USE_AS_RE.search(text)
    if use_as:
        attr = _normalize_attr(use_as.group("attr"))
        value = _clean(use_as.group("value")).rstrip(" .?!")
        if attr and value:
            return f"User's {attr} is {value}.", attr, 0.9

    for line in text.splitlines():
        copular = _COPULAR_RE.search(line)
        if copular:
            attr = _normalize_attr(copular.group("attr"))
            value = _clean(copular.group("value")).rstrip(" .?!")
            if attr and value:
                return f"User's {attr} is {value}.", attr, 0.9
    return None


def _embedded_body(message: str) -> str:
    bodies = [match.group("body") for match in _EMBEDDED_BLOCK_RE.finditer(message)]
    return "\n".join(body.strip() for body in bodies if body.strip())


def _normalize_attr(attr: str) -> str:
    return " ".join(attr.lower().split())


def _third_person(payload: str) -> str:
    rewritten = re.sub(r"^my\s+", "User's ", payload, flags=re.I)
    if rewritten and rewritten[0].islower():
        rewritten = rewritten[0].upper() + rewritten[1:]
    if rewritten and rewritten[-1] not in ".?!":
        rewritten += "."
    return rewritten


def _clean(value: str) -> str:
    return " ".join(value.strip().split())
