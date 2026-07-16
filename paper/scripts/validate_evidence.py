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


def validate_governed_memory_probe() -> None:
    probe = json.loads(
        (DATA / "governed-memory-probe.json").read_text(encoding="utf-8")
    )
    artifact = probe["artifact"]
    workload = probe["workload"]
    results = probe["results"]

    require(artifact["aetnamem_version"] == "0.3.0", "governed-memory release drifted")
    require(
        artifact["script"] == "paper/scripts/run_governed_memory_probe.py",
        "governed-memory probe path drifted",
    )
    require(len(artifact["commit"]) == 40, "governed-memory commit is not a full hash")
    run("git", "cat-file", "-e", f'{artifact["commit"]}^{{commit}}')

    require(workload["synthetic_records"] == 10_000, "synthetic record count drifted")
    require(workload["canonical_records"] == 10_002, "canonical record count drifted")
    require(workload["candidate_cap"] == 200, "candidate cap drifted")
    require(workload["iterations"] == 25, "probe iteration count drifted")
    require(workload["result_limit"] == 10, "probe result limit drifted")

    require(results["direct_target_rank"] is None, "direct recall now finds the target")
    require(results["graph_target_rank"] == 2, "graph target rank drifted")
    require(results["graph_visited_edges"] == 2, "visited-edge count drifted")
    require(results["logged_candidates"] == 50, "logged candidate count drifted")

    direct = results["direct_ms"]
    graph = results["graph_ms"]
    require(direct["median"] > 0 and graph["median"] > 0, "invalid median timing")
    require(
        direct["p95_order_statistic"] >= direct["median"]
        and graph["p95_order_statistic"] >= graph["median"],
        "p95 order statistic is below its median",
    )

    manuscript = (PAPER / "sections" / "governed-memory" / "10-evaluation.tex").read_text(
        encoding="utf-8"
    )
    overhead = graph["median"] - direct["median"]
    expected_fragments = [
        f'Median recall & {direct["median"]:.3f} & {graph["median"]:.3f}',
        (
            "p95 order statistic & "
            f'{direct["p95_order_statistic"]:.3f} & '
            f'{graph["p95_order_statistic"]:.3f}'
        ),
        f'Ingestion of all 10,002 records took {results["ingest_ms"]:,.3f}\\,ms',
        f"Graph recall added {overhead:.3f}\\,ms",
    ]
    for fragment in expected_fragments:
        require(fragment in manuscript, f"manuscript/probe mismatch: {fragment}")


def validate_recall_forensics() -> None:
    evidence = json.loads((DATA / "recall-forensics.json").read_text(encoding="utf-8"))
    artifact = evidence["artifact"]
    workload = evidence["workload"]
    results = evidence["results"]

    require(artifact["package_version"] == "0.3.0", "forensics package version drifted")
    require(
        artifact["script"] == "paper/scripts/run_recall_forensics_eval.py",
        "forensics script path drifted",
    )
    require(
        artifact["state"] == "content-addressed post-v0.3.0 development snapshot",
        "forensics source-state label drifted",
    )
    require(len(artifact["base_commit"]) == 40, "forensics base commit is not full")
    run("git", "cat-file", "-e", f'{artifact["base_commit"]}^{{commit}}')
    source_files = artifact["source_files_sha256"]
    require(len(source_files) == 42, "forensics source-manifest file count drifted")
    required_files = {
        "aetnamem/memory.py",
        "aetnamem/graph.py",
        "aetnamem/retrieve/rank.py",
        "aetnamem/store/sqlite.py",
        "paper/scripts/run_recall_forensics_eval.py",
        "pyproject.toml",
    }
    require(required_files <= set(source_files), "forensics manifest misses core files")
    for relative, expected in source_files.items():
        path = (REPO / relative).resolve()
        require(path.is_relative_to(REPO.resolve()), f"manifest path escapes repo: {relative}")
        require(path.is_file(), f"manifest source file missing: {relative}")
        require(sha256(path) == expected, f"manifest source digest mismatch: {relative}")
    manifest_json = json.dumps(source_files, sort_keys=True, separators=(",", ":"))
    manifest_sha256 = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    require(
        manifest_sha256 == artifact["source_manifest_sha256"],
        "forensics source-manifest digest mismatch",
    )

    require(workload["recall_turns"] == 14, "forensics turn count drifted")
    require(workload["filler_records"] == 1_000, "forensics filler count drifted")
    require(workload["historical_turns"] == 3, "historical turn count drifted")
    require(workload["stable_replay_turns"] == 11, "stable turn count drifted")
    require(workload["graph_recall_turns"] == 9, "forensics graph turn count drifted")
    require(workload["limits_tested"] == [3, 4, 5, 6, 7], "forensics limits drifted")
    require(workload["min_scores_tested"] == [0.25], "forensics threshold drifted")
    require(workload["candidate_cap"] == 200, "forensics candidate cap drifted")

    require(results["baseline_chain_failures"] == 0, "baseline chain must verify")
    require(results["baseline_digest_failures"] == 0, "baseline digests must verify")
    require(results["baseline_lifecycle_failures"] == 0, "lifecycle replay must verify")
    require(
        results["baseline_turn_semantic_failures"] == 0,
        "turn arithmetic and ordering must verify",
    )
    pairs = results["returned_pairs"]
    require(pairs == 68, "returned-pair count drifted")
    for key in (
        "f1_attribution_recomputed",
        "f2_provenance_commitments_complete",
        "f3_lifecycle_admissible",
    ):
        require(results[key] == pairs, f"{key} is not complete over all pairs")
    require(results["f1_ranking_turns_recomputed"] == 14, "ranking replay drifted")
    require(
        results["f1_historical_paths_valid"] == results["f1_graph_paths"] == 14,
        "historical graph-path validation drifted",
    )
    require(
        results["f1_paths_missing_from_current_graph"] == 1,
        "historical/current graph-path boundary drifted",
    )
    require(results["f2_deleted_source_payload_pairs"] == 1, "deletion boundary drifted")
    require(results["f3_promoted_record_pairs"] == 1, "promotion coverage drifted")
    require(results["f3_promotion_transition_verified"], "promotion did not verify")
    replay = results["f4_stable_engine_reexecution"]
    require(
        replay["returned_exact"]
        == replay["candidate_ledgers_exact"]
        == replay["query_confirmed"]
        == replay["eligible_turns"]
        == 11,
        "eligible-turn engine re-execution is not exact",
    )
    require(replay["excluded_historical_turns"] == 3, "replay exclusion drifted")
    tamper = results["f5_tamper"]
    single_row = [
        "audit_event_deletion",
        "audit_payload_edit",
        "audit_returned_set_edit",
        "retrieval_candidate_score_edit",
        "retrieval_returned_set_edit",
        "retrieval_parameter_edit",
        "retrieval_query_edit",
        "retrieval_subject_edit",
        "record_content_edit",
        "record_status_edit",
        "record_trust_edit",
        "record_source_edit",
        "record_confidence_edit",
        "record_scope_edit",
        "episode_message_edit",
    ]
    for name in single_row:
        entry = tamper[name]
        require(
            entry["detected"] == entry["trials"] == 5,
            f"tamper class {name} is not fully detected",
        )
    require(
        tamper["tail_truncation_chain_only"]["detected"] == 0,
        "chain-only truncation detection drifted (should be undetectable)",
    )
    require(
        tamper["tail_truncation_with_checkpoint"]["detected"]
        == tamper["tail_truncation_with_checkpoint"]["trials"]
        == 5,
        "checkpointed truncation detection drifted",
    )
    require(results["quarantined_results_returned"] == 0, "quarantined content surfaced")
    require(
        results["forgotten_results_returned_after_deletion"] == 0,
        "forgotten content surfaced after deletion",
    )
    require(results["forgotten_content_rows_remaining"] == 0, "forgotten content persisted")
    require(results["reconstruction_ms_total"] > 0, "invalid reconstruction timing")

    manuscript = (
        PAPER / "sections" / "governed-memory" / "07b-recall-forensics.tex"
    ).read_text(encoding="utf-8")
    for fragment in (
        "F1 ranking decisions recomputed & 14/14",
        "F1 returned-result attribution & 68/68",
        "historical graph paths valid & 14/14",
        "F2 provenance commitments complete & 68/68",
        "F3 lifecycle admissible at recall & 68/68",
        "F4 stable returned sets re-executed exactly & 11/11",
        "complete candidate ledgers exact & 11/11",
        "F5 selected single-row mutations detected & 75/75",
        "tail truncation, chain only & 0/5",
        "tail truncation, anchored checkpoint & 5/5",
        f'Auditor reconstruction time & {results["reconstruction_ms_total"] / 1000:.3f}\\,s',
    ):
        require(fragment in manuscript, f"manuscript/forensics mismatch: {fragment}")


def main() -> None:
    validate_benchmark()
    validate_artifact_hashes()
    validate_demo_database()
    validate_standalone_verifiers()
    validate_governed_memory_probe()
    validate_recall_forensics()
    print("OK   paper benchmark tables")
    print("OK   flagship artifact digests and database metrics")
    print("OK   standalone audit and action verifiers")
    print("OK   governed-memory probe and manuscript values")
    print("OK   recall-forensics evidence and manuscript values")


if __name__ == "__main__":
    main()
