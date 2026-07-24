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
    if not isinstance(legacy, dict):
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

    stable_parts = [str(legacy.get("stable_context") or "")]
    dynamic_parts = [str(legacy.get("dynamic_context") or "")]
    for plane in PLANE_NAMES:
        if plane == "semantic":
            continue
        contribution = by_plane.get(plane)
        if contribution is None or not contribution.content:
            continue
        if contribution.placement == "stable_system_prefix":
            stable_parts.append(contribution.content)
        else:
            dynamic_parts.append(contribution.content)

    total_budget = max(0, int(budgets.get("total_chars", 5000)))
    stable = "\n\n".join(part for part in stable_parts if part)
    stable = stable[:total_budget]
    dynamic_budget = max(0, total_budget - len(stable))
    dynamic = "\n\n".join(part for part in dynamic_parts if part)[:dynamic_budget]

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
