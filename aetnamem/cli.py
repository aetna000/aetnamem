from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from aetnamem.memory import Memory

DEFAULT_MCP_DB = os.environ.get(
    "AETNAMEM_DB", str(Path.home() / ".aetnamem" / "memories.db")
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetnamem")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    list_parser = subparsers.add_parser("list", help="List a subject's records")
    list_parser.add_argument("path")
    list_parser.add_argument("subject_id")
    list_parser.add_argument(
        "--all", action="store_true", help="Include superseded/quarantined/tombstoned"
    )

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
    elif args.command == "forget":
        result = memory.forget(
            args.subject_id,
            selector=args.contains,
            utterance=args.utterance,
            session_id=args.session,
        )
        _print(result)
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


if __name__ == "__main__":
    main()
