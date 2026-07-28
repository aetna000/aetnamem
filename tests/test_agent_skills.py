from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNED = ROOT / "skills/use-governed-memory/scripts/governed_memory.py"
AUDIT = ROOT / "skills/audit-agent-memory/scripts/audit_memory.py"
TRIAL = ROOT / "skills/trial-agent-memory/scripts/trial_memory.py"


def run_script(script: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def test_governed_memory_wrapper_remembers_finds_and_verifies(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    remembered = run_script(
        GOVERNED,
        "--db",
        str(db),
        "--subject",
        "skill-user",
        "remember",
        "My preferred report format is Markdown.",
    )
    admitted = json.loads(remembered.stdout)
    assert admitted["verification"]["valid"] is True
    assert admitted["result"]["records"][0]["status"] == "active"

    found = run_script(
        GOVERNED,
        "--db",
        str(db),
        "--subject",
        "skill-user",
        "find",
        "report format",
    )
    search = json.loads(found.stdout)
    assert search["result"]["matched"] == 1
    assert search["result"]["results"][0]["kind"] == "memory"


def test_governed_memory_wrapper_requires_confirmation_for_deletion(tmp_path: Path) -> None:
    refused = run_script(
        GOVERNED,
        "--db",
        str(tmp_path / "memory.db"),
        "--subject",
        "skill-user",
        "forget",
        "--contains",
        "email",
        check=False,
    )
    assert refused.returncode != 0
    assert "explicit --confirm" in refused.stderr


def test_audit_wrapper_verifies_searches_logs_access_and_exports(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    run_script(
        GOVERNED,
        "--db",
        str(db),
        "--subject",
        "skill-user",
        "remember",
        "My preferred report format is Markdown.",
    )
    output = tmp_path / "trace.json"
    traced = run_script(
        AUDIT,
        "--db",
        str(db),
        "--subject",
        "skill-user",
        "--actor",
        "auditor-1",
        "trace",
        "report format",
        "--output",
        str(output),
    )
    report = json.loads(traced.stdout)
    assert report["verification"]["valid"] is True
    assert report["result"]["audit_chain_valid"] is True
    assert report["result"]["timeline"]
    assert json.loads(output.read_text(encoding="utf-8")) == report

    access = subprocess.run(
        [
            sys.executable,
            "-m",
            "aetnamem.cli",
            "access-log",
            str(db),
            "--subject",
            "skill-user",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "auditor-1" in access.stdout


def test_trial_wrapper_help_and_confirmation_gate() -> None:
    assert run_script(TRIAL, "--help").returncode == 0
    refused = run_script(TRIAL, "activate", check=False)
    assert refused.returncode != 0
    assert "explicit --confirm" in refused.stderr


def test_skill_and_plugin_manifests_have_no_placeholders() -> None:
    for skill in (
        "use-governed-memory",
        "audit-agent-memory",
        "trial-agent-memory",
    ):
        content = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "[TODO:" not in content

    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "aetnamem"
    assert manifest["skills"] == "./skills/"
