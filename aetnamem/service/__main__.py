"""Run the loopback control service: ``python -m aetnamem.service``.

Wires a default governed core — memory tools plus a rooted filesystem
``write_file`` guarded tool — and prints the two role tokens. Point the
assistant loop at the agent token and the dashboard at the reviewer token.
"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from aetnamem import Memory
from aetnamem.actions import ActionEngine, ApprovalAuthority, FilesystemAdapter
from aetnamem.assistant.providers import config_from_env
from aetnamem.broker import ToolBroker
from aetnamem.service.app import build_service, serve
from aetnamem.service.encrypted_db import EncryptedDatabaseManager


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetnamem-control")
    parser.add_argument("--db", default=os.environ.get("AETNAMEM_DB", "~/.aetnamem/memories.db"))
    parser.add_argument("--workspace", default=os.environ.get("AETNAMEM_WORKSPACE", "~/.aetnamem/workspace"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--include-promote", action="store_true")
    parser.add_argument(
        "--encrypted-db",
        default=os.environ.get("AETNAMEM_ENCRYPTED_DB", ""),
        help="macOS-only encrypted DB path; live DB is sealed here on shutdown",
    )
    args = parser.parse_args()

    encrypted_manager: EncryptedDatabaseManager | None = None
    if args.encrypted_db:
        encrypted_manager = EncryptedDatabaseManager(args.encrypted_db).__enter__()
        db_path = encrypted_manager.runtime_path
        assert db_path is not None
    else:
        db_path = Path(args.db).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(args.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    secret = os.environ.get("AETNAMEM_APPROVAL_KEY") or secrets.token_hex(32)
    authority = ApprovalAuthority(secret)

    memory = Memory(db_path)
    engine = ActionEngine(
        memory,
        adapters=[FilesystemAdapter(workspace)],
        approval_authority=authority,
    )
    broker = ToolBroker(engine)
    broker.register_default_memory_tools(include_promote=args.include_promote)
    broker.register_guarded(
        "write_file",
        "Write UTF-8 text to a file in the user's workspace.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        adapter="filesystem",
        operation="write_text",
    )
    service = build_service(engine, broker)
    service.provider_config = config_from_env()
    server = serve(service, host=args.host, port=args.port)

    print(f"aetnamem control service on http://{args.host}:{args.port}", flush=True)
    print(f"  dashboard : http://{args.host}:{args.port}/app", flush=True)
    print(f"  db        : {db_path}", flush=True)
    if encrypted_manager is not None:
        print(f"  sealed db : {encrypted_manager.encrypted_path}", flush=True)
    print(f"  workspace : {workspace}", flush=True)
    print(f"  agent token    (assistant loop): {service.agent_token}", flush=True)
    print(f"  reviewer token (dashboard)     : {service.reviewer_token}", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        try:
            memory.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # noqa: SLF001
        except Exception:
            pass
        memory.close()
        if encrypted_manager is not None:
            encrypted_manager.seal()
            encrypted_manager.__exit__(None, None, None)


if __name__ == "__main__":
    main()
