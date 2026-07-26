from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.decisions.signing import Ed25519Verifier
from aetnamem.impact.allocation import verify_assignment_token
from aetnamem.impact.attestation import verify_outcome_attestation


def load_result_rows(results_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(results_dir)
    rows = []
    for path in sorted(root.glob("impact_*/outcome-receipt.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        metrics = dict(receipt.get("metrics") or {})
        rows.append(
            {
                "run_id": receipt["run_id"],
                "block_id": receipt["block_id"],
                "task_id": receipt["task_id"],
                "task_family": receipt.get("task_family"),
                "task_split": receipt.get("task_split"),
                "relevance_arm": receipt.get("relevance_arm", "0100"),
                "arm_id": receipt["arm_id"],
                "success": bool(receipt["success"]),
                "cost_usd": metrics.get("cost_usd", 0.0),
                "cost_trust": metrics.get("cost_trust", "unavailable"),
                "cost_budget_compliant": metrics.get(
                    "cost_budget_compliant"
                ),
                "tokens": metrics.get("tokens", 0),
                "token_trust": metrics.get("token_trust", "unavailable"),
                "context_chars": metrics.get("context_chars", 0),
                "context_trust": metrics.get("context_trust", "unavailable"),
                "latency_ms": metrics.get("latency_ms", 0),
                "unsafe_actions": metrics.get("unsafe_actions", 0),
                "false_warnings": metrics.get("false_warnings", 0),
            }
        )
    return rows


def verify_experiment(
    results_dir: str | Path,
    *,
    public_key_path: str | Path,
    revealed_seed: str | None = None,
) -> dict[str, Any]:
    root = Path(results_dir)
    assignments_path = root / "assignments.json"
    registration_path = root / "registration.json"
    if not assignments_path.is_file() or not registration_path.is_file():
        raise ValueError("results require registration.json and assignments.json")
    assignments = json.loads(assignments_path.read_text(encoding="utf-8"))
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    public_pem = Path(public_key_path).read_bytes()
    key_id = str(registration["signing_key_id"])
    verifier = Ed25519Verifier.from_public_pems({key_id: public_pem})
    expected = {str(item["run_id"]): item for item in assignments}
    schedule_payload = {
        "format": "aetnamem-balanced-factorial-schedule-v1",
        "experiment_id": registration["experiment_id"],
        "seed_commitment": registration["randomization"]["seed_commitment"],
        "assignments": [
            {
                key: value
                for key, value in item.items()
                if key not in {"schedule_sha256", "assignment_token"}
            }
            for item in assignments
        ],
    }
    recomputed_schedule = sha256_hex(canonical_json(schedule_payload))
    schedule_integrity = (
        recomputed_schedule == registration.get("schedule_sha256")
        and all(
            item.get("schedule_sha256") == recomputed_schedule
            for item in assignments
        )
    )
    seed_valid: bool | None = None
    if revealed_seed is not None:
        seed_valid = sha256_hex(revealed_seed) == registration["randomization"].get(
            "seed_commitment"
        ) and all(
            verify_assignment_token(
                seed=revealed_seed,
                experiment_id=str(item["experiment_id"]),
                task_id=str(item["task_id"]),
                block_id=str(item["block_id"]),
                repetition=int(item["repetition"]),
                assignment_index=int(item["assignment_index"]),
                run_id=str(item["run_id"]),
                arm_id=str(item["arm_id"]),
                assignment_probability=float(item["assignment_probability"]),
                seed_commitment=str(item["seed_commitment"]),
                schedule_sha256=str(item["schedule_sha256"]),
                assignment_token=str(item["assignment_token"]),
            )
            for item in assignments
        )
    receipts = {}
    failures = []
    for path in sorted(root.glob("impact_*/outcome-receipt.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        run_id = str(value.get("run_id"))
        receipts[run_id] = value
        if not verify_outcome_attestation(value, verifier):
            failures.append({"run_id": run_id, "reason": "invalid signature or digest"})
            continue
        assignment = expected.get(run_id)
        if assignment is None:
            failures.append({"run_id": run_id, "reason": "unregistered run"})
            continue
        for field in ("arm_id", "block_id", "schedule_sha256"):
            if value.get(field) != assignment.get(field):
                failures.append(
                    {"run_id": run_id, "reason": f"{field} does not match schedule"}
                )
        run_root = path.parent
        stdout = run_root / "stdout.txt"
        pack_path = run_root / "runtime-pack.json"
        if not stdout.is_file() or sha256_hex(
            stdout.read_text(encoding="utf-8")
        ) != value.get("output_sha256"):
            failures.append({"run_id": run_id, "reason": "output digest mismatch"})
        if not pack_path.is_file():
            failures.append({"run_id": run_id, "reason": "runtime pack missing"})
        else:
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            for field in ("manifest_sha256", "stable_sha256", "dynamic_sha256"):
                if pack.get(field) != value.get(field):
                    failures.append(
                        {"run_id": run_id, "reason": f"{field} binding mismatch"}
                    )
        verifier_artifact = run_root / "host-verifier.py"
        if not verifier_artifact.is_file() or _file_sha256(
            verifier_artifact
        ) != value.get("verifier_sha256"):
            failures.append(
                {"run_id": run_id, "reason": "verifier artifact digest mismatch"}
            )
        workspace = run_root / "workspace"
        if not workspace.is_dir() or _tree_sha256(workspace) != value.get(
            "workspace_sha256"
        ):
            failures.append(
                {"run_id": run_id, "reason": "workspace digest mismatch"}
            )
    missing = sorted(set(expected) - set(receipts))
    extra = sorted(set(receipts) - set(expected))
    aborted = sorted(
        str(json.loads(path.read_text(encoding="utf-8")).get("run_id"))
        for path in root.glob("impact_*/aborted.json")
    )
    blocks: dict[str, list[str]] = {}
    for item in assignments:
        blocks.setdefault(str(item["block_id"]), []).append(str(item["arm_id"]))
    unbalanced = {
        block: arms
        for block, arms in blocks.items()
        if sorted(arms) != [f"{value:04b}" for value in range(16)]
    }
    valid = (
        schedule_integrity
        and seed_valid is not False
        and not failures
        and not missing
        and not extra
        and not unbalanced
    )
    return {
        "format": "aetnamem-memory-impact-verification-v1",
        "valid": valid,
        "registered_runs": len(expected),
        "verified_receipts": len(receipts) - len(
            {item["run_id"] for item in failures}
        ),
        "missing_runs": missing,
        "aborted_runs": aborted,
        "extra_runs": extra,
        "unbalanced_blocks": unbalanced,
        "failures": failures,
        "protocol_sha256": registration.get("protocol_sha256"),
        "schedule_sha256": registration.get("schedule_sha256"),
        "schedule_integrity": schedule_integrity,
        "revealed_seed_valid": seed_valid,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(path: Path) -> str:
    entries = []
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        entries.append(
            {"path": item.relative_to(path).as_posix(), "sha256": _file_sha256(item)}
        )
    return sha256_hex(canonical_json(entries))
