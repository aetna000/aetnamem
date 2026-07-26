from __future__ import annotations

from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.runtime.models import PLANE_NAMES, PlaneContribution, RuntimeScope


def compile_context(
    *,
    run_id: str,
    scope: RuntimeScope,
    contributions: list[PlaneContribution],
    degraded_planes: list[str],
    budgets: dict[str, Any],
    cml_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_plane = {item.plane: item for item in contributions}
    semantic = by_plane.get("semantic")
    legacy = (
        semantic.metadata.get("legacy_context_pack")
        if semantic is not None
        else None
    )
    has_legacy_semantic_pack = isinstance(legacy, dict)
    if not has_legacy_semantic_pack:
        legacy = {
            "format": "aetnamem-context-pack-v1",
            "stable_context": "",
            "dynamic_context": "",
            "stable_record_ids": [],
            "dynamic_record_ids": [],
            "stable_sha256": sha256_hex(""),
            "dynamic_sha256": sha256_hex(""),
            "placement": {
                "stable_context": "stable_system_prefix",
                "dynamic_context": "current_turn_tail",
            },
            "budgets": {},
            "reference_mode": "compact",
        }

    stable_parts: list[tuple[str, str]] = [
        ("semantic", str(legacy.get("stable_context") or ""))
    ]
    dynamic_parts: list[tuple[str, str]] = [
        ("semantic", str(legacy.get("dynamic_context") or ""))
    ]
    if (
        semantic is not None
        and semantic.content
        and not has_legacy_semantic_pack
    ):
        target = (
            stable_parts
            if semantic.placement == "stable_system_prefix"
            else dynamic_parts
        )
        target.append(("semantic", semantic.content))
    for plane in PLANE_NAMES:
        if plane == "semantic":
            continue
        contribution = by_plane.get(plane)
        if contribution is None or not contribution.content:
            continue
        if contribution.placement == "stable_system_prefix":
            stable_parts.append((plane, contribution.content))
        else:
            dynamic_parts.append((plane, contribution.content))

    total_budget = max(0, int(budgets.get("total_chars", 5000)))
    stable, stable_exposure = _compile_segments(
        stable_parts, budget=total_budget, placement="stable_system_prefix"
    )
    dynamic_budget = max(0, total_budget - len(stable))
    dynamic, dynamic_exposure = _compile_segments(
        dynamic_parts, budget=dynamic_budget, placement="current_turn_tail"
    )
    exposure = stable_exposure + dynamic_exposure
    if cml_manifest is not None and cml_manifest.get("require_full_exposure"):
        expected = {
            item.plane for item in contributions if item.content.strip()
        }
        observed = {item["plane"] for item in exposure}
        missing = sorted(expected - observed)
        if missing:
            raise ValueError(
                "benchmark compiler did not expose assigned planes: "
                + ", ".join(missing)
            )
        truncated = sorted(
            {item["plane"] for item in exposure if not item["fully_exposed"]}
        )
        if truncated:
            raise ValueError(
                "benchmark context budget truncated assigned planes: "
                + ", ".join(truncated)
            )

    manifest = {
        "run_id": run_id,
        "planes": [
            {
                "plane": item.plane,
                "item_ids": item.item_ids,
                "content_sha256": sha256_hex(item.content),
                "chars": len(item.content),
                "placement": item.placement,
                "trust": item.trust,
            }
            for item in contributions
        ],
        "degraded_planes": sorted(degraded_planes),
        "budgets": budgets,
        "exposure": exposure,
    }
    if cml_manifest is not None:
        manifest["cml"] = cml_manifest
    result = {
        "format": (
            "aetnamem-runtime-pack-v2"
            if cml_manifest is not None
            else "aetnamem-runtime-pack-v1"
        ),
        "run_id": run_id,
        "scope": scope.to_dict(),
        "stable_context": stable,
        "dynamic_context": dynamic,
        "legacy_context_pack": legacy,
        "contributions": [item.to_dict() for item in contributions],
        "degraded_planes": sorted(degraded_planes),
        "placement": {
            "stable_context": "stable_system_prefix",
            "dynamic_context": "current_turn_tail",
        },
        "budgets": budgets,
        "stable_sha256": sha256_hex(stable),
        "dynamic_sha256": sha256_hex(dynamic),
        "manifest": manifest,
    }
    if cml_manifest is not None:
        result["cml"] = cml_manifest
    result["manifest_sha256"] = sha256_hex(canonical_json(manifest))
    return result


def _compile_segments(
    segments: list[tuple[str, str]], *, budget: int, placement: str
) -> tuple[str, list[dict[str, Any]]]:
    output = ""
    evidence: list[dict[str, Any]] = []
    for plane, content in segments:
        if not content:
            continue
        separator = "\n\n" if output else ""
        remaining = max(0, budget - len(output))
        separator_part = separator[:remaining]
        content_remaining = max(0, remaining - len(separator_part))
        exposed = content[:content_remaining]
        start = len(output) + len(separator_part)
        output += separator_part + exposed
        evidence.append(
            {
                "plane": plane,
                "placement": placement,
                "source_sha256": sha256_hex(content),
                "source_chars": len(content),
                "exposed_sha256": sha256_hex(exposed),
                "exposed_chars": len(exposed),
                "start": start,
                "end": start + len(exposed),
                "fully_exposed": len(exposed) == len(content),
            }
        )
    return output, evidence
