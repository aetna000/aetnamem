#!/usr/bin/env python3
"""Validate the paper's pinned data and committed flagship-demo evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


PAPER = Path(__file__).resolve().parents[1]
REPO = PAPER.parent
DATA = PAPER / "data"
DEMO = REPO / "examples" / "flagship-demo" / "artifacts"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args: str) -> str:
    result = subprocess.run(args, cwd=REPO, text=True, capture_output=True)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip()


def validate_benchmark() -> None:
    rows = read_csv("benchmark-results.csv")
    require(len(rows) == 19, "expected 19 public benchmark targets")
    aetna = next(row for row in rows if row["framework"] == "aetnamem")
    require((aetna["checks_passed"], aetna["checks_total"]) == ("33", "33"), "aetnamem check score drifted")
    require((aetna["scenarios_passed"], aetna["scenarios_total"]) == ("5", "5"), "aetnamem scenario score drifted")
    require((aetna["weighted_passed"], aetna["weighted_total"]) == ("81", "81"), "aetnamem weighted score drifted")
    perfect = sum(row["checks_passed"] == row["checks_total"] for row in rows)
    require(perfect == 12, "public perfect-score tie count drifted")

    audits = read_csv("auditability.csv")
    require(len(audits) == 19, "expected 19 auditability rows")
    aetna_audit = next(row for row in audits if row["framework"] == "aetnamem")
    require((aetna_audit["points"], aetna_audit["possible"]) == ("16", "18"), "aetnamem auditability score drifted")
    require(max(int(row["points"]) for row in audits if row["framework"] != "aetnamem") == 13, "comparison auditability maximum drifted")


def validate_artifact_hashes() -> None:
    provenance = json.loads((DATA / "reproduction.json").read_text(encoding="utf-8"))
    expected = provenance["demo_artifacts"]
    mapping = {
        "memories_db_sha256": DEMO / "memories.db",
        "checkpoints_jsonl_sha256": DEMO / "checkpoints.jsonl",
        "transcript_txt_sha256": DEMO / "transcript.txt",
    }
    for key, path in mapping.items():
        require(path.exists(), f"missing demo artifact: {path}")
        require(sha256(path) == expected[key], f"artifact digest mismatch: {path.name}")


def validate_demo_database() -> None:
    metrics = json.loads((DATA / "demo-metrics.json").read_text(encoding="utf-8"))
    database = DEMO / "memories.db"
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        event_count = connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        counts = dict(connection.execute("SELECT status, COUNT(*) FROM records GROUP BY status"))
        transactions = connection.execute("SELECT id, state FROM action_transactions").fetchall()
        receipts = connection.execute("SELECT COUNT(*) FROM action_receipts").fetchone()[0]
    require(event_count == metrics["audit_events"], "audit-event count mismatch")
    require(counts.get("active") == metrics["active_records"], "active-record count mismatch")
    require(counts.get("quarantined") == metrics["quarantined_records"], "quarantine count mismatch")
    require(len(transactions) == 1, "expected one recorded action transaction")
    require(transactions[0]["id"] == metrics["action_transaction_id"], "action id mismatch")
    require(transactions[0]["state"] == "committed", "action is not committed")
    require(receipts == metrics["authorized_commits"], "receipt count mismatch")


def validate_standalone_verifiers() -> None:
    metrics = json.loads((DATA / "demo-metrics.json").read_text(encoding="utf-8"))
    audit = run(
        sys.executable,
        "tools/verify_audit.py",
        str(DEMO / "memories.db"),
        "--checkpoints",
        str(DEMO / "checkpoints.jsonl"),
    )
    action = run(
        sys.executable,
        "tools/verify_actions.py",
        str(DEMO / "memories.db"),
        metrics["action_transaction_id"],
    )
    require(audit == "OK   demo-user", f"unexpected audit verifier output: {audit}")
    require(action == f'OK   {metrics["action_transaction_id"]}', f"unexpected action verifier output: {action}")


def main() -> None:
    validate_benchmark()
    validate_artifact_hashes()
    validate_demo_database()
    validate_standalone_verifiers()
    print("OK   paper benchmark tables")
    print("OK   flagship artifact digests and database metrics")
    print("OK   standalone audit and action verifiers")


if __name__ == "__main__":
    main()
