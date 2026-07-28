from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from aetnamem.memory import Memory

DEFAULT_MCP_DB = os.environ.get(
    "AETNAMEM_DB", str(Path.home() / ".aetnamem" / "memories.db")
)
DEFAULT_RUNTIME_CONFIG = str(Path.home() / ".aetnamem" / "runtime.json")


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetnamem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser(
        "setup", help="Ten-step wizard for four-memory agent setup"
    )
    setup_parser.add_argument(
        "--preset", choices=("starter", "private", "team", "benchmark"), default="starter"
    )
    setup_parser.add_argument("--db", default=DEFAULT_MCP_DB)
    setup_parser.add_argument("--output", default=DEFAULT_RUNTIME_CONFIG)
    setup_parser.add_argument("--subject", default="you")
    setup_parser.add_argument("--agent", default="openclaw-primary")
    setup_parser.add_argument("--skill-path", action="append", default=[])
    setup_parser.add_argument(
        "--yes", action="store_true", help="Accept defaults without interactive prompts"
    )

    remember_parser = subparsers.add_parser(
        "remember", help="Ingest a message through the write pipeline"
    )
    remember_parser.add_argument("path")
    remember_parser.add_argument("subject_id")
    remember_parser.add_argument("message")
    remember_parser.add_argument("--session", default=None)
    remember_parser.add_argument("--turn", default=None)
    remember_parser.add_argument(
        "--source-type",
        default=None,
        help="Override source classification (user_message, webpage, tool_output)",
    )

    observe_parser = subparsers.add_parser(
        "observe",
        help="Admit one typed, quarantined text observation of host-controlled media",
    )
    observe_parser.add_argument("path")
    observe_parser.add_argument("subject_id")
    observe_parser.add_argument(
        "--envelope",
        required=True,
        help="JSON envelope file, or - to read JSON from stdin",
    )
    observe_parser.add_argument("--session", default=None)
    observe_parser.add_argument("--turn", default=None)

    recall_parser = subparsers.add_parser(
        "recall", help="Top-k recall over active records"
    )
    recall_parser.add_argument("path")
    recall_parser.add_argument("subject_id")
    recall_parser.add_argument("query")
    recall_parser.add_argument("--limit", type=int, default=10)
    recall_parser.add_argument("--min-score", type=float, default=None)
    recall_parser.add_argument("--session", default=None)
    recall_parser.add_argument(
        "--graph", action="store_true", help="Blend bounded graph seed-and-spread recall"
    )

    graph_backfill_parser = subparsers.add_parser(
        "graph-backfill", help="Build the derived graph index from canonical records"
    )
    graph_backfill_parser.add_argument("path")
    graph_backfill_parser.add_argument("subject_id")
    graph_backfill_parser.add_argument(
        "--rebuild", action="store_true", help="Drop and deterministically rebuild graph rows"
    )

    graph_inspect_parser = subparsers.add_parser(
        "graph-inspect", help="Inspect derived entities, aliases, edges, and counts"
    )
    graph_inspect_parser.add_argument("path")
    graph_inspect_parser.add_argument("subject_id")

    graph_consolidate_parser = subparsers.add_parser(
        "graph-consolidate",
        help="Backfill graph state, propose entity merges, and optionally archive history",
    )
    graph_consolidate_parser.add_argument("path")
    graph_consolidate_parser.add_argument("subject_id")
    graph_consolidate_parser.add_argument("--archive-root", default=None)
    graph_consolidate_parser.add_argument("--archive-before", default=None)
    graph_consolidate_parser.add_argument("--no-prune", action="store_true")

    graph_merges_parser = subparsers.add_parser(
        "graph-merges", help="List reviewer-gated entity merge proposals"
    )
    graph_merges_parser.add_argument("path")
    graph_merges_parser.add_argument("subject_id")
    graph_merges_parser.add_argument("--status", default=None)

    graph_merge_parser = subparsers.add_parser(
        "graph-merge", help="Approve, reject, or revert an entity merge proposal"
    )
    graph_merge_parser.add_argument("path")
    graph_merge_parser.add_argument("subject_id")
    graph_merge_parser.add_argument("proposal_id")
    graph_merge_parser.add_argument("decision", choices=("approve", "reject", "revert"))
    graph_merge_parser.add_argument("--winner", default=None)
    graph_merge_parser.add_argument("--actor", default="reviewer")

    graph_history_parser = subparsers.add_parser(
        "graph-history", help="Read verified inactive-edge archive partitions"
    )
    graph_history_parser.add_argument("path")
    graph_history_parser.add_argument("subject_id")
    graph_history_parser.add_argument("--year", type=int, default=None)

    optimize_parser = subparsers.add_parser(
        "optimize", help="Run SQLite PRAGMA optimize maintenance"
    )
    optimize_parser.add_argument("path")

    index_parser = subparsers.add_parser(
        "index", help="Build and verify the optional semantic search index"
    )
    index_commands = index_parser.add_subparsers(
        dest="index_command", required=True
    )
    index_build = index_commands.add_parser(
        "build", help="Build and activate a verified versioned index epoch"
    )
    index_build.add_argument("path")
    index_build.add_argument("--subject", required=True)
    index_build.add_argument(
        "--embedder",
        choices=("ollama", "openai-compatible", "sentence-transformers", "hashing"),
        default="ollama",
    )
    index_build.add_argument("--model", default=None)
    index_build.add_argument("--model-version", default="unverified")
    index_build.add_argument("--endpoint", default=None)
    index_build.add_argument("--api-key-env", default=None)
    index_build.add_argument("--index-path", default=None)
    index_build.add_argument("--batch-size", type=int, default=64)

    index_status = index_commands.add_parser(
        "status", help="Show active and retired semantic index epochs"
    )
    index_status.add_argument("path")
    index_status.add_argument("--subject", default=None)
    index_status.add_argument("--index-path", default=None)

    index_verify = index_commands.add_parser(
        "verify", help="Fail if vectors are stale, orphaned, unsafe, or incomplete"
    )
    index_verify.add_argument("path")
    index_verify.add_argument("--subject", required=True)
    index_verify.add_argument("--index-path", default=None)

    list_parser = subparsers.add_parser("list", help="List a subject's records")
    list_parser.add_argument("path")
    list_parser.add_argument("subject_id")
    list_parser.add_argument(
        "--all", action="store_true", help="Include superseded/quarantined/tombstoned"
    )

    memories_parser = subparsers.add_parser(
        "memories", help="Browse and search a user's memories without recording a recall"
    )
    memories_parser.add_argument("path")
    memories_parser.add_argument("--subject", required=True)
    memories_parser.add_argument("--query", default="")
    memories_parser.add_argument(
        "--status",
        action="append",
        choices=("active", "quarantined", "superseded", "tombstoned"),
        default=[],
        help="Filter by status; repeat to select more than one",
    )
    memories_parser.add_argument(
        "--all", action="store_true", help="Include every memory status"
    )
    memories_parser.add_argument("--since", default=None, help="ISO date or timestamp")
    memories_parser.add_argument("--until", default=None, help="ISO date or timestamp")
    memories_parser.add_argument("--limit", type=int, default=100)
    _add_semantic_search_arguments(memories_parser)
    _add_access_audit_arguments(memories_parser)
    _add_report_arguments(memories_parser)

    search_parser = subparsers.add_parser(
        "search", help="Search across memories and audit evidence without agent recall"
    )
    search_parser.add_argument("path")
    search_parser.add_argument("query", nargs="?", default="")
    search_parser.add_argument("--subject", required=True)
    search_parser.add_argument(
        "--scope",
        choices=(
            "all",
            "memories",
            "media",
            "episodes",
            "retrievals",
            "events",
            "runs",
            "actions",
        ),
        default="all",
    )
    search_parser.add_argument(
        "--status",
        action="append",
        choices=("active", "quarantined", "superseded", "tombstoned"),
        default=[],
    )
    search_parser.add_argument("--session", default=None)
    search_parser.add_argument(
        "--event-type", default=None, help="Exact type or wildcard such as memory.*"
    )
    search_parser.add_argument("--actor", default=None)
    search_parser.add_argument(
        "--plane", choices=("working", "semantic", "episodic", "procedural"), default=None
    )
    search_parser.add_argument(
        "--outcome", default=None, help="success, failed, or a stored state/status"
    )
    search_parser.add_argument("--since", default=None, help="ISO date or timestamp")
    search_parser.add_argument("--until", default=None, help="ISO date or timestamp")
    search_parser.add_argument("--limit", type=int, default=100)
    _add_semantic_search_arguments(search_parser)
    _add_access_audit_arguments(search_parser)
    _add_report_arguments(search_parser)

    trace_parser = subparsers.add_parser(
        "trace", help="Find a clue and reconstruct its chronological evidence trail"
    )
    trace_parser.add_argument("path")
    trace_parser.add_argument("query", nargs="?", default="")
    trace_parser.add_argument("--subject", required=True)
    trace_parser.add_argument("--session", default=None)
    trace_parser.add_argument("--run", default=None)
    trace_parser.add_argument("--record", default=None)
    trace_parser.add_argument(
        "--event-type", default=None, help="Exact type or wildcard such as memory.*"
    )
    trace_parser.add_argument("--since", default=None, help="ISO date or timestamp")
    trace_parser.add_argument("--until", default=None, help="ISO date or timestamp")
    trace_parser.add_argument("--limit", type=int, default=500)
    _add_semantic_search_arguments(trace_parser)
    _add_access_audit_arguments(trace_parser)
    _add_report_arguments(trace_parser)

    access_log_parser = subparsers.add_parser(
        "access-log", help="List and verify the separate investigator access chain"
    )
    access_log_parser.add_argument("path")
    access_log_parser.add_argument("--subject", required=True)

    forget_parser = subparsers.add_parser(
        "forget", help="Tombstone + purge matching records; prints a deletion receipt"
    )
    forget_parser.add_argument("path")
    forget_parser.add_argument("subject_id")
    forget_group = forget_parser.add_mutually_exclusive_group(required=True)
    forget_group.add_argument("--contains", default=None)
    forget_group.add_argument(
        "--utterance", default=None, help='e.g. "Forget my backup email."'
    )
    forget_parser.add_argument("--session", default=None)

    forget_artifact_parser = subparsers.add_parser(
        "forget-artifact",
        help="Purge all AetnaMem derivatives of one exact media-byte SHA-256",
    )
    forget_artifact_parser.add_argument("path")
    forget_artifact_parser.add_argument("subject_id")
    forget_artifact_parser.add_argument("media_sha256")
    forget_artifact_parser.add_argument("--artifact-id", default=None)
    forget_artifact_parser.add_argument("--session", default=None)
    forget_artifact_parser.add_argument("--turn", default=None)

    promote_parser = subparsers.add_parser(
        "promote", help="Activate a quarantined record and audit the trust transition"
    )
    promote_parser.add_argument("path")
    promote_parser.add_argument("subject_id")
    promote_parser.add_argument("record_id")
    promote_parser.add_argument("--session", default=None)

    log_action_parser = subparsers.add_parser(
        "log-action", help="Append an agent action event to the audit chain"
    )
    log_action_parser.add_argument("path")
    log_action_parser.add_argument("subject_id")
    log_action_parser.add_argument("action_type")
    log_action_parser.add_argument(
        "--payload", default="{}", help="JSON object (store digests, not raw content)"
    )
    log_action_parser.add_argument("--session", default=None)
    log_action_parser.add_argument("--turn", default=None)

    consolidate_parser = subparsers.add_parser(
        "consolidate",
        help="Deterministic cleanup: collapse duplicate actives, repair fact-key conflicts",
    )
    consolidate_parser.add_argument("path")
    consolidate_parser.add_argument("subject_id")

    persona_parser = subparsers.add_parser(
        "persona", help="Deterministic L3 persona snapshot derived from active records"
    )
    persona_parser.add_argument("path")
    persona_parser.add_argument("subject_id")
    persona_parser.add_argument("--max-chars", type=int, default=1500)

    context_parser = subparsers.add_parser(
        "context-pack", help="Build host-neutral stable and dynamic prompt context"
    )
    context_parser.add_argument("path")
    context_parser.add_argument("subject_id")
    context_parser.add_argument("query")
    context_parser.add_argument("--session", default=None)
    context_parser.add_argument("--persona-max-chars", type=int, default=600)
    context_parser.add_argument("--recall-max-records", type=int, default=3)
    context_parser.add_argument("--recall-max-chars", type=int, default=1200)
    context_parser.add_argument("--min-score", type=float, default=0.3)
    context_parser.add_argument("--graph", action="store_true")
    context_parser.add_argument(
        "--reference-mode", choices=("full", "compact", "none"), default="compact"
    )

    scenes_parser = subparsers.add_parser(
        "scenes", help="Deterministic L2 scene view: sessions with their episodes/records"
    )
    scenes_parser.add_argument("path")
    scenes_parser.add_argument("subject_id")

    propose_parser = subparsers.add_parser(
        "propose",
        help="Submit derived fact proposals (JSON array on stdin); they land quarantined with evidence",
    )
    propose_parser.add_argument("path")
    propose_parser.add_argument("subject_id")
    propose_parser.add_argument("--proposer", default="llm")

    inspect_parser = subparsers.add_parser(
        "inspect", help="Dump a subject's records, episodes, and audit trail"
    )
    inspect_parser.add_argument("path")
    inspect_parser.add_argument("subject_id")

    audit_parser = subparsers.add_parser(
        "audit", help="Dump a subject's audit log and verify the hash chain"
    )
    audit_parser.add_argument("path")
    audit_parser.add_argument("subject_id")

    checkpoint_parser = subparsers.add_parser(
        "checkpoint",
        help="Snapshot all audit-chain heads; anchor the output externally",
    )
    checkpoint_parser.add_argument("path")
    checkpoint_parser.add_argument(
        "sink", nargs="?", help="JSONL file to append the checkpoint to"
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify audit-chain integrity, optionally against checkpoints",
    )
    verify_parser.add_argument("path")
    verify_parser.add_argument("--subject", default=None)
    verify_parser.add_argument(
        "--checkpoints", default=None, help="JSONL checkpoint file to check against"
    )
    verify_parser.add_argument(
        "--incremental",
        action="store_true",
        help="verify only the suffix after a locally cached, hash-checked head",
    )

    mcp_parser = subparsers.add_parser(
        "mcp", help="Serve the verbs as MCP tools over stdio"
    )
    mcp_parser.add_argument(
        "--db",
        default=DEFAULT_MCP_DB,
        help=f"SQLite path (default: $AETNAMEM_DB or {DEFAULT_MCP_DB})",
    )
    mcp_parser.add_argument(
        "--subject",
        default="default",
        help="Subject used when a tool call omits subject_id",
    )
    mcp_parser.add_argument(
        "--checkpoints",
        default=None,
        help="Default checkpoint JSONL for the memory_verify tool",
    )
    mcp_parser.add_argument("--retain-query-text", action="store_true")

    runtime_parser = subparsers.add_parser(
        "runtime", help="Coordinate working, semantic, episodic, and procedural memory"
    )
    runtime_commands = runtime_parser.add_subparsers(
        dest="runtime_command", required=True
    )
    runtime_commands.add_parser("presets", help="List ready-made configurations")

    runtime_init = runtime_commands.add_parser(
        "init", help="Write a ready-made runtime configuration"
    )
    runtime_init.add_argument(
        "--preset", choices=("starter", "private", "team", "benchmark"), default="starter"
    )
    runtime_init.add_argument("--db", default=DEFAULT_MCP_DB)
    runtime_init.add_argument("--output", default=DEFAULT_RUNTIME_CONFIG)
    runtime_init.add_argument("--subject", default="you")
    runtime_init.add_argument("--agent", default="default-agent")
    runtime_init.add_argument("--skill-path", action="append", default=[])

    for name, help_text in (
        ("validate", "Validate a runtime configuration"),
        ("status", "Show runtime health and stored learning counts"),
        ("mcp", "Serve legacy and four-memory runtime tools over stdio"),
    ):
        command_parser = runtime_commands.add_parser(name, help=help_text)
        command_parser.add_argument("--config", default=DEFAULT_RUNTIME_CONFIG)
        if name == "mcp":
            command_parser.add_argument(
                "--impact-restricted",
                action="store_true",
                help="Expose no memory or outcome tools to the experimental agent",
            )

    runtime_prepare = runtime_commands.add_parser(
        "prepare", help="Compile four memory planes for one agent turn"
    )
    runtime_prepare.add_argument("query")
    runtime_prepare.add_argument("--config", default=DEFAULT_RUNTIME_CONFIG)
    runtime_prepare.add_argument(
        "--task-state", default="{}", help="JSON object with goal, constraints, and progress"
    )
    runtime_prepare.add_argument("--session", default=None)
    runtime_prepare.add_argument("--task", default=None)
    runtime_prepare.add_argument("--turn", default=None)

    runtime_outcome = runtime_commands.add_parser(
        "outcome", help="Record a caller-asserted outcome for a prepared turn"
    )
    runtime_outcome.add_argument("run_id")
    runtime_outcome.add_argument("--config", default=DEFAULT_RUNTIME_CONFIG)
    outcome_result = runtime_outcome.add_mutually_exclusive_group(required=True)
    outcome_result.add_argument("--success", action="store_true")
    outcome_result.add_argument("--failure", action="store_true")
    runtime_outcome.add_argument("--summary", default="")
    runtime_outcome.add_argument("--result-digest", default=None)
    runtime_outcome.add_argument("--feedback", default=None)
    runtime_outcome.add_argument("--idempotency-key", default=None)
    runtime_outcome.add_argument("--manifest-sha256", default=None)
    runtime_outcome.add_argument(
        "--metrics",
        default="{}",
        help="JSON object with verifier, token, cost, latency, and safety metrics",
    )

    runtime_promote = runtime_commands.add_parser(
        "promote-lesson", help="Activate a reviewed episodic lesson proposal"
    )
    runtime_promote.add_argument("lesson_id")
    runtime_promote.add_argument("--config", default=DEFAULT_RUNTIME_CONFIG)

    runtime_forget = runtime_commands.add_parser(
        "forget", help="Purge matching content across all four memory planes"
    )
    runtime_forget.add_argument("--config", default=DEFAULT_RUNTIME_CONFIG)
    runtime_forget_selector = runtime_forget.add_mutually_exclusive_group(required=True)
    runtime_forget_selector.add_argument("--contains", default=None)
    runtime_forget_selector.add_argument("--utterance", default=None)

    impact_parser = subparsers.add_parser(
        "impact", help="Run registered Memory Impact experiments"
    )
    impact_commands = impact_parser.add_subparsers(
        dest="impact_command", required=True
    )
    impact_init = impact_commands.add_parser(
        "init", help="Create a reproducible 16-arm Memory Impact Lab"
    )
    impact_init.add_argument("path", nargs="?", default="bench/causal_memory")

    impact_run = impact_commands.add_parser(
        "run", help="Run a gated synthetic, Grok training, or held-out stage"
    )
    impact_run.add_argument("--protocol", required=True)
    impact_run.add_argument(
        "--stage",
        choices=("synthetic", "grok-smoke", "grok-train", "grok-held-out"),
        default="synthetic",
    )
    impact_run.add_argument("--simulations", type=int, default=500)
    impact_run.add_argument("--blocks", type=int, default=80)
    impact_run.add_argument(
        "--max-new-runs",
        type=int,
        default=None,
        help="Stop after this many newly completed model runs",
    )
    impact_run.add_argument("--signing-key", default=None)
    impact_run.add_argument(
        "--confirm-paid-run",
        action="store_true",
        help="Required for stages that invoke the configured model",
    )

    impact_verify = impact_commands.add_parser(
        "verify", help="Verify assignments, artifacts, and signed host outcomes"
    )
    impact_verify.add_argument("results")
    impact_verify.add_argument("--public-key", required=True)
    impact_verify.add_argument(
        "--seed-file",
        default=None,
        help="After experiment close, verify every HMAC assignment token",
    )

    impact_report = impact_commands.add_parser(
        "report", help="Build a human-readable Memory Impact HTML report"
    )
    impact_report.add_argument("results")
    impact_report.add_argument("--public-key", required=True)
    impact_report.add_argument("--output", required=True)

    trial_parser = subparsers.add_parser(
        "trial", help="Try AetnaMem beside OpenClaw or Hermes before switching"
    )
    trial_commands = trial_parser.add_subparsers(
        dest="trial_command", required=True
    )
    trial_start = trial_commands.add_parser(
        "start", help="Start candidate-only capture; agent behavior is unchanged"
    )
    trial_start.add_argument(
        "--host",
        choices=("auto", "openclaw", "hermes"),
        default="auto",
        help="auto detects exactly one installed supported agent",
    )
    trial_start.add_argument(
        "--state",
        default=None,
        help="Advanced: override the local trial control-file path",
    )
    trial_start.add_argument(
        "--trial-root",
        default=None,
        help="Advanced: override the private trial evidence directory",
    )
    trial_start.add_argument(
        "--no-configure",
        action="store_true",
        help="Testing only: create trial state without installing the host hook",
    )

    for name, help_text in (
        ("status", "Show mode, safety boundary, evidence, and readiness"),
        ("candidates", "List candidate memories awaiting your review"),
        ("preview", "Build previews beside the agent without changing its context"),
        ("activate", "Switch all eligible turns after the canary gate passes"),
        ("rollback", "Turn injection and capture off; preserve evidence for review"),
        ("off", "Emergency stop: fail closed without deleting trial evidence"),
        ("mcp", "Serve the private host-integration protocol over stdio"),
        ("dashboard", "Open the local Safe Switch review dashboard"),
    ):
        command_parser = trial_commands.add_parser(name, help=help_text)
        command_parser.add_argument("--state", default=None)
        if name == "preview":
            command_parser.add_argument(
                "--query",
                default=None,
                help="Optional local test query; live hosts preview automatically",
            )
        if name == "dashboard":
            command_parser.add_argument("--port", type=int, default=8766)
            command_parser.add_argument("--no-open", action="store_true")
        if name in {"activate", "rollback"}:
            command_parser.add_argument(
                "--yes", action="store_true", help="Confirm non-interactively"
            )

    trial_canary = trial_commands.add_parser(
        "canary", help="Allow a limited number of approved-memory context exposures"
    )
    trial_canary.add_argument("--turns", type=int, required=True)
    trial_canary.add_argument("--state", default=None)
    trial_canary.add_argument(
        "--yes", action="store_true", help="Confirm non-interactively"
    )

    for name, approve, help_text in (
        ("approve", True, "Approve candidate memories for preview and canary"),
        ("reject", False, "Reject candidate memories so they cannot be used"),
    ):
        command_parser = trial_commands.add_parser(name, help=help_text)
        command_parser.add_argument("candidate_ids", nargs="+")
        command_parser.add_argument("--state", default=None)
        command_parser.set_defaults(trial_approve=approve)

    trial_capture = trial_commands.add_parser(
        "capture-test", help="Test candidate extraction without running an agent"
    )
    trial_capture.add_argument("message")
    trial_capture.add_argument("--session", default=None)
    trial_capture.add_argument("--state", default=None)

    actions_parser = subparsers.add_parser(
        "actions", help="Stage, approve, execute, and verify guarded actions"
    )
    action_commands = actions_parser.add_subparsers(
        dest="action_command", required=True
    )

    stage_parser = action_commands.add_parser(
        "stage", help="Create a canonical hash-bound one-operation WorldPatch"
    )
    stage_parser.add_argument("path", help="aetnamem SQLite database")
    stage_parser.add_argument("subject_id")
    stage_parser.add_argument("adapter", choices=["filesystem"])
    stage_parser.add_argument("operation", choices=["write_text", "delete_file"])
    stage_parser.add_argument("--args", required=True, help="Operation arguments JSON")
    stage_parser.add_argument("--root", required=True, help="Filesystem adapter root")
    stage_parser.add_argument("--actor", required=True)
    stage_parser.add_argument(
        "--mode", choices=["observe", "preview", "enforce"], default="enforce"
    )
    stage_parser.add_argument("--authority-id", default=None)
    stage_parser.add_argument(
        "--authority-digest",
        default=None,
        help="Digest of the host-attested user task; raw task text is not stored",
    )
    stage_parser.add_argument(
        "--evidence",
        default="[]",
        help="Additional EvidenceRef objects as a JSON array",
    )
    stage_parser.add_argument("--session", default=None)
    stage_parser.add_argument("--turn", default=None)

    show_parser = action_commands.add_parser("show", help="Show a redacted action plan")
    show_parser.add_argument("path")
    show_parser.add_argument("transaction_id")

    action_list_parser = action_commands.add_parser("list", help="List action plans")
    action_list_parser.add_argument("path")
    action_list_parser.add_argument("--subject", default=None)

    approve_parser = action_commands.add_parser(
        "approve", help="Sign and record approval for the exact current plan"
    )
    approve_parser.add_argument("path")
    approve_parser.add_argument("transaction_id")
    approve_parser.add_argument(
        "--approver-label",
        "--approver",
        dest="approver_label",
        required=True,
        help="Attribution label; shared-key possession is the authenticated fact",
    )
    approve_parser.add_argument("--ttl", type=int, default=900)
    approve_parser.add_argument("--approval-key-file", default=None)

    commit_parser = action_commands.add_parser(
        "commit", help="Revalidate and execute an approved plan"
    )
    commit_parser.add_argument("path")
    commit_parser.add_argument("transaction_id")
    commit_parser.add_argument("--root", required=True)
    commit_parser.add_argument("--approval-key-file", default=None)

    abort_parser = action_commands.add_parser("abort", help="Abort a pre-commit plan")
    abort_parser.add_argument("path")
    abort_parser.add_argument("transaction_id")
    abort_parser.add_argument("--actor", default="user")

    recover_parser = action_commands.add_parser(
        "recover", help="Fence an interrupted external call for operator recovery"
    )
    recover_parser.add_argument("path")
    recover_parser.add_argument("transaction_id")
    recover_parser.add_argument("--actor", default="operator")

    action_verify_parser = action_commands.add_parser(
        "verify", help="Verify an action receipt and its audit-chain binding"
    )
    action_verify_parser.add_argument("path")
    action_verify_parser.add_argument("transaction_id")
    action_verify_parser.add_argument("--approval-key-file", default=None)

    purge_parser = action_commands.add_parser(
        "purge-payloads", help="Erase raw action arguments, snapshots, and results"
    )
    purge_parser.add_argument("path")
    purge_parser.add_argument("transaction_id")
    purge_parser.add_argument("--actor", default="user")

    import_journal_parser = action_commands.add_parser(
        "import-journal",
        help="Import a compatible journal as digest-only, unverified audit evidence",
    )
    import_journal_parser.add_argument("path", help="aetnamem SQLite database")
    import_journal_parser.add_argument("subject_id")
    import_journal_parser.add_argument("source_journal")
    import_journal_parser.add_argument("--source-id", required=True)
    import_journal_parser.add_argument("--actor", default="journal-importer")

    args = parser.parse_args()

    if args.command == "setup":
        from aetnamem.runtime.wizard import run_setup_wizard

        run_setup_wizard(
            preset=args.preset,
            db_path=args.db,
            output_path=args.output,
            subject_id=args.subject,
            agent_id=args.agent,
            skill_paths=args.skill_path,
            non_interactive=args.yes,
        )
        return

    if args.command == "runtime":
        _run_runtime(args)
        return

    if args.command == "impact":
        _run_impact(args)
        return

    if args.command == "trial":
        _run_trial(args)
        return

    if args.command == "index":
        _run_index(args)
        return

    if args.command == "actions":
        _run_actions(args)
        return

    if args.command == "mcp":
        from aetnamem.mcp import MCPServer

        memory = Memory(args.db, retain_query_text=args.retain_query_text)
        MCPServer(
            memory,
            default_subject=args.subject,
            checkpoints_path=args.checkpoints,
        ).serve()
        return

    memory = Memory(args.path)

    if args.command == "remember":
        result = memory.remember(
            args.subject_id,
            args.message,
            session_id=args.session,
            turn_id=args.turn,
            source_type=args.source_type,
        )
        _print(result)
    elif args.command == "observe":
        envelope_text = (
            sys.stdin.read()
            if args.envelope == "-"
            else Path(args.envelope).read_text(encoding="utf-8")
        )
        envelope = json.loads(envelope_text)
        if not isinstance(envelope, dict):
            raise ValueError("media observation envelope must be a JSON object")
        _print(
            memory.remember_observation(
                args.subject_id,
                envelope,
                session_id=args.session,
                turn_id=args.turn,
                actor="cli-caller",
                forced_assurance="caller_asserted",
            )
        )
    elif args.command == "recall":
        _print(
            memory.recall(
                args.subject_id,
                args.query,
                session_id=args.session,
                limit=args.limit,
                min_score=args.min_score,
                use_graph=args.graph,
            )
        )
    elif args.command == "graph-backfill":
        _print(memory.backfill_graph(args.subject_id, rebuild=args.rebuild))
    elif args.command == "graph-inspect":
        _print(memory.inspect_graph(args.subject_id))
    elif args.command == "graph-consolidate":
        _print(
            memory.consolidate_graph(
                args.subject_id,
                archive_root=args.archive_root,
                archive_before=args.archive_before,
                prune_archive=not args.no_prune,
            )
        )
    elif args.command == "graph-merges":
        _print(memory.list_graph_merge_proposals(args.subject_id, status=args.status))
    elif args.command == "graph-merge":
        if args.decision == "revert":
            _print(
                memory.revert_graph_merge(
                    args.subject_id, args.proposal_id, actor=args.actor
                )
            )
        else:
            _print(
                memory.decide_graph_merge(
                    args.subject_id,
                    args.proposal_id,
                    approve=args.decision == "approve",
                    actor=args.actor,
                    winner_entity=args.winner,
                )
            )
    elif args.command == "graph-history":
        _print(memory.read_graph_archive(args.subject_id, partition_year=args.year))
    elif args.command == "optimize":
        memory.optimize()
        _print({"optimized": True})
    elif args.command == "list":
        _print(memory.list(args.subject_id, include_inactive=args.all))
    elif args.command == "memories":
        from aetnamem.investigate import format_memories, search_evidence

        semantic_index, embedder = _semantic_search_resources(args, memory)
        try:
            statuses = args.status or (
                ("active", "quarantined", "superseded", "tombstoned")
                if args.all
                else ("active",)
            )
            report = search_evidence(
                memory,
                args.subject,
                args.query,
                scope="memories",
                statuses=statuses,
                since=args.since,
                until=args.until,
                limit=args.limit,
                mode=args.mode,
                semantic_index=semantic_index,
                embedder=embedder,
                min_similarity=args.min_similarity,
                audit_access=args.audit_access,
                access_actor=args.access_actor,
                access_operation="memories",
            )
            _emit_report(report, format_memories(report), args)
        finally:
            if semantic_index is not None:
                semantic_index.close()
    elif args.command == "search":
        from aetnamem.investigate import format_search, search_evidence

        semantic_index, embedder = _semantic_search_resources(args, memory)
        try:
            report = search_evidence(
                memory,
                args.subject,
                args.query,
                scope=args.scope,
                statuses=args.status,
                session_id=args.session,
                event_type=args.event_type,
                actor=args.actor,
                plane=args.plane,
                outcome=args.outcome,
                since=args.since,
                until=args.until,
                limit=args.limit,
                mode=args.mode,
                semantic_index=semantic_index,
                embedder=embedder,
                min_similarity=args.min_similarity,
                audit_access=args.audit_access,
                access_actor=args.access_actor,
            )
            _emit_report(report, format_search(report), args)
        finally:
            if semantic_index is not None:
                semantic_index.close()
    elif args.command == "trace":
        from aetnamem.investigate import format_trace, trace_evidence

        semantic_index, embedder = _semantic_search_resources(args, memory)
        try:
            report = trace_evidence(
                memory,
                args.subject,
                args.query,
                session_id=args.session,
                run_id=args.run,
                record_id=args.record,
                event_type=args.event_type,
                since=args.since,
                until=args.until,
                limit=args.limit,
                mode=args.mode,
                semantic_index=semantic_index,
                embedder=embedder,
                min_similarity=args.min_similarity,
                audit_access=args.audit_access,
                access_actor=args.access_actor,
            )
            _emit_report(report, format_trace(report), args)
        finally:
            if semantic_index is not None:
                semantic_index.close()
    elif args.command == "access-log":
        _print(
            {
                "format": "aetnamem-investigation-access-v1",
                "subject_id": args.subject,
                "verification": memory.store.verify_investigation_access(
                    args.subject
                ),
                "events": memory.store.list_investigation_access(args.subject),
            }
        )
    elif args.command == "forget":
        result = memory.forget(
            args.subject_id,
            selector=args.contains,
            utterance=args.utterance,
            session_id=args.session,
        )
        _print(result)
    elif args.command == "forget-artifact":
        _print(
            memory.forget_artifact(
                args.subject_id,
                args.media_sha256,
                artifact_id=args.artifact_id,
                session_id=args.session,
                turn_id=args.turn,
            )
        )
    elif args.command == "promote":
        _print(
            memory.promote(args.subject_id, args.record_id, session_id=args.session)
        )
    elif args.command == "log-action":
        event_id = memory.log_action(
            args.subject_id,
            args.action_type,
            json.loads(args.payload),
            session_id=args.session,
            turn_id=args.turn,
        )
        _print({"event_id": event_id})
    elif args.command == "consolidate":
        _print(memory.consolidate(args.subject_id))
    elif args.command == "persona":
        _print(memory.build_persona(args.subject_id, max_chars=args.max_chars))
    elif args.command == "context-pack":
        _print(
            memory.build_context_pack(
                args.subject_id,
                args.query,
                session_id=args.session,
                persona_max_chars=args.persona_max_chars,
                recall_max_records=args.recall_max_records,
                recall_max_chars=args.recall_max_chars,
                min_score=args.min_score,
                use_graph=args.graph,
                reference_mode=args.reference_mode,
            )
        )
    elif args.command == "scenes":
        _print(memory.scenes(args.subject_id))
    elif args.command == "propose":
        proposals = json.load(sys.stdin)
        _print(
            memory.propose_facts(
                args.subject_id, proposals, proposer=args.proposer
            )
        )
    elif args.command == "inspect":
        _print(memory.inspect(args.subject_id))
    elif args.command == "audit":
        _print(memory.audit(args.subject_id))
    elif args.command == "checkpoint":
        _print(memory.checkpoint(sink_path=args.sink))
    elif args.command == "verify":
        result = memory.verify(
            args.subject,
            checkpoints_path=args.checkpoints,
            incremental=args.incremental,
        )
        _print(result)
        if not result["valid"]:
            sys.exit(1)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _add_report_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        dest="report_format",
        choices=("text", "json"),
        default=None,
        help="Output format (default: text, or inferred from --output extension)",
    )
    parser.add_argument(
        "--output", default=None, help="Write the complete report to this file"
    )


def _add_semantic_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=("lexical", "semantic", "hybrid"),
        default="lexical",
        help="Retrieval mode; semantic/hybrid require a built index",
    )
    parser.add_argument(
        "--embedder",
        choices=("ollama", "openai-compatible", "sentence-transformers", "hashing"),
        default=None,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--index-path", default=None)
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.2,
        help="Minimum cosine similarity for semantic nominations",
    )


def _add_access_audit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--audit-access",
        action="store_true",
        help="Append a digest-only event to the separate investigation access chain",
    )
    parser.add_argument(
        "--access-actor",
        default="unauthenticated-cli",
        help="Actor asserted by the caller; authenticated hosts should supply identity",
    )


def _semantic_search_resources(
    args: argparse.Namespace, memory: Memory
) -> tuple[object | None, object | None]:
    if args.mode == "lexical":
        return None, None
    from aetnamem.semantic import SemanticIndex, create_embedder, default_index_path

    index_path = Path(
        args.index_path or default_index_path(memory.store.path)
    ).expanduser()
    if not index_path.exists():
        raise ValueError(
            f"semantic index does not exist: {index_path}; "
            "run `aetnamem index build` first"
        )
    index = SemanticIndex(index_path)
    epoch = index.active_epoch(args.subject)
    if epoch is None:
        index.close()
        raise ValueError(
            f"no semantic index for {args.subject!r}; run `aetnamem index build` first"
        )
    identity = epoch["identity"]
    provider = args.embedder or str(identity["provider"])
    if provider == "hashing-diagnostic":
        provider = "hashing"
    model = args.model or str(identity["model"])
    if provider == "hashing":
        model = str(epoch["dimensions"])
    embedder = create_embedder(
        provider,
        model,
        endpoint=args.endpoint or identity.get("endpoint"),
        api_key_env=args.api_key_env,
        model_version=args.model_version or str(identity.get("version", "unverified")),
    )
    return index, embedder


def _run_index(args: argparse.Namespace) -> None:
    from aetnamem.semantic import SemanticIndex, create_embedder, default_index_path

    memory = Memory(args.path)
    index = SemanticIndex(args.index_path or default_index_path(args.path))
    try:
        if args.index_command == "status":
            _print(index.status(args.subject))
            return
        if args.index_command == "verify":
            report = index.verify(memory, args.subject)
            _print(report)
            if not report["valid"]:
                raise SystemExit(1)
            return
        if args.index_command == "build":
            model = args.model
            if args.embedder == "ollama" and not model:
                model = "nomic-embed-text"
            embedder = create_embedder(
                args.embedder,
                model,
                endpoint=args.endpoint,
                api_key_env=args.api_key_env,
                model_version=args.model_version,
            )
            report = index.build(
                memory,
                args.subject,
                embedder,
                batch_size=args.batch_size,
            )
            _print(report)
            return
        raise ValueError(f"unknown index command: {args.index_command}")
    finally:
        index.close()
        memory.close()


def _emit_report(value: object, text: str, args: argparse.Namespace) -> None:
    output_path = Path(args.output).expanduser() if args.output else None
    report_format = args.report_format
    if report_format is None:
        report_format = "json" if output_path and output_path.suffix.lower() == ".json" else "text"
    rendered = (
        json.dumps(value, indent=2, sort_keys=True) + "\n"
        if report_format == "json"
        else text
    )
    if output_path is None:
        sys.stdout.write(rendered)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def _run_runtime(args: argparse.Namespace) -> None:
    from aetnamem.runtime import (
        MemoryRuntime,
        list_presets,
        load_config,
        preset_config,
    )

    if args.runtime_command == "presets":
        _print(list_presets())
        return
    if args.runtime_command == "init":
        config = preset_config(
            args.preset,
            db_path=str(Path(args.db).expanduser()),
            subject_id=args.subject,
            agent_id=args.agent,
            skill_paths=args.skill_path,
        )
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _print({"created": str(output), "preset": args.preset, "config": config})
        return
    if args.runtime_command == "validate":
        config = load_config(args.config)
        _print(
            {
                "valid": True,
                "format": config["format"],
                "preset": config.get("preset", "custom"),
                "planes": sorted(config["planes"]),
            }
        )
        return

    runtime = MemoryRuntime(args.config)
    try:
        if args.runtime_command == "status":
            _print(runtime.status())
            return
        if args.runtime_command == "prepare":
            task_state = json.loads(args.task_state)
            if not isinstance(task_state, dict):
                raise ValueError("--task-state must be a JSON object")
            scope = runtime.default_scope.to_dict()
            scope.update(
                {
                    key: value
                    for key, value in {
                        "session_id": args.session,
                        "task_id": args.task,
                        "turn_id": args.turn,
                    }.items()
                    if value is not None
                }
            )
            _print(runtime.prepare_turn(args.query, task_state=task_state, scope=scope))
            return
        if args.runtime_command == "outcome":
            metrics = json.loads(args.metrics)
            if not isinstance(metrics, dict):
                raise ValueError("--metrics must be a JSON object")
            _print(
                runtime.record_outcome(
                    args.run_id,
                    success=bool(args.success),
                    summary=args.summary,
                    result_digest=args.result_digest,
                    feedback=args.feedback,
                    idempotency_key=args.idempotency_key,
                    manifest_sha256=args.manifest_sha256,
                    metrics=metrics,
                )
            )
            return
        if args.runtime_command == "promote-lesson":
            _print(runtime.promote_lesson(args.lesson_id))
            return
        if args.runtime_command == "forget":
            _print(runtime.forget(contains=args.contains, utterance=args.utterance))
            return
        if args.runtime_command == "mcp":
            from aetnamem.mcp import MCPServer

            MCPServer(
                runtime.memory,
                default_subject=runtime.default_scope.subject_id,
                runtime=runtime,
                tool_profile=(
                    "impact-restricted"
                    if args.impact_restricted
                    else "full"
                ),
            ).serve()
            return
        raise ValueError(f"unknown runtime command: {args.runtime_command}")
    finally:
        runtime.close()


def _run_impact(args: argparse.Namespace) -> None:
    from aetnamem.impact.allocation import BalancedFactorialAllocator
    from aetnamem.impact.controller import ImpactController, run_paid_smoke_check
    from aetnamem.impact.lab import init_lab, load_signer
    from aetnamem.impact.metrology import inspect_cli, write_metrology
    from aetnamem.impact.policy import (
        evaluate_held_out,
        freeze_policy,
        write_policy,
    )
    from aetnamem.impact.protocol import load_protocol
    from aetnamem.impact.report import write_report
    from aetnamem.impact.synthetic import run_calibration, write_calibration
    from aetnamem.impact.tasks import load_task
    from aetnamem.impact.verify import (
        load_result_rows,
        verify_experiment,
    )

    if args.impact_command == "init":
        _print(init_lab(args.path))
        return
    if args.impact_command == "verify":
        revealed_seed = (
            Path(args.seed_file).read_text(encoding="utf-8").strip()
            if args.seed_file
            else None
        )
        result = verify_experiment(
            args.results,
            public_key_path=args.public_key,
            revealed_seed=revealed_seed,
        )
        _print(result)
        if not result["valid"]:
            raise SystemExit(1)
        return
    if args.impact_command == "report":
        verification = verify_experiment(
            args.results, public_key_path=args.public_key
        )
        rows = load_result_rows(args.results)
        calibration_path = Path(args.results) / "synthetic-calibration.json"
        calibration = (
            json.loads(calibration_path.read_text(encoding="utf-8"))
            if calibration_path.is_file()
            else None
        )
        write_report(args.output, rows, verification, calibration)
        _print(
            {
                "created": str(Path(args.output).resolve()),
                "runs": len(rows),
                "verified": verification["valid"],
            }
        )
        return
    if args.impact_command != "run":
        raise ValueError(f"unknown impact command: {args.impact_command}")

    protocol_path = Path(args.protocol).resolve()
    protocol = load_protocol(protocol_path)
    results = (protocol_path.parent / protocol.results_dir).resolve()
    results.mkdir(parents=True, exist_ok=True)
    if args.stage == "synthetic":
        result = run_calibration(
            simulations=args.simulations,
            blocks=args.blocks,
        )
        output = results / "synthetic-calibration.json"
        write_calibration(output, result)
        _print({**result, "output": str(output)})
        if not result["passed"]:
            raise SystemExit(1)
        return
    if not args.confirm_paid_run:
        raise ValueError(
            "Grok stages may incur provider cost; rerun with --confirm-paid-run"
        )
    if args.max_new_runs is not None and args.max_new_runs <= 0:
        raise ValueError("--max-new-runs must be positive")
    smoke_path = results / "paid-smoke.json"
    if args.stage == "grok-smoke":
        smoke = run_paid_smoke_check(protocol, output_path=smoke_path)
        _print(smoke)
        if not smoke["passed"]:
            raise SystemExit(1)
        return
    if not smoke_path.is_file():
        raise ValueError(
            "paid Grok smoke gate has not passed; run stage grok-smoke first"
        )
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    if (
        not smoke.get("passed")
        or smoke.get("protocol_sha256") != protocol.digest
    ):
        raise ValueError("paid Grok smoke gate is invalid for this protocol")

    tasks = [
        load_task(protocol_path.parent / relative)
        for relative in protocol.task_files
    ]
    registered_tasks = results / "registered-tasks"
    registered_tasks.mkdir(exist_ok=True)
    for task in tasks:
        destination = registered_tasks / f"{task.task_id}.json"
        serialized = json.dumps(task.raw, indent=2, sort_keys=True) + "\n"
        if destination.exists() and destination.read_text(encoding="utf-8") != serialized:
            raise ValueError(f"registered task changed after scheduling: {task.task_id}")
        destination.write_text(serialized, encoding="utf-8")
    allocator = BalancedFactorialAllocator(
        experiment_id=protocol.experiment_id,
        seed=str(protocol.raw["randomization"]["seed"]),
    )
    assignments = allocator.schedule(
        [task.task_id for task in tasks], repetitions=protocol.repetitions
    )
    signing_key = Path(
        args.signing_key or protocol_path.parent / ".impact-host-key.pem"
    ).resolve()
    signer = load_signer(signing_key, key_id="memory-impact-host")
    assignments_path = results / "assignments.json"
    registration_path = results / "registration.json"
    serialized_assignments = [item.to_dict() for item in assignments]
    if assignments_path.exists():
        if json.loads(assignments_path.read_text(encoding="utf-8")) != serialized_assignments:
            raise ValueError("existing assignment schedule differs from protocol")
    else:
        assignments_path.write_text(
            json.dumps(serialized_assignments, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    schedule_sha256 = assignments[0].schedule_sha256
    registration = {
        **protocol.public_registration(),
        "schedule_sha256": schedule_sha256,
        "signing_key_id": signer.key_id,
    }
    if registration_path.exists():
        if json.loads(registration_path.read_text(encoding="utf-8")) != registration:
            raise ValueError("existing experiment registration differs from protocol")
    else:
        registration_path.write_text(
            json.dumps(registration, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    metrology = inspect_cli(
        str(protocol.raw["model"]["command"]),
        model=str(protocol.raw["model"]["name"]),
        arguments=[
            *[str(value) for value in protocol.raw["model"]["arguments"]],
            "--max-turns",
            "--session-id",
            "--single",
        ],
        cwd=protocol_path.parent,
    )
    write_metrology(results / "metrology.json", metrology)
    if not metrology["available"]:
        raise ValueError("configured Grok CLI is not available")
    if not metrology["model_advertised"]:
        raise ValueError(
            "configured model is not advertised by the authenticated Grok CLI"
        )
    missing_controls = [
        name for name, present in metrology["controls"].items() if not present
    ]
    if missing_controls:
        raise ValueError(
            "Grok CLI does not advertise registered isolation controls: "
            + ", ".join(missing_controls)
        )

    rows = load_result_rows(results)
    if args.stage == "grok-held-out":
        if any(row.get("task_split") == "held-out" for row in rows):
            raise ValueError("held-out outcomes already exist; refusing to refit policy")
        policy = freeze_policy(
            rows,
            max_mean_context_chars=float(
                protocol.raw["budgets"]["max_context_chars"]
            ),
        )
        write_policy(results / "frozen-policy.json", policy)
        selected_split = "held-out"
    else:
        policy = None
        selected_split = None

    controller = ImpactController(
        protocol,
        output_root=results,
        signer=signer,
        signature_verifier=signer.verifier(),
        metrology=metrology,
    )
    tasks_by_id = {task.task_id: task for task in tasks}
    selected_tasks = {
        task.task_id
        for task in tasks
        if (
            task.split == "held-out"
            if selected_split == "held-out"
            else task.split in {"train", "validation"}
        )
    }
    completed = {row["run_id"] for row in rows}
    created = 0
    for assignment in assignments:
        if args.max_new_runs is not None and created >= args.max_new_runs:
            break
        if assignment.task_id not in selected_tasks or assignment.run_id in completed:
            continue
        controller.run_assignment(tasks_by_id[assignment.task_id], assignment)
        created += 1
    response: dict[str, Any] = {
        "stage": args.stage,
        "created_runs": created,
        "results": str(results),
        "schedule_sha256": schedule_sha256,
        "max_new_runs": args.max_new_runs,
    }
    if policy is not None:
        final_rows = load_result_rows(results)
        held_out = evaluate_held_out(final_rows, policy)
        (results / "held-out-evaluation.json").write_text(
            json.dumps(held_out, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        response["held_out"] = held_out
    _print(response)


def _run_actions(args: argparse.Namespace) -> None:
    from aetnamem.actions import (
        ActionEngine,
        ApprovalAuthority,
        EvidenceRef,
        FilesystemAdapter,
        OperationProposal,
        TransactionJournalImporter,
        verify_action,
    )

    memory = Memory(args.path)
    try:
        if args.action_command == "stage":
            evidence = [EvidenceRef(**item) for item in json.loads(args.evidence)]
            if bool(args.authority_id) != bool(args.authority_digest):
                raise ValueError(
                    "--authority-id and --authority-digest must be supplied together"
                )
            if args.authority_id:
                evidence.append(
                    EvidenceRef(
                        kind="user_task",
                        ref_id=args.authority_id,
                        digest=args.authority_digest,
                        relation="authorized_by",
                        trust_tier="trusted_user",
                        attested=True,
                    )
                )
            engine = ActionEngine(
                memory,
                adapters=[FilesystemAdapter(args.root)],
                mode=args.mode,
            )
            patch = engine.propose(
                args.subject_id,
                [
                    OperationProposal(
                        key="operation-1",
                        adapter=args.adapter,
                        operation=args.operation,
                        arguments=json.loads(args.args),
                        evidence=tuple(evidence),
                    )
                ],
                actor_id=args.actor,
                session_id=args.session,
                turn_id=args.turn,
            )
            _print(patch.to_dict())
            return

        if args.action_command == "show":
            _print(ActionEngine(memory).get(args.transaction_id))
            return
        if args.action_command == "list":
            _print(ActionEngine(memory).list(args.subject))
            return
        if args.action_command == "approve":
            authority = ApprovalAuthority(_approval_secret(args.approval_key_file))
            engine = ActionEngine(memory, approval_authority=authority)
            transaction = engine.get(args.transaction_id)
            approval = authority.issue(
                transaction_id=args.transaction_id,
                plan_hash=transaction["plan_hash"],
                approver=args.approver_label,
                ttl_seconds=args.ttl,
            )
            _print(engine.approve(approval))
            return
        if args.action_command == "commit":
            authority = ApprovalAuthority(_approval_secret(args.approval_key_file))
            engine = ActionEngine(
                memory,
                adapters=[FilesystemAdapter(args.root)],
                approval_authority=authority,
            )
            _print(engine.commit(args.transaction_id))
            return
        if args.action_command == "abort":
            _print(ActionEngine(memory).abort(args.transaction_id, actor=args.actor))
            return
        if args.action_command == "recover":
            _print(ActionEngine(memory).recover(args.transaction_id, actor=args.actor))
            return
        if args.action_command == "verify":
            secret = _approval_secret(args.approval_key_file, required=False)
            authority = ApprovalAuthority(secret) if secret is not None else None
            result = verify_action(
                memory.store,
                args.transaction_id,
                approval_authority=authority,
            )
            _print(result)
            if not result["valid"]:
                raise SystemExit(1)
            return
        if args.action_command == "purge-payloads":
            _print(
                ActionEngine(memory).purge_payloads(
                    args.transaction_id, actor=args.actor
                )
            )
            return
        if args.action_command == "import-journal":
            _print(
                TransactionJournalImporter(memory).import_journal(
                    args.source_journal,
                    subject_id=args.subject_id,
                    source_id=args.source_id,
                    actor=args.actor,
                )
            )
            return
        raise ValueError(f"unknown actions command: {args.action_command}")
    finally:
        memory.close()


def _approval_secret(
    key_file: str | None, *, required: bool = True
) -> str | None:
    if key_file:
        value = Path(key_file).read_text(encoding="utf-8").strip()
    else:
        value = os.environ.get("AETNAMEM_APPROVAL_KEY", "").strip()
    if not value:
        if required:
            raise ValueError(
                "set AETNAMEM_APPROVAL_KEY or pass --approval-key-file; "
                "keep this key outside the agent-facing process"
            )
        return None
    return value


def _run_trial(args: argparse.Namespace) -> None:
    from aetnamem.trial import TrialManager, TrialMode
    from aetnamem.trial.manager import DEFAULT_STATE_PATH, DEFAULT_TRIAL_ROOT
    from aetnamem.trial.server import TrialMCPServer

    state_path = args.state or str(DEFAULT_STATE_PATH)
    if args.trial_command == "start":
        host = _detect_trial_host() if args.host == "auto" else args.host
        manager = TrialManager.start(
            host=host,
            state_path=state_path,
            trial_root=args.trial_root or str(DEFAULT_TRIAL_ROOT),
        )
        integration: dict[str, object]
        if args.no_configure:
            integration = {
                "configured": False,
                "warning": "host hook was not configured; no live turns will be observed",
            }
        else:
            from aetnamem.trial.hosts import configure_host

            try:
                integration = configure_host(manager.state(), state_path)
            except Exception:
                manager.transition(TrialMode.OFF, actor="setup-failure")
                raise
        status = manager.status()
        status["integration"] = integration
        status["next"] = (
            "Keep using your agent normally. Candidate facts are captured, "
            "but model context is unchanged."
            if integration.get("configured")
            else "Configure the host hook before expecting live trial evidence."
        )
        _print(status)
        return

    manager = TrialManager(state_path)
    if args.trial_command == "status":
        _print(manager.status())
    elif args.trial_command == "candidates":
        _print(manager.candidates(include_reviewed=True))
    elif args.trial_command in {"approve", "reject"}:
        _print(
            manager.review(
                list(args.candidate_ids), approve=bool(args.trial_approve)
            )
        )
    elif args.trial_command == "preview":
        state = manager.state()
        if state.mode is TrialMode.CAPTURE:
            manager.transition(TrialMode.PREVIEW)
        elif state.mode is not TrialMode.PREVIEW:
            raise ValueError(
                f"preview requires capture or preview mode, not {state.mode.value}"
            )
        _print(
            manager.prepare(args.query)
            if args.query is not None
            else manager.status()
        )
    elif args.trial_command == "canary":
        _confirm_trial_host(manager, non_interactive=args.yes)
        _print(
            manager.transition(
                TrialMode.CANARY, canary_turns=args.turns
            ).public_status()
        )
    elif args.trial_command == "activate":
        _confirm_trial_host(manager, non_interactive=args.yes)
        _print(manager.transition(TrialMode.ACTIVE).public_status())
    elif args.trial_command == "off":
        state = manager.state()
        if state.mode is not TrialMode.OFF:
            state = manager.transition(TrialMode.OFF)
        result = state.public_status()
        result["rollback_boundary"] = (
            "Future AetnaMem capture and context injection are off. Trial evidence "
            "is preserved. Past agent outputs and provider logs are not undone."
        )
        _print(result)
    elif args.trial_command == "rollback":
        from aetnamem.trial.hosts import restore_host

        _confirm_trial_host(manager, non_interactive=args.yes)
        state = manager.state()
        if state.mode is not TrialMode.OFF:
            state = manager.transition(TrialMode.OFF, actor="rollback")
        restored = restore_host(state)
        result = state.public_status()
        result["host_restore"] = restored
        result["rollback_boundary"] = (
            "The saved host plugin configuration was restored and future "
            "AetnaMem injection is off. Trial evidence is preserved. Past "
            "agent outputs and provider logs are not undone."
        )
        _print(result)
    elif args.trial_command == "capture-test":
        _print(
            manager.capture(
                args.message,
                session_id=args.session,
                authenticated_user=True,
            )
        )
    elif args.trial_command == "mcp":
        TrialMCPServer(manager).serve()
    elif args.trial_command == "dashboard":
        import webbrowser

        from aetnamem.trial.web import TrialDashboardServer, dashboard_html

        server = TrialDashboardServer(
            ("127.0.0.1", args.port), manager, html=dashboard_html()
        )
        url = f"http://127.0.0.1:{args.port}/auth?code={server.login_code}"
        print(f"Safe Switch dashboard: http://127.0.0.1:{args.port}/")
        print("The dashboard is loopback-only. Press Ctrl-C to stop.")
        if not args.no_open:
            webbrowser.open(url)
        else:
            print(f"One-time sign-in URL: {url}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:  # pragma: no cover - argparse prevents this
        raise ValueError(f"unknown trial command: {args.trial_command}")


def _detect_trial_host() -> str:
    detected = [
        name for name in ("openclaw", "hermes") if shutil.which(name) is not None
    ]
    if len(detected) == 1:
        return detected[0]
    if not detected:
        raise ValueError(
            "--host auto found neither openclaw nor hermes on PATH; "
            "pass --host openclaw or --host hermes"
        )
    raise ValueError(
        "--host auto found both openclaw and hermes; choose one explicitly"
    )


def _confirm_trial_host(
    manager: object, *, non_interactive: bool
) -> None:
    state = manager.state()  # type: ignore[attr-defined]
    if non_interactive:
        return
    if not sys.stdin.isatty():
        raise ValueError(
            f"confirmation required; rerun with --yes after reviewing host {state.host}"
        )
    entered = input(f"Type the host name `{state.host}` to confirm: ").strip()
    if entered != state.host:
        raise ValueError("host confirmation did not match")


if __name__ == "__main__":
    main()
