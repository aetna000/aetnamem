#!/usr/bin/env python3
"""Exercise an installed aetnamem wheel without importing the source checkout."""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def json_run(*args: str, env: dict[str, str] | None = None) -> object:
    return json.loads(run(*args, env=env).stdout)


def main() -> None:
    distribution = importlib.metadata.distribution("aetnamem")
    assert distribution.version
    scripts = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    assert scripts == {
        "aetnamem": "aetnamem.cli:main",
        "aetnamem-etd-playground": "aetnamem.etd.playground:main",
        "aetnamem-etd-verify": "aetnamem.decisions.verify:main",
        "aetnamem-service": "aetnamem.service.__main__:main",
    }, scripts

    executable = Path(sys.executable).with_name("aetnamem")
    assert executable.is_file(), "aetnamem console command was not installed"
    run(str(executable), "--help")
    service_executable = Path(sys.executable).with_name("aetnamem-service")
    assert service_executable.is_file(), "aetnamem-service command was not installed"
    run(str(service_executable), "--help")
    etd_playground = Path(sys.executable).with_name("aetnamem-etd-playground")
    etd_verify = Path(sys.executable).with_name("aetnamem-etd-verify")
    assert etd_playground.is_file() and etd_verify.is_file()

    with tempfile.TemporaryDirectory(prefix="aetnamem-wheel-smoke-") as temp:
        root = Path(temp)
        database = root / "memory.db"
        workspace = root / "workspace"
        workspace.mkdir()

        decision_output = root / "decision-output"
        run(
            str(etd_playground),
            "--db",
            str(database),
            "--output",
            str(decision_output),
            "--namespace",
            "wheel-smoke-hospital",
        )
        decision_verification = json.loads(
            run(str(etd_verify), str(decision_output / "decision-bundle.json")).stdout
        )
        assert decision_verification["valid"] is True, decision_verification
        assert "Criterion assessments" in (decision_output / "etd-report.md").read_text()

        json_run(
            str(executable),
            "remember",
            str(database),
            "release-smoke",
            "My preferred editor is Vim.",
            "--session",
            "wheel-test",
        )
        recalled = json_run(
            str(executable),
            "recall",
            str(database),
            "release-smoke",
            "preferred editor",
        )
        assert isinstance(recalled, list) and recalled
        assert "Vim" in recalled[0]["content"]
        json_run(
            str(executable),
            "remember",
            str(database),
            "release-smoke",
            "My boss is Sarah.",
        )
        json_run(
            str(executable),
            "remember",
            str(database),
            "release-smoke",
            "Sarah's preferred airport is SEA.",
        )
        graph_recalled = json_run(
            str(executable),
            "recall",
            str(database),
            "release-smoke",
            "What airport does my boss prefer?",
            "--graph",
        )
        assert isinstance(graph_recalled, list)
        assert any(
            "SEA" in item["content"] and "graph" in item
            for item in graph_recalled
        ), graph_recalled
        graph_report = json_run(
            str(executable),
            "graph-consolidate",
            str(database),
            "release-smoke",
        )
        assert graph_report["counts"]["edges"] >= 3, graph_report
        memory_verification = json_run(
            str(executable), "verify", str(database), "--incremental"
        )
        assert memory_verification["valid"] is True, memory_verification

        staged = json_run(
            str(executable),
            "actions",
            "stage",
            str(database),
            "release-smoke",
            "filesystem",
            "write_text",
            "--root",
            str(workspace),
            "--args",
            json.dumps({"path": "result.txt", "content": "clean wheel works"}),
            "--actor",
            "package-smoke",
            "--authority-id",
            "release-gate",
            "--authority-digest",
            "0123456789abcdef" * 4,
        )
        transaction_id = staged["transaction_id"]
        approval_env = dict(os.environ)
        approval_env["AETNAMEM_APPROVAL_KEY"] = "abcdef0123456789" * 4
        json_run(
            str(executable),
            "actions",
            "approve",
            str(database),
            transaction_id,
            "--approver-label",
            "release-gate",
            env=approval_env,
        )
        json_run(
            str(executable),
            "actions",
            "commit",
            str(database),
            transaction_id,
            "--root",
            str(workspace),
            env=approval_env,
        )
        action_verification = json_run(
            str(executable),
            "actions",
            "verify",
            str(database),
            transaction_id,
            env=approval_env,
        )
        assert action_verification["valid"] is True, action_verification
        assert (workspace / "result.txt").read_text() == "clean wheel works"

    print("installed wheel smoke test passed")


if __name__ == "__main__":
    main()
