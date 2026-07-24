#!/usr/bin/env python3
"""Deterministic four-plane coverage and ablation benchmark.

This measures memory preparation, not model intelligence. It verifies that the
same task receives the expected evidence from each enabled plane, and reports
latency/context size so model-level trials can be layered on top.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time

from aetnamem.runtime import MemoryRuntime, preset_config


VARIANTS = {
    "all_four": set(),
    "without_working": {"working"},
    "without_semantic": {"semantic"},
    "without_episodic": {"episodic"},
    "without_procedural": {"procedural"},
    "semantic_only": {"working", "episodic", "procedural"},
}


def run() -> dict:
    rows = []
    with tempfile.TemporaryDirectory(prefix="aetnamem-four-memory-") as directory:
        root = Path(directory)
        skill = root / "skills" / "report-uploader" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: report-uploader\n"
            "description: Upload and verify customer reports\n---\n"
            "# Report uploader\nUpload once and verify the receipt.\n",
            encoding="utf-8",
        )
        base = preset_config(
            "benchmark",
            db_path=str(root / "memory.db"),
            subject_id="benchmark-user",
            agent_id="benchmark-agent",
            skill_paths=[str(skill)],
        )
        seed = MemoryRuntime(base)
        seed.memory.remember(
            "benchmark-user", "My preferred report format is PDF."
        )
        failed = seed.prepare_turn(
            "Upload customer report",
            task_state={"goal": "upload report"},
        )
        outcome = seed.record_outcome(
            failed["run_id"],
            success=False,
            summary="Customer report upload timed out at the old endpoint",
        )
        seed.promote_lesson(outcome["lesson_proposals"][0]["id"])
        seed.close()

        for name, disabled in VARIANTS.items():
            config = deepcopy(base)
            for plane in disabled:
                config["planes"][plane]["enabled"] = False
            runtime = MemoryRuntime(config)
            started = time.perf_counter()
            pack = runtime.prepare_turn(
                "Retry the customer report upload",
                task_state={
                    "goal": "upload report",
                    "progress": "PDF generated",
                },
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            content = f"{pack['stable_context']}\n{pack['dynamic_context']}"
            expected = {
                "working": "PDF generated",
                "semantic": "report format is PDF",
                "episodic": "timed out",
                "procedural": "report-uploader",
            }
            hits = {
                plane: marker.lower() in content.lower()
                for plane, marker in expected.items()
            }
            rows.append(
                {
                    "variant": name,
                    "disabled_planes": sorted(disabled),
                    "expected_plane_hits": hits,
                    "hit_count": sum(hits.values()),
                    "context_chars": len(pack["stable_context"])
                    + len(pack["dynamic_context"]),
                    "prepare_ms": round(elapsed_ms, 3),
                    "degraded_planes": pack["degraded_planes"],
                }
            )
            runtime.close()
    return {
        "format": "aetnamem-four-memory-ablation-v1",
        "scope": "deterministic memory coverage; no model call",
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
