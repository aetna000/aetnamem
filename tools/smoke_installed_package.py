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
    assert scripts == {"aetnamem": "aetnamem.cli:main"}, scripts

    executable = Path(sys.executable).with_name("aetnamem")
    assert executable.is_file(), "aetnamem console command was not installed"
    run(str(executable), "--help")

    with tempfile.TemporaryDirectory(prefix="aetnamem-wheel-smoke-") as temp:
        root = Path(temp)
        database = root / "memory.db"
        workspace = root / "workspace"
        workspace.mkdir()

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
        memory_verification = json_run(str(executable), "verify", str(database))
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
