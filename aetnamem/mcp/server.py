"""Minimal MCP (Model Context Protocol) server over stdio.

Implements the subset of MCP that tool use requires — initialize, ping,
tools/list, tools/call — as newline-delimited JSON-RPC 2.0 on stdin/stdout,
using only the standard library so `aetnamem mcp` keeps the zero-dependency
promise. Diagnostics go to stderr; stdout carries protocol messages only.

Any MCP-capable agent host (Claude Code, Claude Desktop, OpenClaw via its
MCP bridge, etc.) gets persistent, auditable memory by running:

    aetnamem mcp --db ~/.aetnamem/memories.db
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

PROTOCOL_VERSION = "2025-06-18"

try:
    from importlib.metadata import version as _pkg_version

    SERVER_VERSION = _pkg_version("aetnamem")
except Exception:  # not installed (e.g. run from a checkout)
    SERVER_VERSION = "0.3.0"

_SUBJECT_PROPERTY = {
    "subject_id": {
        "type": "string",
        "description": "User/tenant scope; omit to use the server default.",
    }
}
_SESSION_PROPERTIES = {
    "session_id": {"type": "string", "description": "Conversation/session id."},
    "turn_id": {"type": "string", "description": "Turn id within the session."},
}


class MCPServer:
    def __init__(
        self,
        memory: Any,
        *,
        default_subject: str = "default",
        checkpoints_path: str | None = None,
    ) -> None:
        self.memory = memory
        self.default_subject = default_subject
        self.checkpoints_path = checkpoints_path

    # ------------------------------------------------------------- transport

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._write(stdout, _error(None, -32700, "parse error"))
                continue
            response = self.handle(message)
            if response is not None:
                self._write(stdout, response)

    @staticmethod
    def _write(stdout: TextIO, message: dict[str, Any]) -> None:
        stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
        stdout.flush()

    # -------------------------------------------------------------- protocol

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        is_notification = "id" not in message

        if not isinstance(method, str):
            return None
        if is_notification:
            # notifications/initialized, notifications/cancelled, ...
            return None

        try:
            if method == "initialize":
                params = message.get("params") or {}
                return _result(
                    request_id,
                    {
                        "protocolVersion": params.get(
                            "protocolVersion", PROTOCOL_VERSION
                        ),
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "aetnamem",
                            "version": SERVER_VERSION,
                        },
                    },
                )
            if method == "ping":
                return _result(request_id, {})
            if method == "tools/list":
                return _result(request_id, {"tools": self._tool_definitions()})
            if method == "tools/call":
                params = message.get("params") or {}
                return self._call_tool(
                    request_id,
                    params.get("name", ""),
                    params.get("arguments") or {},
                )
            return _error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:  # protocol must survive tool bugs
            print(f"aetnamem-mcp error: {exc!r}", file=sys.stderr)
            return _error(request_id, -32603, str(exc))

    # ----------------------------------------------------------------- tools

    def _call_tool(
        self, request_id: Any, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "memory_remember": self._tool_remember,
            "memory_recall": self._tool_recall,
            "memory_recall_block": self._tool_recall_block,
            "memory_persona": self._tool_persona,
            "memory_capture": self._tool_capture,
            "memory_list": self._tool_list,
            "memory_forget": self._tool_forget,
            "memory_promote": self._tool_promote,
            "memory_audit": self._tool_audit,
            "memory_verify": self._tool_verify,
            "memory_graph_status": self._tool_graph_status,
            "memory_graph_merges": self._tool_graph_merges,
            "memory_graph_history": self._tool_graph_history,
            "memory_log_action": self._tool_log_action,
        }
        handler = handlers.get(name)
        if handler is None:
            return _error(request_id, -32602, f"unknown tool: {name}")
        try:
            outcome = handler(arguments)
        except Exception as exc:
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            )
        return _result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(outcome, indent=2, sort_keys=True),
                    }
                ],
                "isError": False,
            },
        )

    def _subject(self, arguments: dict[str, Any]) -> str:
        return str(arguments.get("subject_id") or self.default_subject)

    def _tool_remember(self, arguments: dict[str, Any]) -> Any:
        return self.memory.remember(
            self._subject(arguments),
            arguments["message"],
            session_id=arguments.get("session_id"),
            turn_id=arguments.get("turn_id"),
            source_type=arguments.get("source_type"),
        )

    def _tool_recall(self, arguments: dict[str, Any]) -> Any:
        return self.memory.recall(
            self._subject(arguments),
            arguments["query"],
            session_id=arguments.get("session_id"),
            limit=int(arguments.get("limit", 10)),
            min_score=arguments.get("min_score"),
            use_graph=arguments.get("use_graph"),
        )

    def _tool_recall_block(self, arguments: dict[str, Any]) -> Any:
        return self.memory.build_recall_block(
            self._subject(arguments),
            arguments["query"],
            session_id=arguments.get("session_id"),
            max_records=int(arguments.get("max_records", 5)),
            max_chars=int(arguments.get("max_chars", 2000)),
            min_score=float(arguments.get("min_score", 0.3)),
            use_graph=arguments.get("use_graph"),
        )

    def _tool_persona(self, arguments: dict[str, Any]) -> Any:
        return self.memory.build_persona(
            self._subject(arguments),
            session_id=arguments.get("session_id"),
            max_chars=int(arguments.get("max_chars", 1500)),
        )

    def _tool_capture(self, arguments: dict[str, Any]) -> Any:
        return self.memory.capture(
            self._subject(arguments),
            arguments["role"],
            arguments["content"],
            session_id=arguments.get("session_id"),
            turn_id=arguments.get("turn_id"),
            tool_name=arguments.get("tool_name"),
        )

    def _tool_list(self, arguments: dict[str, Any]) -> Any:
        return self.memory.list(
            self._subject(arguments),
            include_inactive=bool(arguments.get("include_inactive", False)),
        )

    def _tool_forget(self, arguments: dict[str, Any]) -> Any:
        return self.memory.forget(
            self._subject(arguments),
            selector=arguments.get("contains"),
            utterance=arguments.get("utterance"),
            session_id=arguments.get("session_id"),
            turn_id=arguments.get("turn_id"),
        )

    def _tool_promote(self, arguments: dict[str, Any]) -> Any:
        return self.memory.promote(
            self._subject(arguments),
            arguments["record_id"],
            session_id=arguments.get("session_id"),
        )

    def _tool_audit(self, arguments: dict[str, Any]) -> Any:
        return self.memory.audit(self._subject(arguments))

    def _tool_verify(self, arguments: dict[str, Any]) -> Any:
        return self.memory.verify(
            arguments.get("subject_id"),
            checkpoints_path=arguments.get("checkpoints_path", self.checkpoints_path),
            incremental=bool(arguments.get("incremental", False)),
        )

    def _tool_graph_status(self, arguments: dict[str, Any]) -> Any:
        return self.memory.inspect_graph(self._subject(arguments))

    def _tool_graph_merges(self, arguments: dict[str, Any]) -> Any:
        return self.memory.list_graph_merge_proposals(
            self._subject(arguments), status=arguments.get("status")
        )

    def _tool_graph_history(self, arguments: dict[str, Any]) -> Any:
        year = arguments.get("partition_year")
        return self.memory.read_graph_archive(
            self._subject(arguments),
            partition_year=int(year) if year is not None else None,
        )

    def _tool_log_action(self, arguments: dict[str, Any]) -> Any:
        event_id = self.memory.log_action(
            self._subject(arguments),
            arguments["action_type"],
            arguments.get("payload") or {},
            session_id=arguments.get("session_id"),
            turn_id=arguments.get("turn_id"),
        )
        return {"event_id": event_id}

    def _tool_definitions(self) -> list[dict[str, Any]]:
        return [
            _tool(
                "memory_remember",
                "Store a message in auditable memory. Trusted user statements "
                "become active records; content from webpages/tool output is "
                "quarantined until explicitly promoted. Updates supersede "
                "older facts with the same slot instead of duplicating.",
                {
                    **_SUBJECT_PROPERTY,
                    "message": {"type": "string", "description": "The user message or fact."},
                    "source_type": {
                        "type": "string",
                        "enum": ["user_message", "webpage", "tool_output"],
                        "description": "Override source classification.",
                    },
                    **_SESSION_PROPERTIES,
                },
                required=["message"],
            ),
            _tool(
                "memory_recall",
                "Retrieve the most relevant active memories for a query "
                "(text relevance + trust + recency). Every recall is logged "
                "with a bounded score sample for auditability.",
                {
                    **_SUBJECT_PROPERTY,
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "min_score": {
                        "type": "number",
                        "description": "Drop matches scoring below this.",
                    },
                    "use_graph": {
                        "type": "boolean",
                        "description": "Blend bounded graph seed-and-spread recall.",
                    },
                    **_SESSION_PROPERTIES,
                },
                required=["query"],
            ),
            _tool(
                "memory_recall_block",
                "Build a bounded <relevant_memories> block for prompt "
                "injection: top matches only (lexical match required), hard "
                "record/char budgets, and an audit event naming exactly "
                "which record IDs entered the context.",
                {
                    **_SUBJECT_PROPERTY,
                    "query": {"type": "string"},
                    "max_records": {"type": "integer", "default": 5},
                    "max_chars": {"type": "integer", "default": 2000},
                    "min_score": {"type": "number", "default": 0.3},
                    "use_graph": {"type": "boolean"},
                    **_SESSION_PROPERTIES,
                },
                required=["query"],
            ),
            _tool(
                "memory_persona",
                "Deterministic persona snapshot (<user_persona> block) "
                "derived live from active records: stable fact slots first, "
                "then recent facts, under a character budget. Every line "
                "carries the source record id; building it is audited.",
                {
                    **_SUBJECT_PROPERTY,
                    "max_chars": {"type": "integer", "default": 1500},
                    **_SESSION_PROPERTIES,
                },
            ),
            _tool(
                "memory_capture",
                "Auto-capture a conversation event. role=user runs the full "
                "write pipeline; role=assistant/tool_call/tool_result are "
                "logged to the audit chain as digests and never become "
                "memory records.",
                {
                    **_SUBJECT_PROPERTY,
                    "role": {
                        "type": "string",
                        "enum": ["user", "assistant", "tool_call", "tool_result"],
                    },
                    "content": {"type": "string"},
                    "tool_name": {"type": "string"},
                    **_SESSION_PROPERTIES,
                },
                required=["role", "content"],
            ),
            _tool(
                "memory_list",
                "List a subject's records. include_inactive=true also shows "
                "superseded, quarantined, and tombstoned records.",
                {
                    **_SUBJECT_PROPERTY,
                    "include_inactive": {"type": "boolean", "default": False},
                },
            ),
            _tool(
                "memory_forget",
                "Delete matching memories: tombstone + purge content and the "
                "source episode. Returns a deletion receipt bound to the "
                "audit chain. Provide `contains` (substring) or `utterance` "
                '(e.g. "Forget my backup email.").',
                {
                    **_SUBJECT_PROPERTY,
                    "contains": {"type": "string"},
                    "utterance": {"type": "string"},
                    **_SESSION_PROPERTIES,
                },
            ),
            _tool(
                "memory_promote",
                "Activate a quarantined record and audit the trust transition. "
                "This tool does not authenticate confirmation; the host must "
                "show the record and enforce any required human approval.",
                {
                    **_SUBJECT_PROPERTY,
                    "record_id": {"type": "string"},
                    **_SESSION_PROPERTIES,
                },
                required=["record_id"],
            ),
            _tool(
                "memory_audit",
                "Return the hash-chained audit log, retrieval events, and "
                "whether the chain verifies.",
                {**_SUBJECT_PROPERTY},
            ),
            _tool(
                "memory_verify",
                "Verify audit-chain integrity, optionally against an "
                "anchored checkpoint file.",
                {
                    **_SUBJECT_PROPERTY,
                    "checkpoints_path": {"type": "string"},
                    "incremental": {"type": "boolean", "default": False},
                },
            ),
            _tool(
                "memory_graph_status",
                "Inspect derived graph entities, edges, merge proposals, and archives.",
                {**_SUBJECT_PROPERTY},
            ),
            _tool(
                "memory_graph_merges",
                "List entity merge proposals. Decisions require the reviewer HTTP or CLI surface.",
                {
                    **_SUBJECT_PROPERTY,
                    "status": {
                        "type": "string",
                        "enum": ["pending", "approved", "rejected", "reverted"],
                    },
                },
            ),
            _tool(
                "memory_graph_history",
                "Read digest-verified inactive graph edges from cold partitions.",
                {
                    **_SUBJECT_PROPERTY,
                    "partition_year": {"type": "integer"},
                },
            ),
            _tool(
                "memory_log_action",
                "Append an agent action event (tool call, decision, response "
                "shown) to the same audit chain as memory events. Put "
                "digests in the payload, not raw content.",
                {
                    **_SUBJECT_PROPERTY,
                    "action_type": {"type": "string", "description": 'e.g. "tool_call"'},
                    "payload": {"type": "object"},
                    **_SESSION_PROPERTIES,
                },
                required=["action_type"],
            ),
        ]


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
