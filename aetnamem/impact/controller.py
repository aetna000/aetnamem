from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from typing import Any
import uuid

from aetnamem.core.canonical import canonical_json, sha256_hex
from aetnamem.decisions.signing import DecisionSignatureVerifier, DecisionSigner
from aetnamem.impact.allocation import ScheduledAssignment, arm_planes
from aetnamem.impact.attestation import (
    OutcomeAttestation,
    issue_outcome_attestation,
    write_attestation,
)
from aetnamem.impact.protocol import ImpactProtocol
from aetnamem.impact.tasks import ImpactTask
from aetnamem.impact.metrology import inspect_cli
from aetnamem.runtime import MemoryRuntime, RuntimeScope, preset_config


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    latency_ms: int
    timed_out: bool


class ImpactController:
    """Host-side controller. Its verifier and signing key never enter the agent workspace."""

    def __init__(
        self,
        protocol: ImpactProtocol,
        *,
        output_root: str | Path,
        signer: DecisionSigner,
        signature_verifier: DecisionSignatureVerifier,
        metrology: dict[str, Any] | None = None,
    ) -> None:
        self.protocol = protocol
        self.output_root = Path(output_root).resolve()
        self.signer = signer
        self.signature_verifier = signature_verifier
        self.metrology = metrology or inspect_cli(
            str(protocol.raw["model"]["command"]),
            model=str(protocol.raw["model"]["name"]),
            arguments=[
                *[str(value) for value in protocol.raw["model"]["arguments"]],
                "--max-turns",
            ],
        )

    def run_assignment(
        self,
        task: ImpactTask,
        assignment: ScheduledAssignment,
    ) -> OutcomeAttestation:
        run_root = self.output_root / assignment.run_id
        if run_root.exists():
            raise ValueError(f"run output already exists: {run_root}")
        run_root.mkdir(parents=True)
        workspace = run_root / "workspace"
        shutil.copytree(task.resolve(str(task.raw["workspace"])), workspace)
        database = run_root / "memory.db"
        snapshot = task.resolve(str(task.raw["snapshot"]))
        snapshot_sha256 = _file_sha256(snapshot)
        _clone_sqlite(snapshot, database)

        runtime_config = preset_config(
            "benchmark",
            db_path=str(database),
            subject_id=str(task.raw.get("subject_id", "impact-subject")),
            agent_id=str(task.raw.get("agent_id", "grok-impact")),
            skill_paths=[
                str(task.resolve(value))
                for value in task.raw.get("skill_paths", [])
            ],
        )
        runtime_config["budgets"]["total_chars"] = int(
            self.protocol.raw["budgets"]["max_context_chars"]
        )
        runtime_config["learning_enabled"] = False
        runtime_config["cml"] = {
            "mode": "experiment",
            "experiment_id": assignment.experiment_id,
            "design": "balanced-factorial",
            "policy_version": "memory-impact-v1",
            "eligible_planes": list(arm_planes(assignment.arm_id)),
            "pinned_planes": [],
            "seed": str(self.protocol.raw["randomization"]["seed"]),
            "assigned_arm": assignment.arm_id,
            "block_id": assignment.block_id,
            "task_id": assignment.task_id,
            "repetition": assignment.repetition,
            "assignment_index": assignment.assignment_index,
            "assignment_token": assignment.assignment_token,
            "schedule_sha256": assignment.schedule_sha256,
            "assignment_probability": assignment.assignment_probability,
            "require_full_exposure": True,
            "candidate_identity": "content-envelope-v1",
        }
        runtime_config["cml"]["require_nonempty_candidates"] = True
        runtime = MemoryRuntime(runtime_config)
        try:
            pack = runtime.prepare_turn(
                str(task.raw["query"]),
                task_state=dict(task.raw["task_state"]),
                scope=RuntimeScope(
                    subject_id=runtime.default_scope.subject_id,
                    agent_id=runtime.default_scope.agent_id,
                    task_id=task.task_id,
                    run_id=assignment.run_id,
                ),
            )
        finally:
            runtime.close()
        (run_root / "runtime-pack.json").write_text(
            json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        prompt = _agent_prompt(task, pack)
        prompt_path = run_root / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        process = self._run_model(prompt, workspace, assignment.run_id)
        (run_root / "stdout.txt").write_text(process.stdout, encoding="utf-8")
        (run_root / "stderr.txt").write_text(process.stderr, encoding="utf-8")
        try:
            verifier = self._run_verifier(task, workspace, run_root, process)
        except Exception as exc:
            runtime = MemoryRuntime(runtime_config)
            try:
                runtime.store.mark_run_aborted(assignment.run_id, str(exc))
            finally:
                runtime.close()
            aborted = {
                "format": "aetnamem-memory-impact-aborted-run-v1",
                "run_id": assignment.run_id,
                "arm_id": assignment.arm_id,
                "manifest_sha256": pack["manifest_sha256"],
                "reason": str(exc),
            }
            aborted["aborted_sha256"] = sha256_hex(canonical_json(aborted))
            (run_root / "aborted.json").write_text(
                json.dumps(aborted, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raise
        verifier_source = task.resolve(str(task.raw["verifier"]))
        shutil.copy2(verifier_source, run_root / "host-verifier.py")
        metrics = _extract_telemetry(process.stdout)
        metrics.update(
            {
                "context_chars": len(str(pack["stable_context"]))
                + len(str(pack["dynamic_context"])),
                "context_trust": "host_verified",
            }
        )
        for key, value in dict(verifier.get("metrics") or {}).items():
            if (
                key.endswith("_trust")
                and metrics.get(key) not in {None, "unavailable"}
                and value == "unavailable"
            ):
                continue
            metrics[key] = value
        metrics.update(
            {
                "latency_ms": process.latency_ms,
                "exit_code": process.exit_code,
                "timed_out": process.timed_out,
                "cost_trust": metrics.get("cost_trust", "unavailable"),
                "token_trust": metrics.get("token_trust", "unavailable"),
            }
        )
        verified_success = bool(verifier["success"])
        cost = metrics.get("cost_usd")
        cost_compliant = (
            None
            if cost is None
            else float(cost)
            <= float(self.protocol.raw["budgets"]["max_cost_usd"])
        )
        primary_success = (
            verified_success
            and not process.timed_out
            and cost_compliant is not False
        )
        metrics.update(
            {
                "verified_success": verified_success,
                "cost_budget_usd": float(
                    self.protocol.raw["budgets"]["max_cost_usd"]
                ),
                "cost_budget_compliant": cost_compliant,
                "primary_success": primary_success,
            }
        )
        receipt = issue_outcome_attestation(
            self.signer,
            {
                "experiment_id": assignment.experiment_id,
                "block_id": assignment.block_id,
                "task_id": task.task_id,
                "task_family": task.family,
                "task_split": task.split,
                "relevance_arm": str(
                    (task.raw.get("baseline_arms") or {}).get(
                        "relevance", "0100"
                    )
                ),
                "task_sha256": task.digest,
                "run_id": assignment.run_id,
                "arm_id": assignment.arm_id,
                "assignment_probability": assignment.assignment_probability,
                "assignment_token_sha256": sha256_hex(assignment.assignment_token),
                "schedule_sha256": assignment.schedule_sha256,
                "protocol_sha256": self.protocol.digest,
                "memory_snapshot_sha256": snapshot_sha256,
                "metrology_sha256": self.metrology.get("metrology_sha256"),
                "grok_executable_sha256": self.metrology.get(
                    "executable_sha256"
                ),
                "grok_version_output": self.metrology.get("version_output"),
                "grok_model": self.protocol.raw["model"]["name"],
                "manifest_sha256": pack["manifest_sha256"],
                "stable_sha256": pack["stable_sha256"],
                "dynamic_sha256": pack["dynamic_sha256"],
                "output_sha256": sha256_hex(process.stdout),
                "workspace_sha256": _tree_sha256(workspace),
                "verifier_sha256": _file_sha256(verifier_source),
                "success": primary_success,
                "metrics": metrics,
                "verifier_detail": verifier.get("detail", ""),
            },
        )
        write_attestation(run_root / "outcome-receipt.json", receipt)
        runtime = MemoryRuntime(runtime_config)
        try:
            runtime.record_attested_outcome(
                receipt.to_dict(),
                verifier=self.signature_verifier,
                scope=RuntimeScope(
                    subject_id=runtime.default_scope.subject_id,
                    agent_id=runtime.default_scope.agent_id,
                    task_id=task.task_id,
                    run_id=assignment.run_id,
                ),
            )
        finally:
            runtime.close()
        return receipt

    def _run_model(
        self, prompt: str, workspace: Path, run_id: str
    ) -> ProcessResult:
        model = self.protocol.raw["model"]
        command = [str(model["command"]), *[str(v) for v in model["arguments"]]]
        command.extend(
            [
                "--model",
                str(model["name"]),
                "--max-turns",
                str(self.protocol.raw["budgets"]["max_turns"]),
                "--session-id",
                str(uuid.uuid5(uuid.NAMESPACE_URL, f"aetnamem-impact:{run_id}")),
                "--single",
                prompt,
            ]
        )
        return _run_process(
            command,
            cwd=workspace,
            stdin="",
            timeout=int(self.protocol.raw["budgets"]["timeout_seconds"]),
            env={"AETNAMEM_IMPACT_RUN": "1"},
        )

    def _run_verifier(
        self,
        task: ImpactTask,
        workspace: Path,
        run_root: Path,
        process: ProcessResult,
    ) -> dict[str, Any]:
        verifier_path = task.resolve(str(task.raw["verifier"]))
        command = [
            os.environ.get("PYTHON", "python"),
            str(verifier_path),
            "--workspace",
            str(workspace),
            "--stdout",
            str(run_root / "stdout.txt"),
            "--exit-code",
            str(process.exit_code),
        ]
        result = _run_process(
            command,
            cwd=verifier_path.parent,
            stdin="",
            timeout=60,
            env={"AETNAMEM_VERIFIER": "1"},
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"host verifier failed ({result.exit_code}): {result.stderr}"
            )
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or not isinstance(value.get("success"), bool):
            raise ValueError("host verifier must emit JSON with boolean success")
        return value


def _agent_prompt(task: ImpactTask, pack: dict[str, Any]) -> str:
    return (
        "Complete the registered task in the current workspace.\n\n"
        f"{pack['stable_context']}\n\n"
        f"Task:\n{task.raw['query']}\n\n"
        f"{pack['dynamic_context']}\n"
    )


def run_paid_smoke_check(
    protocol: ImpactProtocol,
    *,
    output_path: str | Path,
) -> dict[str, Any]:
    """Prove the registered Grok invocation can edit its isolated workspace."""
    output = Path(output_path).resolve()
    workspace = output.parent / ".paid-smoke-workspace"
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing.get("protocol_sha256") != protocol.digest:
            raise ValueError("paid smoke result belongs to a different protocol")
        return existing
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    answer = workspace / "answer.txt"
    answer.write_text("", encoding="utf-8")
    nonce = f"AETNAMEM-SMOKE-{protocol.digest[:16]}"
    prompt = (
        "This is a paid readiness check for a registered experiment. "
        "Use the editing tool to replace the contents of answer.txt with exactly "
        f"{nonce} and a trailing newline. Do not only describe the edit."
    )
    model = protocol.raw["model"]
    run_id = f"smoke-{protocol.digest}"
    command = [str(model["command"]), *[str(v) for v in model["arguments"]]]
    command.extend(
        [
            "--model",
            str(model["name"]),
            "--max-turns",
            str(protocol.raw["budgets"]["max_turns"]),
            "--session-id",
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"aetnamem-impact:{run_id}")),
            "--single",
            prompt,
        ]
    )
    process = _run_process(
        command,
        cwd=workspace,
        stdin="",
        timeout=int(protocol.raw["budgets"]["timeout_seconds"]),
        env={"AETNAMEM_IMPACT_SMOKE": "1"},
    )
    stdout_path = output.parent / "paid-smoke.stdout.txt"
    stderr_path = output.parent / "paid-smoke.stderr.txt"
    stdout_path.write_text(process.stdout, encoding="utf-8")
    stderr_path.write_text(process.stderr, encoding="utf-8")
    actual = answer.read_text(encoding="utf-8")
    telemetry = _extract_telemetry(process.stdout)
    result = {
        "format": "aetnamem-memory-impact-paid-smoke-v1",
        "protocol_sha256": protocol.digest,
        "passed": (
            process.exit_code == 0
            and not process.timed_out
            and actual == f"{nonce}\n"
        ),
        "exit_code": process.exit_code,
        "timed_out": process.timed_out,
        "latency_ms": process.latency_ms,
        "answer_sha256": sha256_hex(actual),
        "expected_answer_sha256": sha256_hex(f"{nonce}\n"),
        "stdout_sha256": sha256_hex(process.stdout),
        "stderr_sha256": sha256_hex(process.stderr),
        "stdout_artifact": stdout_path.name,
        "stderr_artifact": stderr_path.name,
        "telemetry": telemetry,
    }
    result["smoke_sha256"] = sha256_hex(canonical_json(result))
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.rmtree(workspace)
    return result


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    stdin: str,
    timeout: int,
    env: dict[str, str],
) -> ProcessResult:
    started = time.monotonic()
    merged_env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"AETNAMEM_APPROVAL_KEY", "AETNAMEM_IMPACT_SIGNING_KEY"}
    }
    merged_env.update(env)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=stdin,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=merged_env,
            check=False,
        )
        return ProcessResult(
            result.returncode,
            result.stdout,
            result.stderr,
            int((time.monotonic() - started) * 1000),
            False,
        )
    except subprocess.TimeoutExpired as exc:
        return ProcessResult(
            124,
            str(exc.stdout or ""),
            str(exc.stderr or ""),
            int((time.monotonic() - started) * 1000),
            True,
        )


def _clone_sqlite(source: Path, destination: Path) -> None:
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()


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


def _extract_telemetry(stdout: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "cost_trust": "unavailable",
            "token_trust": "unavailable",
        }
    found: dict[str, float] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).lower()
                if normalized in {
                    "input_tokens",
                    "prompt_tokens",
                    "output_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "cost_usd",
                    "total_cost_usd",
                } and isinstance(child, (int, float)):
                    found[normalized] = float(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    input_tokens = found.get("input_tokens", found.get("prompt_tokens", 0.0))
    output_tokens = found.get(
        "output_tokens", found.get("completion_tokens", 0.0)
    )
    tokens = found.get("total_tokens", input_tokens + output_tokens)
    cost = found.get("cost_usd", found.get("total_cost_usd"))
    result: dict[str, Any] = {
        "tokens": int(tokens),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "token_trust": "provider_reported" if tokens else "unavailable",
        "cost_trust": "provider_reported" if cost is not None else "unavailable",
    }
    if cost is not None:
        result["cost_usd"] = float(cost)
    return result
