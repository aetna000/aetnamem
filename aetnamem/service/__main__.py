"""Run the loopback control service: ``python -m aetnamem.service``.

Wires a default governed core — memory tools plus a rooted filesystem
``write_file`` guarded tool — and prints the two role tokens. Point the
assistant loop at the agent token and the dashboard at the reviewer token.
"""

from __future__ import annotations

import argparse
import os
import signal
import secrets
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

from aetnamem import Memory
from aetnamem.actions import ActionEngine, ApprovalAuthority, FilesystemAdapter
from aetnamem.assistant.providers import (
    DEFAULT_LOCAL_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    ProviderConfig,
    config_from_env,
)
from aetnamem.service.app import _ollama_available, build_service, serve
from aetnamem.broker import ToolBroker
from aetnamem.service.encrypted_db import EncryptedDatabaseManager
from aetnamem.maintenance import GraphMaintenanceWorker


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetnamem-control")
    parser.add_argument("--db", default=os.environ.get("AETNAMEM_DB", "~/.aetnamem/memories.db"))
    parser.add_argument("--workspace", default=os.environ.get("AETNAMEM_WORKSPACE", "~/.aetnamem/workspace"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--include-promote", action="store_true")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="do not auto-open the dashboard in the default browser",
    )
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

    graph_recall = os.environ.get("AETNAMEM_GRAPH_RECALL", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    memory = Memory(db_path, graph_recall=graph_recall)
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
    service.workspace = workspace
    service.db_info = {
        "db_path": str(db_path),
        "db_sealed_at_rest": encrypted_manager is not None,
        "db_sealed_path": (
            str(encrypted_manager.encrypted_path) if encrypted_manager is not None else None
        ),
        "db_key_storage": "macos-keychain" if encrypted_manager is not None else None,
        "graph_archive_path": str(
            (
                encrypted_manager.encrypted_path.parent
                if encrypted_manager is not None
                else Path(db_path).parent
            )
            / "graph-archive"
        ),
    }
    provider_config = config_from_env()
    if provider_config.kind == "echo" and _ollama_available(DEFAULT_OLLAMA_BASE_URL):
        provider_config = ProviderConfig(
            kind="local", model=DEFAULT_LOCAL_MODEL, base_url=DEFAULT_OLLAMA_BASE_URL
        )
    service.provider_config = provider_config
    server = serve(service, host=args.host, port=args.port)

    maintenance_interval = max(
        0.0,
        float(
            os.environ.get(
                "AETNAMEM_GRAPH_MAINTENANCE_SECONDS",
                "3600" if graph_recall else "0",
            )
        ),
    )
    maintenance: GraphMaintenanceWorker | None = None
    if maintenance_interval:
        default_archive_root = str(service.db_info["graph_archive_path"])
        archive_root = Path(
            os.environ.get(
                "AETNAMEM_GRAPH_ARCHIVE_DIR",
                default_archive_root,
            )
        ).expanduser()
        archive_days = int(
            os.environ.get(
                "AETNAMEM_GRAPH_ARCHIVE_AFTER_DAYS",
                "0" if encrypted_manager is not None else "365",
            )
        )
        maintenance = GraphMaintenanceWorker(
            db_path,
            interval_seconds=maintenance_interval,
            archive_root=archive_root,
            archive_after_days=archive_days,
            on_error=lambda exc: print(
                f"warning: graph maintenance failed: {exc}", flush=True
            ),
        )
        maintenance.start()

    seal_interval = max(
        0.0, float(os.environ.get("AETNAMEM_SEAL_INTERVAL_SECONDS", "15"))
    )
    last_sealed = 0.0
    seal_dirty = False

    def checkpoint_and_seal(*, force: bool = False) -> None:
        nonlocal last_sealed, seal_dirty
        if encrypted_manager is None:
            return
        now = time.monotonic()
        if force and last_sealed and not seal_dirty:
            return
        if not force:
            seal_dirty = True
        if not force and last_sealed and now - last_sealed < seal_interval:
            return
        try:
            memory.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # noqa: SLF001
        except Exception as exc:
            print(f"warning: database checkpoint failed; seal deferred: {exc}", flush=True)
            return
        encrypted_manager.seal()
        last_sealed = now
        seal_dirty = False

    service.after_mutation = (
        (lambda: checkpoint_and_seal(force=False))
        if encrypted_manager is not None
        else None
    )

    print(f"aetnamem control service on http://{args.host}:{args.port}", flush=True)
    print(f"  dashboard : http://{args.host}:{args.port}/app", flush=True)
    print(f"  db        : {db_path}", flush=True)
    if encrypted_manager is not None:
        print(f"  sealed db : {encrypted_manager.encrypted_path}", flush=True)
    print(f"  workspace : {workspace}", flush=True)
    print(f"  provider  : {provider_config.kind} / {provider_config.model}", flush=True)
    print(f"  graph recall : {'enabled' if graph_recall else 'disabled'}", flush=True)
    print(
        "  graph maintenance : "
        + (f"every {maintenance_interval:g}s" if maintenance else "disabled"),
        flush=True,
    )
    print(f"  agent token    (assistant loop): {service.agent_token}", flush=True)
    print(f"  reviewer token (dashboard)     : {service.reviewer_token}", flush=True)
    print("Ctrl-C to stop.", flush=True)

    # Tokens travel in the URL fragment, which the browser never sends over
    # the wire; the dashboard stores them locally and strips the fragment.
    signin_url = (
        f"http://{args.host}:{args.port}/app"
        f"#agent={quote(service.agent_token)}&reviewer={quote(service.reviewer_token)}"
    )
    if not args.no_open:
        opened = webbrowser.open(signin_url)
        if not opened:
            print(f"Open this URL to sign in automatically:\n  {signin_url}", flush=True)
    else:
        print(f"Sign-in URL: {signin_url}", flush=True)

    def stop(_signum, _frame) -> None:
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        if maintenance is not None:
            maintenance.stop()
        checkpoint_and_seal(force=True)
        memory.close()
        if encrypted_manager is not None:
            encrypted_manager.__exit__(None, None, None)


if __name__ == "__main__":
    main()
