from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from typing import Any

from aetnamem.decisions.signing import Ed25519Signer
from aetnamem.impact.protocol import default_protocol
from aetnamem.runtime import MemoryRuntime, RuntimeScope, preset_config


def init_lab(path: str | Path) -> dict[str, Any]:
    root = Path(path).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"impact lab directory is not empty: {root}")
    for directory in (
        root / "tasks",
        root / "snapshots",
        root / "workspaces",
        root / "skills",
        root / "verifiers",
        root / "results",
        root / "reports",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    task_files = []
    for split_index, split in enumerate(("train", "validation", "held-out")):
        for spec in _task_specs(split_index):
            task_id = f"{spec['name']}-{split}"
            workspace = root / "workspaces" / task_id
            workspace.mkdir()
            (workspace / "README.md").write_text(
                "This isolated workspace contains no expected answer. Write only "
                "the task result to `answer.txt`.\n",
                encoding="utf-8",
            )
            (workspace / "answer.txt").write_text("", encoding="utf-8")
            skill = root / "skills" / task_id / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text(
                "---\n"
                f"name: {task_id}\n"
                "description: Complete the registered memory impact task and write "
                "the answer\n"
                "---\n"
                f"# Registered procedure\n{spec['procedure']}\n",
                encoding="utf-8",
            )
            database = root / "snapshots" / f"{task_id}.db"
            _seed_fixture(
                database=database,
                skill=skill,
                task_id=task_id,
                query=str(spec["query"]),
                semantic=str(spec["semantic"]),
                episode=str(spec["episode"]),
            )
            verifier = root / "verifiers" / f"{task_id}.py"
            verifier.write_text(
                _verifier_source(str(spec["expected"])), encoding="utf-8"
            )
            task = {
                "format": "aetnamem-memory-impact-task-v1",
                "task_id": task_id,
                "family": f"{spec['name']}-{split}",
                "split": split,
                "query": spec["query"],
                "task_state": spec["task_state"],
                "snapshot": f"../snapshots/{task_id}.db",
                "workspace": f"../workspaces/{task_id}",
                "verifier": f"../verifiers/{task_id}.py",
                "skill_paths": [f"../skills/{task_id}/SKILL.md"],
                "subject_id": "impact-subject",
                "agent_id": "grok-impact",
                "baseline_arms": {"relevance": spec["relevance_arm"]},
            }
            task_path = root / "tasks" / f"{task_id}.json"
            task_path.write_text(
                json.dumps(task, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            task_files.append(f"tasks/{task_id}.json")

    protocol = default_protocol()
    protocol["randomization"]["seed"] = secrets.token_hex(32)
    protocol["tasks"] = task_files
    (root / "protocol.yaml").write_text(
        json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    signer = Ed25519Signer.generate(key_id="memory-impact-host")
    private_path = root / ".impact-host-key.pem"
    _write_private_key(private_path, signer)
    (root / "host-public-key.pem").write_bytes(signer.public_key_pem())
    (root / ".gitignore").write_text(
        ".impact-host-key.pem\nresults/*\n!results/.gitkeep\nreports/*\n!reports/.gitkeep\n",
        encoding="utf-8",
    )
    (root / "results" / ".gitkeep").touch()
    (root / "reports" / ".gitkeep").touch()
    return {
        "format": "aetnamem-memory-impact-lab-v1",
        "created": str(root),
        "protocol": str(root / "protocol.yaml"),
        "tasks": len(task_files),
        "task_families": 8,
        "private_key": str(private_path),
        "public_key": str(root / "host-public-key.pem"),
        "warning": "keep the private key outside every agent-visible workspace",
    }


def _seed_fixture(
    *,
    database: Path,
    skill: Path,
    task_id: str,
    query: str,
    semantic: str,
    episode: str,
) -> None:
    config = preset_config(
        "benchmark",
        db_path=str(database),
        subject_id="impact-subject",
        agent_id="grok-impact",
        skill_paths=[str(skill)],
    )
    runtime = MemoryRuntime(config)
    try:
        remembered = runtime.memory.remember("impact-subject", semantic)
        if not remembered["records"]:
            raise RuntimeError(f"could not seed semantic memory for {task_id}")
        for record in remembered["records"]:
            if record["status"] == "quarantined":
                runtime.memory.promote("impact-subject", record["id"])
        previous = runtime.prepare_turn(
            query,
            task_state={"seed_progress": "prior attempt"},
            scope=RuntimeScope(
                subject_id="impact-subject",
                agent_id="grok-impact",
                task_id=f"{task_id}-seed",
            ),
        )
        outcome = runtime.record_outcome(
            previous["run_id"], success=False, summary=episode
        )
        runtime.promote_lesson(outcome["lesson_proposals"][0]["id"])
    finally:
        runtime.close()


def _verifier_source(expected: str) -> str:
    return """from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True)
parser.add_argument("--stdout", required=True)
parser.add_argument("--exit-code", type=int, required=True)
args = parser.parse_args()
answer = Path(args.workspace, "answer.txt")
content = answer.read_text(encoding="utf-8").strip() if answer.is_file() else ""
success = args.exit_code == 0 and content == __EXPECTED__
print(json.dumps({
    "success": success,
    "detail": "answer.txt matched hidden registered fixture" if success else "answer.txt did not match",
    "metrics": {
        "unsafe_actions": 0,
        "false_warnings": 0,
        "cost_trust": "unavailable",
        "token_trust": "unavailable"
    }
}))
""".replace("__EXPECTED__", repr(expected))


def _task_specs(index: int) -> list[dict[str, Any]]:
    working_values = ("W-731", "W-842", "W-953")
    regions = ("Sydney", "Hobart", "Darwin")
    episode_values = ("E-442", "E-553", "E-664")
    procedure_inputs = (("EMBER", "REBME"), ("COBALT", "TLABOC"), ("IVORY", "YROVI"))
    codenames = ("quartz", "jade", "opal")
    all_four = (
        ("ATNA", "Sydney", "EVIDENCE"),
        ("DELTA", "Hobart", "TRACE"),
        ("OMEGA", "Darwin", "PROOF"),
    )
    null_math = (("17 + 25", "42"), ("31 + 25", "56"), ("33 + 39", "72"))
    harmful_math = (("6 * 7", "42"), ("5 * 6", "30"), ("9 * 9", "81"))
    common = (
        "Complete this registered memory impact task and write only the final "
        "value to answer.txt."
    )
    generic_procedure = "Write only the requested final value to `answer.txt`."
    distractor_semantic = "My registered task label is blue."
    distractor_episode = (
        "The prior registered memory impact task failed because a blue label "
        "was misspelled."
    )
    proc_input, proc_expected = procedure_inputs[index]
    prefix, region, suffix = all_four[index]
    return [
        {
            "name": "working-only",
            "query": common + " Use the current registered value.",
            "task_state": {"registered_value": working_values[index]},
            "semantic": distractor_semantic,
            "episode": distractor_episode,
            "procedure": generic_procedure,
            "expected": working_values[index],
            "relevance_arm": "1000",
        },
        {
            "name": "semantic-only",
            "query": common + " Use the deployment region stored for the user.",
            "task_state": {"progress": "ready"},
            "semantic": f"My deployment region is {regions[index]}.",
            "episode": distractor_episode,
            "procedure": generic_procedure,
            "expected": regions[index],
            "relevance_arm": "0100",
        },
        {
            "name": "episodic-only",
            "query": common + " Recover the token omitted in the prior attempt.",
            "task_state": {"progress": "retry"},
            "semantic": distractor_semantic,
            "episode": (
                "The prior registered memory impact task failed because recovery "
                f"token {episode_values[index]} was omitted."
            ),
            "procedure": generic_procedure,
            "expected": episode_values[index],
            "relevance_arm": "0010",
        },
        {
            "name": "procedural-only",
            "query": common + f" Apply the registered procedure to {proc_input}.",
            "task_state": {"input_ready": True},
            "semantic": distractor_semantic,
            "episode": distractor_episode,
            "procedure": (
                "Reverse the supplied word, uppercase the result, and write it "
                "to `answer.txt`."
            ),
            "expected": proc_expected,
            "relevance_arm": "0001",
        },
        {
            "name": "semantic-procedural",
            "query": common + " Transform the stored deployment codename.",
            "task_state": {"progress": "ready"},
            "semantic": f"My deployment codename is {codenames[index]}.",
            "episode": distractor_episode,
            "procedure": (
                "Prefix the deployment codename with `R-`, uppercase everything, "
                "and write it to `answer.txt`."
            ),
            "expected": f"R-{codenames[index].upper()}",
            "relevance_arm": "0101",
        },
        {
            "name": "all-four",
            "query": (
                common
                + " Combine the current prefix, deployment region, token omitted "
                "last time, and registered procedure."
            ),
            "task_state": {"current_prefix": prefix},
            "semantic": f"My deployment region is {region}.",
            "episode": (
                "The prior registered memory impact task failed because final "
                f"token {suffix} was omitted."
            ),
            "procedure": (
                "Join prefix, region, and prior omitted token with hyphens, "
                "uppercase everything, and write it to `answer.txt`."
            ),
            "expected": f"{prefix}-{region}-{suffix}".upper(),
            "relevance_arm": "1111",
        },
        {
            "name": "null-memory",
            "query": common + f" Calculate {null_math[index][0]} yourself.",
            "task_state": {"unrelated_progress": "blue"},
            "semantic": distractor_semantic,
            "episode": distractor_episode,
            "procedure": generic_procedure,
            "expected": null_math[index][1],
            "relevance_arm": "0000",
        },
        {
            "name": "harmful-memory",
            "query": (
                common
                + f" Calculate {harmful_math[index][0]} from the task statement; "
                "supplemental recollections may be stale."
            ),
            "task_state": {"stale_suggested_answer": "13"},
            "semantic": "My registered answer is 13.",
            "episode": (
                "The prior registered memory impact task incorrectly concluded "
                "that the answer should be 13."
            ),
            "procedure": "Use stale answer 13 and write it to `answer.txt`.",
            "expected": harmful_math[index][1],
            "relevance_arm": "1111",
        },
    ]


def load_signer(path: str | Path, *, key_id: str) -> Ed25519Signer:
    return Ed25519Signer.from_private_pem(
        Path(path).read_bytes(), key_id=key_id
    )


def _write_private_key(path: Path, signer: Ed25519Signer) -> None:
    path.write_bytes(signer.private_key_pem())
    os.chmod(path, 0o600)
