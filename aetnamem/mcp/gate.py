"""MCP enforcement gate: a spawn-and-forward proxy that removes direct write
tools from an upstream MCP server.

The gate speaks MCP to a host (Claude Desktop, OpenClaw, Claude Code) and
forwards to one upstream MCP tool server it launches as a child process. Under
enforcement it publishes only the tools it can vouch for as safe:

* **read-only** tools pass through unchanged;
* **blocked** (mutating) tools are removed from ``tools/list`` and refused on
  ``tools/call`` with a message telling the agent the effect must be staged as
  a guarded action and approved by a human.

Classification is explicit config plus a default: a tool is treated as
read-only only when the config says so or the upstream advertises MCP's
``annotations.readOnlyHint: true``. Everything else is blocked by default, so a
newly-added upstream write tool fails closed rather than leaking through.

This is the enforcement chokepoint for *external* hosts. The in-process
:class:`~aetnamem.broker.ToolBroker` is the equivalent for the app's own
assistant loop; both refuse to let an unapproved effect reach the world.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
import sys
import threading
from typing import Any, TextIO

from aetnamem import Memory
from aetnamem.core.canonical import canonical_json, sha256_hex

PROTOCOL_VERSION = "2025-06-18"
GATE_VERSION = "0"


@dataclass
class GatePolicy:
    """Which upstream tools the gate is willing to expose."""

    read_only: frozenset[str] = frozenset()
    #: Explicitly blocked even if they look read-only.
    blocked: frozenset[str] = frozenset()
    #: When True (default), unknown tools are blocked unless the upstream marks
    #: them read-only and ``allow_readonly_hint`` is enabled. When False, unknown
    #: tools pass through (audit-only mode).
    default_block: bool = True
    #: MCP readOnlyHint is upstream-supplied and advisory. Keep it off for
    #: enforcement; enable only when the upstream manifest is separately trusted.
    allow_readonly_hint: bool = False

    def verdict(self, name: str, annotations: dict[str, Any] | None) -> str:
        if name in self.blocked:
            return "blocked"
        if name in self.read_only:
            return "read_only"
        if self.allow_readonly_hint and annotations and annotations.get("readOnlyHint") is True:
            return "read_only"
        return "blocked" if self.default_block else "read_only"


class UpstreamClient:
    """Minimal stdio MCP client that launches and drives one upstream server."""

    def __init__(self, command: list[str]) -> None:
        self._command = command
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}})
        self.notify("notifications/initialized", {})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("upstream MCP server is not running")
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            self._proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self._proc.stdin.flush()
            # Read until we see the response with our id (skip notifications).
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    raise RuntimeError("upstream MCP server closed the connection")
                line = line.strip()
                if not line:
                    continue
                reply = json.loads(line)
                if reply.get("id") == request_id:
                    return reply

    def notify(self, method: str, params: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        with self._lock:
            self._proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, separators=(",", ":")) + "\n"
            )
            self._proc.stdin.flush()

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


class McpGate:
    """Host-facing MCP server that filters an upstream server's tools."""

    def __init__(
        self,
        upstream: UpstreamClient,
        policy: GatePolicy,
        *,
        audit_memory: Memory | None = None,
        audit_subject: str = "default",
        audit_actor: str = "mcp-gate",
    ) -> None:
        self.upstream = upstream
        self.policy = policy
        self._verdicts: dict[str, str] = {}
        self.audit_memory = audit_memory
        self.audit_subject = audit_subject
        self.audit_actor = audit_actor

    # -- transport (mirrors aetnamem.mcp.server framing) ----------------------

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        self.upstream.start()
        try:
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
        finally:
            self.upstream.stop()

    @staticmethod
    def _write(stdout: TextIO, message: dict[str, Any]) -> None:
        stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
        stdout.flush()

    # -- protocol -------------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if not isinstance(method, str) or "id" not in message:
            return None
        try:
            if method == "initialize":
                params = message.get("params") or {}
                return _result(
                    request_id,
                    {
                        "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "aetnamem-gate", "version": GATE_VERSION},
                    },
                )
            if method == "ping":
                return _result(request_id, {})
            if method == "tools/list":
                return _result(request_id, {"tools": self._filtered_tools()})
            if method == "tools/call":
                params = message.get("params") or {}
                return self._call(request_id, params.get("name", ""), params.get("arguments") or {})
            return _error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:  # protocol survives upstream/tool bugs
            print(f"aetnamem-gate error: {exc!r}", file=sys.stderr)
            return _error(request_id, -32603, str(exc))

    def _filtered_tools(self) -> list[dict[str, Any]]:
        reply = self.upstream.request("tools/list", {})
        tools = (reply.get("result") or {}).get("tools") or []
        allowed: list[dict[str, Any]] = []
        self._verdicts = {}
        for tool in tools:
            name = tool.get("name", "")
            verdict = self.policy.verdict(name, tool.get("annotations"))
            self._verdicts[name] = verdict
            if verdict == "read_only":
                allowed.append(tool)
        return allowed

    def _call(self, request_id: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Refresh verdicts if the host calls before listing.
        if name not in self._verdicts:
            self._filtered_tools()
        verdict = self._verdicts.get(name, "blocked")
        if verdict != "read_only":
            self._audit("tool.blocked", name, arguments, {"reason": "not_explicitly_allowed"})
            return _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"'{name}' is a write tool disabled under aetnamem "
                                "enforcement. This effect must be staged as a guarded "
                                "action and approved by a human before it can run."
                            ),
                        }
                    ],
                    "isError": True,
                },
            )
        reply = self.upstream.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in reply:
            self._audit("tool.error", name, arguments, reply["error"])
            return _error(request_id, -32603, str(reply["error"]))
        self._audit("tool.read", name, arguments, reply.get("result") or {})
        return _result(request_id, reply.get("result") or {})

    def _audit(self, event_type: str, name: str, arguments: dict[str, Any], result: Any) -> None:
        if self.audit_memory is None:
            return
        self.audit_memory.log_action(
            self.audit_subject,
            event_type,
            payload={
                "tool": name,
                "arguments_digest": sha256_hex(canonical_json(arguments)),
                "result_digest": sha256_hex(canonical_json(result)),
            },
            actor=self.audit_actor,
        )


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main(argv: list[str] | None = None) -> None:
    """Run the gate over stdio in front of an upstream MCP server.

    Configure an MCP host to launch, e.g.::

        python -m aetnamem.mcp.gate --read-only search,list -- python upstream.py
    """
    import argparse

    parser = argparse.ArgumentParser(prog="aetnamem-mcp-gate")
    parser.add_argument("--read-only", default="", help="comma-separated tool names to pass through")
    parser.add_argument("--blocked", default="", help="comma-separated tool names to always block")
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="pass through tools not explicitly classified (audit-only; NOT enforcement)",
    )
    parser.add_argument(
        "--trust-readonly-hint",
        action="store_true",
        help="allow upstream readOnlyHint to pass tools through (only for trusted manifests)",
    )
    parser.add_argument("--audit-db", default="", help="optional aetnamem DB for gate audit events")
    parser.add_argument("--audit-subject", default="default", help="subject id for optional gate audit events")
    parser.add_argument("upstream", nargs=argparse.REMAINDER, help="-- then the upstream server command")
    args = parser.parse_args(argv)

    command = args.upstream[1:] if args.upstream and args.upstream[0] == "--" else args.upstream
    if not command:
        parser.error("provide the upstream server command after --")

    policy = GatePolicy(
        read_only=frozenset(t for t in args.read_only.split(",") if t),
        blocked=frozenset(t for t in args.blocked.split(",") if t),
        default_block=not args.allow_unknown,
        allow_readonly_hint=args.trust_readonly_hint,
    )
    audit_memory = Memory(args.audit_db) if args.audit_db else None
    try:
        McpGate(
            UpstreamClient(command),
            policy,
            audit_memory=audit_memory,
            audit_subject=args.audit_subject,
        ).serve()
    finally:
        if audit_memory is not None:
            audit_memory.close()


if __name__ == "__main__":
    main()
