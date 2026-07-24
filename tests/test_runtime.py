from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from aetnamem import Memory
from aetnamem.mcp import MCPServer
from aetnamem.runtime import MemoryRuntime, RuntimeScope, preset_config


LEGACY_TOOL_NAMES = [
    "memory_remember",
    "memory_recall",
    "memory_recall_block",
    "memory_persona",
    "memory_context_pack",
    "memory_capture",
    "memory_list",
    "memory_forget",
    "memory_promote",
    "memory_audit",
    "memory_verify",
    "memory_graph_status",
    "memory_graph_merges",
    "memory_graph_history",
    "memory_log_action",
]


def _runtime(tmp_path: Path, *, skill_path: Path | None = None) -> MemoryRuntime:
    config = preset_config(
        "benchmark",
        db_path=str(tmp_path / "memory.db"),
        subject_id="alice",
        agent_id="openclaw-primary",
        skill_paths=[str(skill_path)] if skill_path else None,
    )
    return MemoryRuntime(config)


def test_four_planes_prepare_and_outcome_learning(tmp_path: Path) -> None:
    skill = tmp_path / "report-skill" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text(
        "---\nname: report-uploader\ndescription: Upload and verify customer reports\n---\n"
        "# Report uploader\nCheck the destination, upload once, then verify the receipt.\n",
        encoding="utf-8",
    )
    runtime = _runtime(tmp_path, skill_path=skill)
    try:
        runtime.memory.remember("alice", "My preferred report format is PDF.")
        pack = runtime.prepare_turn(
            "Upload the customer PDF report",
            task_state={"goal": "upload report", "progress": "PDF generated"},
            scope=RuntimeScope(
                subject_id="alice",
                agent_id="openclaw-primary",
                session_id="s1",
                task_id="report",
            ),
        )
        assert pack["format"] == "aetnamem-runtime-pack-v1"
        assert [item["plane"] for item in pack["contributions"]] == [
            "working",
            "semantic",
            "episodic",
            "procedural",
        ]
        assert "PDF" in pack["stable_context"] + pack["dynamic_context"]
        assert "<working_memory>" in pack["dynamic_context"]
        assert "report-uploader" in pack["stable_context"]
        assert pack["legacy_context_pack"]["format"] == "aetnamem-context-pack-v1"
        assert pack["degraded_planes"] == []

        outcome = runtime.record_outcome(
            pack["run_id"],
            success=False,
            summary="Customer report upload timed out",
            idempotency_key="report-attempt-1",
        )
        assert outcome["created"] is True
        assert outcome["lesson_proposals"][0]["status"] == "quarantined"
        assert outcome["procedure_proposals"][0]["status"] == "quarantined"
        lesson_id = outcome["lesson_proposals"][0]["id"]

        duplicate = runtime.record_outcome(
            pack["run_id"],
            success=False,
            summary="Customer report upload timed out",
            idempotency_key="report-attempt-1",
        )
        assert duplicate["created"] is False

        runtime.promote_lesson(lesson_id)
        next_pack = runtime.prepare_turn("Retry the customer report upload")
        episodic = next(
            item for item in next_pack["contributions"] if item["plane"] == "episodic"
        )
        assert "Prior attempt failed" in episodic["content"]
        assert "Reviewed lesson" in episodic["content"]
        assert runtime.status()["counts"]["experience_outcomes"] == 1

        deleted = runtime.forget(contains="PDF")
        assert deleted["deleted"] is True
        assert deleted["receipt"]["format"] == "aetnamem-runtime-deletion-receipt-v1"
        assert deleted["runtime_purged"]["working_snapshot_ids"]
        after_delete = runtime.prepare_turn("What is the report format?")
        assert "PDF" not in (
            after_delete["stable_context"] + after_delete["dynamic_context"]
        )
    finally:
        runtime.close()


def test_runtime_scope_identity_is_pinned(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        with pytest.raises(ValueError, match="subject_id is pinned"):
            runtime.prepare_turn(
                "steal context",
                scope=RuntimeScope(
                    subject_id="bob",
                    agent_id="openclaw-primary",
                ),
            )
    finally:
        runtime.close()


def test_cml_shadow_records_assignment_without_changing_context(
    tmp_path: Path,
) -> None:
    config = preset_config(
        "starter",
        db_path=str(tmp_path / "memory.db"),
        subject_id="alice",
        agent_id="agent-1",
    )
    config["cml"] = {
        "mode": "shadow",
        "experiment_id": "shadow-study",
        "design": "bernoulli",
        "policy_version": "shadow-v1",
        "assignment_probability": 0.0,
        "eligible_planes": [
            "working",
            "semantic",
            "episodic",
            "procedural",
        ],
        "pinned_planes": [],
        "seed": "test-seed-that-must-not-leak",
    }
    runtime = MemoryRuntime(config)
    try:
        pack = runtime.prepare_turn(
            "prepare the report",
            task_state={"goal": "prepare report"},
        )
        assert pack["format"] == "aetnamem-runtime-pack-v2"
        assert [item["plane"] for item in pack["contributions"]] == [
            "working",
            "semantic",
            "episodic",
            "procedural",
        ]
        assert pack["cml"]["mode"] == "shadow"
        assert pack["cml"]["arm_id"] == "0000"
        assert pack["cml"]["applied_arm_id"] == "1111"
        assert all(not item["assigned"] for item in pack["cml"]["decisions"])
        assert all(item["applied"] for item in pack["cml"]["decisions"])
        assert "test-seed-that-must-not-leak" not in json.dumps(pack)
        stored = runtime.store.interventions_for_run(pack["run_id"])
        assert len(stored) == 4
        assert all(not item["assigned"] and item["applied"] for item in stored)
        assert runtime.status()["counts"]["runtime_interventions"] == 4

        with pytest.raises(ValueError, match="committed manifest_sha256"):
            runtime.record_outcome(pack["run_id"], success=True)
        with pytest.raises(ValueError, match="does not match"):
            runtime.record_outcome(
                pack["run_id"],
                success=True,
                manifest_sha256="wrong",
            )
        outcome = runtime.record_outcome(
            pack["run_id"],
            success=True,
            manifest_sha256=pack["manifest_sha256"],
            metrics={"verifier": "pytest", "tokens": 123},
        )
        assert outcome["manifest_sha256"] == pack["manifest_sha256"]
        assert outcome["metrics"] == {"verifier": "pytest", "tokens": 123}
        assert outcome["outcome_trust"] == "caller_asserted"
    finally:
        runtime.close()


def test_cml_experiment_applies_logged_assignment_and_keeps_pins(
    tmp_path: Path,
) -> None:
    config = preset_config(
        "benchmark",
        db_path=str(tmp_path / "memory.db"),
        subject_id="alice",
        agent_id="agent-1",
    )
    config["cml"] = {
        "mode": "experiment",
        "experiment_id": "factorial-study",
        "design": "bernoulli",
        "policy_version": "experiment-v1",
        "assignment_probability": 0.5,
        "eligible_planes": ["working", "episodic", "procedural"],
        "pinned_planes": ["semantic"],
        "seed": "reproducible-test-seed",
    }
    runtime = MemoryRuntime(config)
    try:
        pack = runtime.prepare_turn(
            "prepare the report",
            task_state={"goal": "prepare report"},
        )
        assert pack["format"] == "aetnamem-runtime-pack-v2"
        decisions = {item["plane"]: item for item in pack["cml"]["decisions"]}
        assert decisions["semantic"]["eligibility"] == "pinned"
        assert decisions["semantic"]["assigned"] is True
        assert decisions["semantic"]["applied"] is True
        assert decisions["semantic"]["propensity"] == 1.0
        admitted = {item["plane"] for item in pack["contributions"]}
        expected = {
            plane for plane, item in decisions.items() if item["applied"]
        }
        assert admitted == expected
        assert "semantic" in admitted
        assert pack["cml"]["arm_id"] == pack["cml"]["applied_arm_id"]
        assert pack["manifest"]["cml"] == pack["cml"]
    finally:
        runtime.close()


def test_cml_configuration_requires_explicit_safe_activation(tmp_path: Path) -> None:
    config = preset_config(
        "starter",
        db_path=str(tmp_path / "memory.db"),
        subject_id="alice",
    )
    assert config["cml"]["mode"] == "off"
    runtime = MemoryRuntime(config)
    try:
        pack = runtime.prepare_turn("hello")
        assert pack["format"] == "aetnamem-runtime-pack-v1"
        assert "cml" not in pack
        assert runtime.status()["counts"]["runtime_interventions"] == 0
    finally:
        runtime.close()

    config["cml"] = {
        "mode": "experiment",
        "eligible_planes": ["semantic"],
        "assignment_probability": 0.5,
    }
    with pytest.raises(ValueError, match="requires experiment_id"):
        MemoryRuntime(config)

    config["cml"] = {
        "mode": "experiment",
        "experiment_id": "unsafe-production-study",
        "seed": "test-seed",
        "eligible_planes": ["semantic"],
        "assignment_probability": 0.5,
    }
    with pytest.raises(ValueError, match="restricted to the benchmark preset"):
        MemoryRuntime(config)


def test_runtime_degrades_one_provider_without_losing_the_turn(tmp_path: Path) -> None:
    class FailingEpisodic:
        plane = "episodic"

        def prepare(self, request):
            raise RuntimeError("remote episodic provider unavailable")

        def record_outcome(self, outcome):
            return []

        def health(self):
            raise AssertionError("health is not needed in this assertion")

    config = preset_config(
        "starter",
        db_path=str(tmp_path / "memory.db"),
        subject_id="alice",
        agent_id="agent-1",
    )
    runtime = MemoryRuntime(config, providers={"episodic": FailingEpisodic()})
    try:
        pack = runtime.prepare_turn("finish task", task_state={"goal": "finish"})
        assert pack["degraded_planes"] == ["episodic"]
        assert "remote episodic provider unavailable" in pack["provider_failures"]["episodic"]
        assert "<working_memory>" in pack["dynamic_context"]
    finally:
        runtime.close()


def test_runtime_schema_is_additive_for_legacy_memory(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    runtime = MemoryRuntime(
        preset_config(
            "private",
            db_path=str(db),
            subject_id="alice",
            agent_id="agent-1",
        )
    )
    runtime.prepare_turn("hello", task_state={"goal": "test"})
    runtime.close()

    legacy = Memory(db)
    try:
        stored = legacy.remember("alice", "My timezone is Australia/Sydney.")
        assert stored["records"]
        assert legacy.recall("alice", "timezone")[0]["content"].endswith("Sydney.")
    finally:
        legacy.close()


def test_default_mcp_catalog_is_unchanged_and_runtime_is_opt_in(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory.db")
    default_server = MCPServer(memory)
    default_tools = default_server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert [item["name"] for item in default_tools["result"]["tools"]] == LEGACY_TOOL_NAMES

    runtime = MemoryRuntime(
        preset_config(
            "starter",
            db_path=str(tmp_path / "runtime.db"),
            subject_id="alice",
            agent_id="openclaw-primary",
        )
    )
    try:
        server = MCPServer(
            runtime.memory,
            default_subject="alice",
            runtime=runtime,
        )
        tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert [item["name"] for item in tools["result"]["tools"]] == [
            *LEGACY_TOOL_NAMES,
            "memory_prepare_turn",
            "memory_record_outcome",
        ]
    finally:
        memory.close()
        runtime.close()


def test_noninteractive_setup_is_a_ten_step_wizard(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aetnamem.cli",
            "setup",
            "--yes",
            "--db",
            str(tmp_path / "memory.db"),
            "--output",
            str(tmp_path / "runtime.json"),
            "--subject",
            "alice",
            "--agent",
            "openclaw-primary",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for number in range(1, 11):
        assert f"Step {number}/10" in result.stdout
    config = json.loads((tmp_path / "runtime.json").read_text())
    assert config["preset"] == "starter"
    assert set(config["planes"]) == {
        "working",
        "semantic",
        "episodic",
        "procedural",
    }


def test_release_versions_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    project_text = (root / "pyproject.toml").read_text()
    project_version = re.search(
        r"(?m)^version = \"([^\"]+)\"$", project_text
    )
    assert project_version and project_version.group(1) == "0.5.0"
    package = json.loads((root / "integrations/openclaw/package.json").read_text())
    lock = json.loads((root / "integrations/openclaw/package-lock.json").read_text())
    manifest = json.loads(
        (root / "integrations/openclaw/openclaw.plugin.json").read_text()
    )
    assert package["version"] == lock["version"] == manifest["version"] == "0.3.0"
