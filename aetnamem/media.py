"""Validated text observations derived from host-controlled media artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from aetnamem.core.canonical import canonical_json, sha256_hex


MEDIA_MODALITIES = frozenset({"image", "audio", "video", "document"})
# "verified_by_aetnamem" may only ever be set by a code path that hashed the
# media bytes itself. No such path exists yet, so no caller — including
# internal ones using forced_assurance — can produce the label today.
RESERVED_DIGEST_ASSURANCE_LEVELS = frozenset({"verified_by_aetnamem"})
ATTAINABLE_DIGEST_ASSURANCE_LEVELS = frozenset(
    {"host_asserted", "caller_asserted"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_KEYS = frozenset(
    {"page", "timestamp_start", "timestamp_end", "region"}
)
_EXTRACTOR_KEYS = frozenset(
    {"provider", "model", "version", "model_digest"}
)


@dataclass(frozen=True)
class MediaObservationEnvelope:
    text: str
    modality: str
    media_sha256: str
    host_reference: str
    segment: dict[str, Any]
    extractor: dict[str, str | None]
    confidence: float | None
    digest_assurance: str
    observed_at: str | None
    artifact_id: str | None

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, forced_assurance: str | None = None
    ) -> "MediaObservationEnvelope":
        allowed = {
            "text",
            "modality",
            "media_sha256",
            "host_reference",
            "segment",
            "extractor",
            "confidence",
            "digest_assurance",
            "observed_at",
            "artifact_id",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown media observation fields: {unknown}")
        text_value = value.get("text")
        if not isinstance(text_value, str):
            raise ValueError("media observation text must be a string")
        text = text_value.strip()
        if not text:
            raise ValueError("media observation text is required")
        if len(text) > 100_000:
            raise ValueError("media observation text exceeds 100000 characters")
        modality_value = value.get("modality")
        if not isinstance(modality_value, str):
            raise ValueError("modality must be a string")
        modality = modality_value.strip().lower()
        if modality not in MEDIA_MODALITIES:
            raise ValueError(
                f"modality must be one of {sorted(MEDIA_MODALITIES)}"
            )
        media_sha256 = _sha256(value.get("media_sha256"), "media_sha256")
        host_reference = _host_reference(value.get("host_reference"))
        segment = _segment(value.get("segment"))
        extractor = _extractor(value.get("extractor"))
        confidence = _confidence(value.get("confidence"))
        assurance = forced_assurance or str(
            value.get("digest_assurance") or "caller_asserted"
        )
        if assurance in RESERVED_DIGEST_ASSURANCE_LEVELS:
            raise ValueError(
                "digest_assurance 'verified_by_aetnamem' is reserved until "
                "AetnaMem hashes the media bytes itself; callers cannot "
                "self-certify it"
            )
        if assurance not in ATTAINABLE_DIGEST_ASSURANCE_LEVELS:
            raise ValueError(
                "digest_assurance must be one of "
                f"{sorted(ATTAINABLE_DIGEST_ASSURANCE_LEVELS)}"
            )
        observed_at = _timestamp(value.get("observed_at"))
        artifact_value = value.get("artifact_id")
        if artifact_value is not None and not isinstance(artifact_value, str):
            raise ValueError("artifact_id must be a string")
        artifact_id = (artifact_value or "").strip() or None
        return cls(
            text=text,
            modality=modality,
            media_sha256=media_sha256,
            host_reference=host_reference,
            segment=segment,
            extractor=extractor,
            confidence=confidence,
            digest_assurance=assurance,
            observed_at=observed_at,
            artifact_id=artifact_id,
        )

    @property
    def segment_sha256(self) -> str:
        return sha256_hex(canonical_json(self.segment))

    @property
    def extractor_sha256(self) -> str:
        return sha256_hex(canonical_json(self.extractor))

    @property
    def host_reference_sha256(self) -> str:
        return sha256_hex(self.host_reference)

    @property
    def text_sha256(self) -> str:
        return sha256_hex(self.text)

    @property
    def lineage_sha256(self) -> str:
        return sha256_hex(
            canonical_json(
                {
                    "media_sha256": self.media_sha256,
                    "segment_sha256": self.segment_sha256,
                    "extractor_sha256": self.extractor_sha256,
                }
            )
        )

    @property
    def canonical_body(self) -> dict[str, Any]:
        return {
            "format": "aetnamem-media-observation-v1",
            "text_sha256": self.text_sha256,
            "modality": self.modality,
            "media_sha256": self.media_sha256,
            "host_reference_sha256": self.host_reference_sha256,
            "segment": self.segment,
            "extractor": self.extractor,
            "confidence": self.confidence,
            "digest_assurance": self.digest_assurance,
            "observed_at": self.observed_at,
        }

    @property
    def envelope_sha256(self) -> str:
        return sha256_hex(canonical_json(self.canonical_body))


def normalize_media_sha256(value: Any) -> str:
    return _sha256(value, "media_sha256")


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    digest = value.strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return digest


def _host_reference(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("host_reference must be a string")
    reference = value.strip()
    if not reference:
        raise ValueError("host_reference is required")
    if len(reference) > 2048 or any(ord(char) < 32 for char in reference):
        raise ValueError("host_reference is invalid")
    parsed = urlsplit(reference)
    if parsed.scheme and (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "host_reference must be secretless and contain no credentials, "
            "query parameters, or fragments"
        )
    return reference


def _segment(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("segment must be an object")
    unknown = sorted(set(value) - _SEGMENT_KEYS)
    if unknown:
        raise ValueError(f"unknown segment fields: {unknown}")
    result: dict[str, Any] = {}
    if value.get("page") is not None:
        if isinstance(value["page"], bool):
            raise ValueError("segment.page must be an integer")
        page = int(value["page"])
        if float(value["page"]) != page:
            raise ValueError("segment.page must be an integer")
        if page < 1:
            raise ValueError("segment.page must be at least 1")
        result["page"] = page
    for key in ("timestamp_start", "timestamp_end"):
        if value.get(key) is not None:
            if isinstance(value[key], bool):
                raise ValueError(f"segment.{key} must be a number")
            timestamp = float(value[key])
            if not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError(f"segment.{key} must be a non-negative number")
            result[key] = timestamp
    if (
        "timestamp_start" in result
        and "timestamp_end" in result
        and result["timestamp_end"] < result["timestamp_start"]
    ):
        raise ValueError("segment.timestamp_end must not precede timestamp_start")
    if value.get("region") is not None:
        if not isinstance(value["region"], str):
            raise ValueError("segment.region must be a string")
        region = value["region"].strip()
        if not region or len(region) > 500:
            raise ValueError("segment.region must be 1 to 500 characters")
        result["region"] = region
    return result


def _extractor(value: Any) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise ValueError("extractor must be an object")
    unknown = sorted(set(value) - _EXTRACTOR_KEYS)
    if unknown:
        raise ValueError(f"unknown extractor fields: {unknown}")
    result: dict[str, str | None] = {}
    for key in ("provider", "model", "version"):
        raw = value.get(key)
        if not isinstance(raw, str):
            raise ValueError(f"extractor.{key} must be a string")
        item = raw.strip()
        if not item or len(item) > 300:
            raise ValueError(f"extractor.{key} is required")
        result[key] = item
    digest_value = value.get("model_digest")
    result["model_digest"] = (
        _sha256(digest_value, "extractor.model_digest")
        if digest_value
        else None
    )
    return result


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("confidence must be a number")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("observed_at must be a string")
    timestamp = value.strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return timestamp
