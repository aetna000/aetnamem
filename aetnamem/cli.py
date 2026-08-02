from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import shutil
import sys

from aetnamem.memory import Memory

DEFAULT_MCP_DB = os.environ.get(
    "AETNAMEM_DB", str(Path.home() / ".aetnamem" / "memories.db")
)


def _installed_version() -> str:
    try:
        return version("aetnamem")
    except PackageNotFoundError:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetnamem")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_installed_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    openclaw_parser = subparsers.add_parser(
        "openclaw",
        help="Install and verify the matching OpenClaw bridge",
    )
    openclaw_commands = openclaw_parser.add_subparsers(
        dest="openclaw_command",
        required=True,
    )
    openclaw_install = openclaw_commands.add_parser(
        "install",
        help="Install the bridge and start a native-memory shadow migration",
    )
    openclaw_install.add_argument(
        "--state",
        default=None,
        help="Advanced: override the local migration control-file path",
    )
    openclaw_install.add_argument(
        "--control-root",
        default=None,
        help="Advanced: override the private migration evidence directory",
    )
    openclaw_install.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )
    openclaw_memory = openclaw_commands.add_parser(
        "memory",
        help="Inspect the OpenClaw memory mirror owned by AetnaMem",
    )
    openclaw_memory_commands = openclaw_memory.add_subparsers(
        dest="openclaw_memory_command",
        required=True,
    )
    for name, help_text in (
        ("status", "Show native mirror, takeover, audit, and context-budget status"),
        ("sync", "Synchronize changed native OpenClaw memory into the shadow mirror"),
        ("search", "Search the mirrored memory by ordinary words"),
        ("trace", "Trace mirrored memories and their audit evidence"),
    ):
        command_parser = openclaw_memory_commands.add_parser(name, help=help_text)
        command_parser.add_argument("--state", default=None)
        command_parser.add_argument(
            "--json", action="store_true", help="Print machine-readable JSON"
        )
        if name in {"search", "trace"}:
            command_parser.add_argument("query")
            command_parser.add_argument("--limit", type=int, default=50)

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Run the friendly local AetnaMem mirror, audit, search, and switch UI",
    )
    dashboard_parser.add_argument("--state", default=None)
    dashboard_parser.add_argument("--port", type=int, default=8766)
    dashboard_parser.add_argument("--no-open", action="store_true")
    dashboard_commands = dashboard_parser.add_subparsers(dest="dashboard_command")
    dashboard_daemon = dashboard_commands.add_parser(
        "daemon", help="Manage the dashboard as a background user service"
    )
    dashboard_daemon_commands = dashboard_daemon.add_subparsers(
        dest="dashboard_daemon_command", required=True
    )
    for name in ("start", "open", "stop", "restart", "status", "remove"):
        command_parser = dashboard_daemon_commands.add_parser(name)
        command_parser.add_argument("--state", default=None)
        command_parser.add_argument("--port", type=int, default=8766)
        command_parser.add_argument(
            "--json", action="store_true", help="Print machine-readable JSON"
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

    control_parser = subparsers.add_parser(
        "control", help="Manage shadowing, activation, restoration, and host adapters"
    )
    control_commands = control_parser.add_subparsers(
        dest="control_command", required=True
    )
    control_shadow = control_commands.add_parser(
        "shadow", help="Mirror native memory while OpenClaw remains active"
    )
    control_shadow.add_argument(
        "--host",
        choices=("openclaw",),
        default="openclaw",
        help="Verified host adapter; OpenClaw is supported in this release",
    )
    control_shadow.add_argument(
        "--state",
        default=None,
        help="Advanced: override the local migration control-file path",
    )
    control_shadow.add_argument(
        "--control-root",
        default=None,
        help="Advanced: override the private migration evidence directory",
    )
    control_shadow.add_argument(
        "--no-configure",
        action="store_true",
        help="Testing only: create migration state without installing the host hook",
    )
    control_shadow.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON"
    )

    for name, help_text in (
        ("status", "Show which memory provider is active and whether switching is safe"),
        ("activate", "Make AetnaMem the OpenClaw memory provider"),
        ("restore", "Restore OpenClaw memory; preserve AetnaMem evidence"),
        ("mcp", "Serve the private host-integration protocol over stdio"),
        ("dashboard", "Open the local memory mirror and switch dashboard"),
    ):
        command_parser = control_commands.add_parser(name, help=help_text)
        command_parser.add_argument("--state", default=None)
        if name not in {"mcp", "dashboard"}:
            command_parser.add_argument(
                "--json", action="store_true", help="Print machine-readable JSON"
            )
        if name == "dashboard":
            command_parser.add_argument("--port", type=int, default=8766)
            command_parser.add_argument("--no-open", action="store_true")
        if name in {"activate", "restore"}:
            command_parser.add_argument(
                "--yes", action="store_true", help="Confirm non-interactively"
            )

    args = parser.parse_args()

    if args.command == "openclaw":
        _run_openclaw(args)
        return

    if args.command == "dashboard":
        _run_dashboard(args)
        return

    if args.command == "control":
        _run_control(args)
        return

    if args.command == "index":
        _run_index(args)
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


def _run_openclaw(args: argparse.Namespace) -> None:
    if args.openclaw_command == "memory":
        from aetnamem.control import ControlPlaneManager
        from aetnamem.control.manager import DEFAULT_STATE_PATH
        from aetnamem.control.openclaw_native import (
            mirror_status,
            search_mirror,
            sync_mirror,
            takeover_status,
            trace_mirror,
        )

        manager = ControlPlaneManager(args.state or DEFAULT_STATE_PATH)
        state = manager.state()
        command = args.openclaw_memory_command
        if command == "sync":
            result = sync_mirror(state)
        elif command == "status":
            result = {
                "format": "aetnamem-openclaw-memory-status-v1",
                "mode": state.mode.value,
                "mirror": mirror_status(state),
                "takeover": takeover_status(state),
            }
        elif command == "search":
            result = search_mirror(state, args.query, limit=args.limit)
        elif command == "trace":
            result = trace_mirror(state, args.query, limit=args.limit)
        else:
            raise ValueError(f"unknown OpenClaw memory command: {command}")
        if args.json:
            _print(result)
        else:
            _print_openclaw_memory(command, result)
        return
    if args.openclaw_command != "install":
        raise ValueError(f"unknown OpenClaw command: {args.openclaw_command}")
    from aetnamem.openclaw_install import install_openclaw
    from aetnamem.control.manager import DEFAULT_STATE_PATH, DEFAULT_CONTROL_ROOT

    try:
        def show_progress(step: int, total: int, label: str) -> None:
            width = 20
            filled = min(width, max(0, round(width * step / max(1, total))))
            bar = "#" * filled + "-" * (width - filled)
            print(
                f"[{bar}] {step}/{total}  {label}",
                file=sys.stderr,
                flush=True,
            )

        result = install_openclaw(
            state_path=args.state or DEFAULT_STATE_PATH,
            control_root=args.control_root or DEFAULT_CONTROL_ROOT,
            progress=None if args.json else show_progress,
        )
    except ValueError as exc:
        if args.json:
            _print(
                {
                    "format": "aetnamem-openclaw-install-v1",
                    "installed": False,
                    "error": str(exc),
                }
            )
        else:
            print("AetnaMem OpenClaw installation did not complete", file=sys.stderr)
            print(f"\n{exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if args.json:
        _print(result)
        return
    print("AetnaMem is installed beside OpenClaw")
    print(f"\n  Engine version        {result['engine_version']}")
    print(f"  Engine executable     {result['engine_executable']}")
    print(f"  OpenClaw bridge       {result['plugin_version']}")
    print(
        "  Gateway verification "
        + ("PASSED" if result.get("gateway_verified") else "FAILED")
    )
    print(
        "  Native memory baseline "
        + ("PASSED" if result.get("native_baseline_verified") else "FAILED")
    )
    print(
        "  Baseline files         "
        f"{int(result.get('native_baseline_files') or 0)}"
    )
    print(
        "  Baseline bytes         "
        f"{int(result.get('native_baseline_bytes') or 0):,}"
    )
    print(
        "  Search mirror          "
        + ("PASSED" if result.get("mirror_verified") else "FAILED")
    )
    print("  Control mode            shadow capture")
    print("  Model context changed no")
    print("  Extra provider calls  no")
    print(f"  Control ID              {result['migration_id']}")
    print(f"  Evidence directory    {result['control_dir']}")
    print(
        "\nKeep using OpenClaw normally. AetnaMem will collect candidate memories "
        "locally and mirror native memory without changing model context."
    )
    print("Next: aetnamem dashboard")


def _print_openclaw_memory(command: str, result: dict[str, object]) -> None:
    if command == "status":
        mirror = result.get("mirror")
        mirror = mirror if isinstance(mirror, dict) else {}
        takeover = result.get("takeover")
        takeover = takeover if isinstance(takeover, dict) else {}
        print("AetnaMem OpenClaw memory status")
        print(f"\n  Mode                    {result.get('mode', 'unknown')}")
        print(
            "  Native mirror           "
            + ("synchronized" if mirror.get("synced") else "NOT READY")
        )
        print(f"  Native sources          {int(mirror.get('source_count') or 0)}")
        print(f"  Mirrored records        {int(mirror.get('record_count') or 0)}")
        print(f"  Source bytes            {int(mirror.get('source_bytes') or 0):,}")
        baseline = mirror.get("native_baseline")
        baseline = baseline if isinstance(baseline, dict) else {}
        history = mirror.get("shadow_history")
        history = history if isinstance(history, dict) else {}
        print(
            "  Pre-shadow baseline     "
            + ("PASSED" if baseline.get("snapshot_sha256") else "MISSING")
        )
        if baseline.get("snapshot_sha256"):
            print(
                "  Baseline files          "
                f"{int(baseline.get('file_count') or 0)}"
            )
            print(
                "  Baseline digest         "
                f"{baseline.get('snapshot_sha256')}"
            )
            print(
                "  Observed change states  "
                f"{int(history.get('observed_change_versions') or 0)}"
            )
        print(
            "  Audit verification      "
            + ("PASSED" if mirror.get("audit_verified") else "FAILED")
        )
        print(f"  Mirror database         {mirror.get('mirror_db', 'not created')}")
        print(f"  Manifest                {mirror.get('manifest_sha256', 'none')}")
        print(
            "  Native memory takeover  "
            + ("active" if takeover.get("active") else "shadow only")
        )
        snapshot = takeover.get("native_snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        if takeover.get("native_snapshot_verified"):
            print("  Complete native snapshot PASSED")
            print(
                "  Snapshot files          "
                f"{int(snapshot.get('file_count') or 0)}"
            )
            print(
                "  Snapshot bytes          "
                f"{int(snapshot.get('total_bytes') or 0):,}"
            )
            print(
                "  Snapshot digest         "
                f"{snapshot.get('snapshot_sha256', 'none')}"
            )
        print(
            "  Cost projection         "
            + str(mirror.get("token_projection") or "not measured").replace("_", " ")
        )
        if not takeover.get("active"):
            print(
                "\nOpenClaw native memory remains authoritative. "
                "AetnaMem is mirroring and auditing without changing prompts."
            )
        else:
            print(
                "\nAetnaMem owns supplemental memory recall. The frozen native "
                "snapshot remains available for verified restore."
            )
        return
    if command == "sync":
        print("AetnaMem OpenClaw mirror synchronized")
        print(f"\n  Sources          {int(result.get('source_count') or 0)}")
        print(f"  Records          {int(result.get('record_count') or 0)}")
        print(f"  Source bytes     {int(result.get('source_bytes') or 0):,}")
        print(f"  Database         {result.get('mirror_db')}")
        print(f"  Manifest         {result.get('manifest_sha256')}")
        return
    if command == "search":
        rows = result.get("records")
        rows = rows if isinstance(rows, list) else []
        print(f"AetnaMem OpenClaw memory search\n\n  {len(rows)} result(s)")
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            content = str(row.get("content") or "").replace("\n", " ").strip()
            print(f"  {index}. {content}")
            provenance = row.get("openclaw_provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            source = provenance.get("relative_path") or row.get("source_type")
            lines = (
                f" lines {provenance.get('line_start')}-{provenance.get('line_end')}"
                if provenance.get("line_start")
                else ""
            )
            print(f"     record {row.get('id')} · {source}{lines}")
        return
    if command == "trace":
        from aetnamem.investigate import format_trace

        print(format_trace(result), end="")
        return


def _print_control(command: str, value: object, *, json_output: bool) -> None:
    if json_output:
        _print(value)
        return
    result = value if isinstance(value, dict) else {}
    if command == "restore":
        restored = result.get("host_restore")
        restored = restored if isinstance(restored, dict) else {}
        verified = bool(restored.get("verified"))
        print("AetnaMem restore complete")
        print(f"\n  Host                 {_display_host(result.get('host'))}")
        print(
            "  Host configuration   "
            + ("restored" if restored.get("restored") else "not restored")
        )
        print(f"  Verification         {'PASSED' if verified else 'FAILED'}")
        print("  Memory provider      OpenClaw")
        plugin_enabled = restored.get("plugin_enabled")
        if plugin_enabled is True:
            print("  AetnaMem plugin      enabled (restored pre-migration state)")
        elif plugin_enabled is False:
            print("  AetnaMem plugin      disabled")
        else:
            print("  AetnaMem plugin      state unknown")
        takeover_restore = restored.get("takeover")
        takeover_restore = (
            takeover_restore if isinstance(takeover_restore, dict) else {}
        )
        preserved = takeover_restore.get("post_switch_native_preserved")
        if isinstance(preserved, list) and preserved:
            print(f"  Post-switch files    preserved ({len(preserved)})")
        active_export = takeover_restore.get("active_memory_export")
        active_export = active_export if isinstance(active_export, dict) else {}
        exported_count = int(active_export.get("record_count") or 0)
        if exported_count:
            print(f"  Active memories      returned to OpenClaw ({exported_count})")
            print(f"  Native export        {active_export.get('path')}")
        print("  Control evidence       preserved")
        if result.get("migration_id"):
            print(f"  Control ID             {result['migration_id']}")
        if result.get("control_dir"):
            print(f"  Evidence directory   {result['control_dir']}")
        print("\nYour original host configuration has been restored.")
        if plugin_enabled is True:
            print(
                "AetnaMem itself is still enabled because it was enabled before "
                "this control-plane migration."
            )
        else:
            print("AetnaMem is not enabled in the restored host configuration.")
        print("Past agent outputs and provider logs are unchanged.")
        return
    titles = {
        "shadow": "AetnaMem shadowing started",
        "status": "OpenClaw memory status",
        "activate": "AetnaMem is active",
    }
    print(titles.get(command, "AetnaMem memory control plane"))
    _print_control_status_rows(result)
    if command == "shadow":
        integration = result.get("integration")
        integration = integration if isinstance(integration, dict) else {}
        print(
            f"  Host integration      "
            f"{'configured' if integration.get('configured') else 'not configured'}"
        )
        print("\nOpenClaw memory remains active.")
        print("AetnaMem is copying, indexing, and auditing it without changing prompts.")
    elif command == "status":
        readiness = result.get("readiness")
        readiness = readiness if isinstance(readiness, dict) else {}
        reasons = readiness.get("reasons")
        if result.get("mode") == "off" and readiness.get("ready_for_active"):
            print(
                "\nReady: the preserved mirror verified. Inspect/search it, "
                "then activate when satisfied."
            )
        elif result.get("mode") == "off":
            print(
                "\nNext: start a new migration with "
                "`aetnamem control shadow --host openclaw`."
            )
        elif result.get("mode") == "active":
            print(
                "\nAetnaMem is active. Use `aetnamem control restore` "
                "to restore OpenClaw memory."
            )
        elif isinstance(reasons, list) and reasons:
            print(f"\nNext: {reasons[0]}")
        elif readiness.get("ready_for_active"):
            print("\nReady: inspect/search the mirror, then activate when satisfied.")
    elif command == "activate":
        print(
            "\nAetnaMem now supplies bounded, governed memory context. "
            "Use `aetnamem control restore` to restore the saved host configuration."
        )


def _print_control_status_rows(result: dict[str, object]) -> None:
    mode = str(result.get("mode") or "unknown")
    evidence = result.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    chain = evidence.get("transition_chain")
    chain = chain if isinstance(chain, dict) else {}
    mirror = result.get("mirror")
    mirror = mirror if isinstance(mirror, dict) else {}
    provider = "AetnaMem" if mode == "active" else _display_host(result.get("host"))
    print(f"\n  Memory provider       {provider}")
    print(f"  Host                  {_display_host(result.get('host'))}")
    print(
        "  Changes agent context "
        + ("yes" if result.get("changes_model_context") else "no")
    )
    print(
        "  Extra provider calls  "
        + ("yes" if result.get("makes_extra_provider_calls") else "no")
    )
    if mirror:
        print(f"  Mirrored files        {int(mirror.get('source_count') or 0)}")
        print(f"  Searchable memories   {int(mirror.get('record_count') or 0)}")
        print(
            "  Mirror verification   "
            + ("PASSED" if mirror.get("audit_verified") else "CHECK REQUIRED")
        )
    if evidence:
        print(
            "  Audit chain           "
            + ("valid" if chain.get("valid") else "CHECK REQUIRED")
        )
    if result.get("migration_id"):
        print(f"  Control ID              {result['migration_id']}")


def _display_host(value: object) -> str:
    text = str(value or "unknown")
    return {"openclaw": "OpenClaw"}.get(text, text)


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


def _run_dashboard(args: argparse.Namespace) -> None:
    if args.dashboard_command == "daemon":
        from aetnamem.dashboard_daemon import manage_dashboard_daemon

        result = manage_dashboard_daemon(
            args.dashboard_daemon_command,
            port=args.port,
            control_state_path=args.state,
        )
        if args.json:
            _print(result)
            return
        print("AetnaMem dashboard daemon")
        print(
            f"\n  Status       "
            f"{'running' if result.get('running') else 'stopped'}"
        )
        if result.get("pid"):
            print(f"  Process      {result['pid']}")
        if result.get("port"):
            print(f"  Port         {result['port']}")
        if result.get("url"):
            print(f"  Dashboard    {result['url']}")
        if result.get("log_path"):
            print(f"  Log          {result['log_path']}")
        if result.get("opened"):
            print("\nOpened the dashboard in the default browser.")
        if result.get("removed"):
            print("\nThe background service record was removed. Memory and migration data were preserved.")
        return
    _serve_dashboard(
        state_path=args.state,
        port=args.port,
        open_browser=not args.no_open,
    )


def _serve_dashboard(
    *,
    state_path: str | None,
    port: int,
    open_browser: bool,
) -> None:
    import webbrowser

    from aetnamem.control import ControlPlaneManager
    from aetnamem.control.manager import DEFAULT_STATE_PATH
    from aetnamem.control.web import ControlDashboardServer, dashboard_html

    manager = ControlPlaneManager(state_path or DEFAULT_STATE_PATH)
    # Fail before opening a port if no valid migration exists.
    manager.state()
    server = ControlDashboardServer(
        ("127.0.0.1", port),
        manager,
        html=dashboard_html(),
    )
    base = f"http://127.0.0.1:{server.server_port}/"
    print(f"AetnaMem dashboard: {base}", flush=True)
    print("No login is required. The dashboard is loopback-only. Press Ctrl-C to stop.", flush=True)
    if open_browser:
        webbrowser.open(base)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _run_control(args: argparse.Namespace) -> None:
    from aetnamem.control import ControlPlaneManager, ControlMode
    from aetnamem.control.manager import DEFAULT_STATE_PATH, DEFAULT_CONTROL_ROOT
    from aetnamem.control.server import ControlMCPServer

    state_path = args.state or str(DEFAULT_STATE_PATH)
    if args.control_command == "shadow":
        host = args.host
        manager = ControlPlaneManager.start(
            host=host,
            state_path=state_path,
            control_root=args.control_root or str(DEFAULT_CONTROL_ROOT),
        )
        integration: dict[str, object]
        if args.no_configure:
            integration = {
                "configured": False,
                "warning": "host hook was not configured; no live turns will be observed",
            }
        else:
            from aetnamem.control.hosts import configure_host

            try:
                integration = configure_host(manager.state(), state_path)
            except Exception:
                manager.transition(ControlMode.OFF, actor="setup-failure")
                raise
        status = manager.status()
        status["integration"] = integration
        status["next"] = (
            "Keep using your agent normally. Native memory is mirrored and "
            "searchable, but model context is unchanged."
            if integration.get("configured")
            else "Configure the host hook before expecting live migration evidence."
        )
        _print_control("shadow", status, json_output=args.json)
        return

    manager = ControlPlaneManager(state_path)
    if args.control_command == "status":
        _print_control("status", manager.status(), json_output=args.json)
    elif args.control_command == "activate":
        _confirm_control_host(manager, non_interactive=args.yes)
        readiness = manager.status().get("readiness") or {}
        if not readiness.get("ready_for_active"):
            raise ValueError("; ".join(readiness.get("reasons") or ["migration is not ready"]))
        state = manager.state()
        if state.host == "openclaw":
            from aetnamem.control.openclaw_native import (
                activate_takeover,
                restore_takeover,
            )

            def activation_progress(step: int, total: int, label: str) -> None:
                if args.json:
                    return
                width = 20
                filled = min(width, max(0, round(width * step / max(1, total))))
                bar = "#" * filled + "-" * (width - filled)
                print(
                    f"[{bar}] {step}/{total}  {label}",
                    file=sys.stderr,
                    flush=True,
                )

            takeover = activate_takeover(
                state,
                manager.state_path,
                progress=activation_progress,
            )
            try:
                state = manager.transition(ControlMode.ACTIVE)
            except Exception:
                restore_takeover(state)
                raise
        else:
            state = manager.transition(ControlMode.ACTIVE)
            takeover = {
                "activated": True,
                "host": state.host,
                "native_memory_replaced": False,
            }
        result = state.public_status()
        result["takeover"] = takeover
        result["mirror"] = manager.status().get("mirror")
        _print_control(
            "activate",
            result,
            json_output=args.json,
        )
    elif args.control_command == "restore":
        from aetnamem.control.hosts import restore_host
        from aetnamem.control.openclaw_native import (
            restart_and_verify_gateway,
            restore_takeover,
        )

        _confirm_control_host(manager, non_interactive=args.yes)
        state = manager.state()
        def restore_progress(step: int, total: int, label: str) -> None:
            if args.json:
                return
            width = 20
            filled = min(width, max(0, round(width * step / max(1, total))))
            bar = "#" * filled + "-" * (width - filled)
            print(
                f"[{bar}] {step}/{total}  {label}",
                file=sys.stderr,
                flush=True,
            )

        takeover_restore = restore_takeover(
            state,
            progress=restore_progress,
        )
        if state.mode is not ControlMode.OFF:
            state = manager.transition(ControlMode.OFF, actor="restore")
        restored = restore_host(state)
        gateway = (
            restart_and_verify_gateway()
            if state.host == "openclaw"
            else {"restarted": False, "verified": True}
        )
        restored["takeover"] = takeover_restore
        restored["gateway"] = gateway
        restored["verified"] = bool(restored.get("verified")) and bool(
            gateway.get("verified")
        )
        result = state.public_status()
        result["host_restore"] = restored
        result["restore_boundary"] = (
            "The saved host plugin configuration was restored and future "
            "AetnaMem injection is off. Control evidence is preserved. Past "
            "agent outputs and provider logs are not undone."
        )
        _print_control("restore", result, json_output=args.json)
    elif args.control_command == "mcp":
        ControlMCPServer(manager).serve()
    elif args.control_command == "dashboard":
        _serve_dashboard(
            state_path=state_path,
            port=args.port,
            open_browser=not args.no_open,
        )
    else:  # pragma: no cover - argparse prevents this
        raise ValueError(f"unknown control command: {args.control_command}")


def _confirm_control_host(
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
