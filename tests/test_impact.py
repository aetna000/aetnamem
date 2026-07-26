from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetnamem.decisions.signing import Ed25519Signer
from aetnamem.impact.allocation import (
    ARMS,
    BalancedFactorialAllocator,
)
from aetnamem.impact.attestation import (
    issue_outcome_attestation,
    verify_outcome_attestation,
)
from aetnamem.impact.controller import ImpactController, run_paid_smoke_check
from aetnamem.impact.lab import init_lab
from aetnamem.impact.policy import freeze_policy
from aetnamem.impact.protocol import load_protocol
from aetnamem.impact.synthetic import PLANTED, generate_randomized
from aetnamem.impact.estimate import estimate_primitive_effects
from aetnamem.impact.tasks import load_task
from aetnamem.impact.verify import _tree_sha256, verify_experiment
from aetnamem.core.canonical import sha256_hex
from aetnamem.runtime import MemoryRuntime, RuntimeScope, preset_config


def test_balanced_allocator_precommits_every_arm_once_per_block() -> None:
    allocator = BalancedFactorialAllocator(
        experiment_id="impact-test", seed="secret-seed"
    )
    first = allocator.schedule(["task-a", "task-b"], repetitions=2)
    second = allocator.schedule(["task-a", "task-b"], repetitions=2)
    assert first == second
    assert len(first) == 64
    for block in {item.block_id for item in first}:
        assert sorted(item.arm_id for item in first if item.block_id == block) == list(
            ARMS
        )
    assert len({item.run_id for item in first}) == 64
    assert all(item.assignment_probability == 1 / 16 for item in first)
    assert "secret-seed" not in json.dumps([item.to_dict() for item in first])
    assert allocator.verify(first)


def test_registered_effect_estimator_recovers_planted_directions() -> None:
    estimates = estimate_primitive_effects(
        generate_randomized(blocks=300, seed=77)
    )
    for name, planted in PLANTED.items():
        if planted:
            assert estimates[name].estimate > 0
            assert abs(estimates[name].estimate - planted) < 0.07
    assert abs(estimates["episodic"].estimate) < 0.06


def test_host_attestation_is_tamper_evident() -> None:
    signer = Ed25519Signer.generate(key_id="impact-host")
    payload = {
        "experiment_id": "experiment",
        "block_id": "task:r1",
        "task_id": "task",
        "run_id": "run",
        "arm_id": "0101",
        "schedule_sha256": "a" * 64,
        "protocol_sha256": "b" * 64,
        "memory_snapshot_sha256": "0" * 64,
        "metrology_sha256": "9" * 64,
        "manifest_sha256": "c" * 64,
        "stable_sha256": "d" * 64,
        "dynamic_sha256": "e" * 64,
        "output_sha256": "f" * 64,
        "workspace_sha256": "1" * 64,
        "verifier_sha256": "2" * 64,
        "success": True,
        "metrics": {"tokens": 100},
    }
    receipt = issue_outcome_attestation(signer, payload).to_dict()
    assert verify_outcome_attestation(receipt, signer.verifier())
    receipt["success"] = False
    assert not verify_outcome_attestation(receipt, signer.verifier())


def test_balanced_runtime_rejects_schedule_tampering_and_truncation(
    tmp_path: Path,
) -> None:
    allocator = BalancedFactorialAllocator(
        experiment_id="impact-test", seed="secret"
    )
    assignment = next(
        item for item in allocator.schedule(["task-a"]) if item.arm_id == "1111"
    )
    config = preset_config(
        "benchmark",
        db_path=str(tmp_path / "memory.db"),
        subject_id="alice",
        agent_id="grok",
    )
    config["budgets"]["total_chars"] = 20
    config["cml"] = {
        "mode": "experiment",
        "experiment_id": assignment.experiment_id,
        "design": "balanced-factorial",
        "policy_version": "impact-v1",
        "eligible_planes": ["working", "semantic", "episodic", "procedural"],
        "pinned_planes": [],
        "seed": "secret",
        "assigned_arm": assignment.arm_id,
        "block_id": assignment.block_id,
        "task_id": assignment.task_id,
        "repetition": assignment.repetition,
        "assignment_index": assignment.assignment_index,
        "assignment_token": assignment.assignment_token,
        "schedule_sha256": assignment.schedule_sha256,
        "assignment_probability": 1 / 16,
        "require_full_exposure": True,
    }
    runtime = MemoryRuntime(config)
    try:
        with pytest.raises(ValueError, match="truncated assigned planes"):
            runtime.prepare_turn(
                "test",
                task_state={"large": "x" * 100},
                scope=RuntimeScope(
                    subject_id="alice",
                    agent_id="grok",
                    task_id="task-a",
                    run_id=assignment.run_id,
                ),
            )
        assert runtime.store.run(assignment.run_id)["status"] == "invalid"
    finally:
        runtime.close()

    tampered = dict(config)
    tampered["db_path"] = str(tmp_path / "tampered.db")
    tampered["cml"] = {**config["cml"], "assigned_arm": "0000"}
    runtime = MemoryRuntime(tampered)
    try:
        with pytest.raises(ValueError, match="assignment token is invalid"):
            runtime.prepare_turn(
                "test",
                task_state={"value": "x"},
                scope=RuntimeScope(
                    subject_id="alice",
                    agent_id="grok",
                    task_id="task-a",
                    run_id=assignment.run_id,
                ),
            )
    finally:
        runtime.close()


def test_impact_lab_controller_keeps_verifier_outside_workspace(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lab"
    init_lab(root)
    fake = tmp_path / "fake-grok"
    fake.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys
if "--version" in sys.argv:
    print("fake-grok 1.0")
elif "--help" in sys.argv:
    print("--no-memory --disable-web-search --no-subagents --sandbox --tools "
          "--permission-mode --output-format --verbatim --no-plan --model "
          "--max-turns --session-id --single")
elif "inspect" in sys.argv:
    print("{}")
elif "models" in sys.argv:
    print("grok-4.5")
else:
    sys.stdin.read()
    pathlib.Path("answer.txt").write_text("W-731\\n")
    print('{"tokens": 10}')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    protocol_value = json.loads((root / "protocol.yaml").read_text())
    protocol_value["model"]["command"] = str(fake)
    (root / "protocol.yaml").write_text(json.dumps(protocol_value))
    protocol = load_protocol(root / "protocol.yaml")
    task = load_task(root / protocol.task_files[0])
    allocator = BalancedFactorialAllocator(
        experiment_id=protocol.experiment_id,
        seed=str(protocol.raw["randomization"]["seed"]),
    )
    assignment = next(
        item
        for item in allocator.schedule([task.task_id])
        if item.arm_id == "1111"
    )
    signer = Ed25519Signer.generate(key_id="memory-impact-host")
    controller = ImpactController(
        protocol,
        output_root=root / "one-run",
        signer=signer,
        signature_verifier=signer.verifier(),
    )
    receipt = controller.run_assignment(task, assignment).to_dict()
    assert receipt["success"] is True
    assert receipt["arm_id"] == "1111"
    workspace = root / "one-run" / assignment.run_id / "workspace"
    assert not (workspace / "verify_outcome.py").exists()
    assert verify_outcome_attestation(receipt, signer.verifier())

    runtime = MemoryRuntime(
        {
            **preset_config(
                "benchmark",
                db_path=str(root / "one-run" / assignment.run_id / "memory.db"),
                subject_id="impact-subject",
                agent_id="grok-impact",
            ),
            "learning_enabled": False,
        }
    )
    try:
        stored = runtime.store.outcome_for_run(assignment.run_id)
        assert stored["outcome_trust"] == "host_attested"
        assert runtime.status()["counts"]["lesson_proposals"] == 1
    finally:
        runtime.close()


def test_paid_smoke_proves_the_registered_cli_can_edit_workspace(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lab"
    init_lab(root)
    fake = tmp_path / "fake-grok"
    fake.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import re
import sys
prompt = sys.argv[sys.argv.index("--single") + 1]
nonce = re.search(r"AETNAMEM-SMOKE-[0-9a-f]+", prompt).group(0)
pathlib.Path("answer.txt").write_text(nonce + "\\n")
print(json.dumps({
    "usage": {"total_tokens": 12},
    "total_cost_usd": 0.001
}))
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    value = json.loads((root / "protocol.yaml").read_text())
    value["model"]["command"] = str(fake)
    (root / "protocol.yaml").write_text(json.dumps(value), encoding="utf-8")
    protocol = load_protocol(root / "protocol.yaml")

    result = run_paid_smoke_check(
        protocol, output_path=root / "results" / "paid-smoke.json"
    )

    assert result["passed"] is True
    assert result["telemetry"]["cost_trust"] == "provider_reported"
    assert (root / "results" / "paid-smoke.stdout.txt").is_file()
    assert (root / "results" / "paid-smoke.stderr.txt").is_file()
    assert not (root / "results" / ".paid-smoke-workspace").exists()


def test_policy_uses_host_context_budget_not_provider_total_tokens() -> None:
    rows = []
    for arm in ARMS:
        for block in range(2):
            rows.append(
                {
                    "task_split": "train",
                    "arm_id": arm,
                    "success": arm == "0100",
                    "tokens": 100_000,
                    "token_trust": "provider_reported",
                    "context_chars": 500 if arm == "0100" else 100,
                    "context_trust": "host_verified",
                }
            )

    policy = freeze_policy(rows, max_mean_context_chars=1_000)

    assert policy["selected_arm"] == "0100"
    assert policy["training_evidence"]["mean_tokens"] == 100_000
    assert policy["training_evidence"]["mean_context_chars"] == 500


def test_default_lab_allows_only_registered_workspace_edit_tools(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lab"
    init_lab(root)
    protocol = json.loads((root / "protocol.yaml").read_text())
    arguments = protocol["model"]["arguments"]
    mode = arguments[arguments.index("--permission-mode") + 1]
    assert mode == "bypassPermissions"
    tools = arguments[arguments.index("--tools") + 1].split(",")
    assert tools == ["read_file", "grep", "list_dir", "search_replace"]
    sandbox = arguments[arguments.index("--sandbox") + 1]
    assert sandbox == "strict"


def test_independent_verifier_checks_complete_schedule_seed_and_artifacts(
    tmp_path: Path,
) -> None:
    seed = "revealed-after-close"
    allocator = BalancedFactorialAllocator(
        experiment_id="verify-study", seed=seed
    )
    assignments = allocator.schedule(["task-a"])
    results = tmp_path / "results"
    results.mkdir()
    (results / "assignments.json").write_text(
        json.dumps([item.to_dict() for item in assignments]),
        encoding="utf-8",
    )
    signer = Ed25519Signer.generate(key_id="memory-impact-host")
    public_key = tmp_path / "host-public.pem"
    public_key.write_bytes(signer.public_key_pem())
    registration = {
        "experiment_id": "verify-study",
        "randomization": {
            "seed_commitment": allocator.seed_commitment,
            "reveal": "after-close",
        },
        "protocol_sha256": "a" * 64,
        "schedule_sha256": assignments[0].schedule_sha256,
        "signing_key_id": signer.key_id,
    }
    (results / "registration.json").write_text(
        json.dumps(registration), encoding="utf-8"
    )
    for assignment in assignments:
        run_root = results / assignment.run_id
        workspace = run_root / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "answer.txt").write_text("ok", encoding="utf-8")
        (run_root / "stdout.txt").write_text("ok", encoding="utf-8")
        verifier = run_root / "host-verifier.py"
        verifier.write_text("# verifier\n", encoding="utf-8")
        pack = {
            "manifest_sha256": "b" * 64,
            "stable_sha256": "c" * 64,
            "dynamic_sha256": "d" * 64,
        }
        (run_root / "runtime-pack.json").write_text(
            json.dumps(pack), encoding="utf-8"
        )
        receipt = issue_outcome_attestation(
            signer,
            {
                "experiment_id": assignment.experiment_id,
                "block_id": assignment.block_id,
                "task_id": assignment.task_id,
                "run_id": assignment.run_id,
                "arm_id": assignment.arm_id,
                "schedule_sha256": assignment.schedule_sha256,
                "protocol_sha256": "a" * 64,
                "memory_snapshot_sha256": "e" * 64,
                "metrology_sha256": "f" * 64,
                **pack,
                "output_sha256": sha256_hex("ok"),
                "workspace_sha256": _tree_sha256(workspace),
                "verifier_sha256": sha256_hex("# verifier\n"),
                "success": True,
                "metrics": {},
            },
        )
        (run_root / "outcome-receipt.json").write_text(
            json.dumps(receipt.to_dict()), encoding="utf-8"
        )
    result = verify_experiment(
        results, public_key_path=public_key, revealed_seed=seed
    )
    assert result["valid"] is True
    assert result["schedule_integrity"] is True
    assert result["revealed_seed_valid"] is True
    assert result["verified_receipts"] == 16

    first = results / assignments[0].run_id / "stdout.txt"
    first.write_text("tampered", encoding="utf-8")
    assert (
        verify_experiment(
            results, public_key_path=public_key, revealed_seed=seed
        )["valid"]
        is False
    )
