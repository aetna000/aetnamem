"""Private memory control plane protocol used by host integrations.

This is intentionally a separate MCP server from the agent-facing memory
tools. It exposes only host-side mirror/capture, preview preparation, exposure
confirmation, and status. The host plugin calls it; the agent cannot promote
candidate memories or change migration mode.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, TextIO

from aetnamem.mcp.server import PROTOCOL_VERSION, SERVER_VERSION
from aetnamem.control.manager import ControlPlaneManager


class ControlMCPServer:
    def __init__(self, manager: ControlPlaneManager) -> None:
        self.manager = manager

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                response = self.handle(message)
            except Exception as exc:
                response = _error(None, -32700, str(exc))
            if response is not None:
                stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                stdout.flush()

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if "id" not in message:
            return None
        request_id = message.get("id")
        method = message.get("method")
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
                            "name": "aetnamem-control-plane",
                            "version": SERVER_VERSION,
                        },
                    },
                )
            if method == "ping":
                return _result(request_id, {})
            if method == "tools/list":
                return _result(request_id, {"tools": _tools()})
            if method == "tools/call":
                params = message.get("params") or {}
                return _result(
                    request_id,
                    self._call(
                        str(params.get("name") or ""),
                        params.get("arguments") or {},
                    ),
                )
            return _error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            )

    def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "control_capture":
            value = self.manager.capture(
                str(arguments["message"]),
                session_id=arguments.get("session_id"),
                authenticated_user=bool(arguments.get("authenticated_user", False)),
            )
        elif name == "control_sync_openclaw_memory":
            state = self.manager.state()
            if state.host != "openclaw":
                raise ValueError("native memory sync is available only for OpenClaw")
            from aetnamem.control.openclaw_native import (
                MIRROR_MANIFEST_NAME,
                mirror_status,
            )

            if not (Path(state.control_dir) / MIRROR_MANIFEST_NAME).is_file():
                raise ValueError(
                    "the OpenClaw mirror has not been initialized; run "
                    "`aetnamem openclaw install` or refresh it from the dashboard"
                )
            value = mirror_status(state, refresh=True)
            if not value.get("synced"):
                raise ValueError(
                    "the OpenClaw mirror has not been initialized; run "
                    "`aetnamem openclaw install` or refresh it from the dashboard"
                )
        elif name == "control_prepare":
            value = self.manager.prepare(
                str(arguments["query"]),
                session_id=arguments.get("session_id"),
                host_run_id=arguments.get("host_run_id"),
            )
        elif name == "control_exposure_shown":
            value = {
                "confirmed": self.manager.confirm_exposure(
                    str(arguments["exposure_id"])
                )
            }
        elif name == "control_status":
            value = self.manager.status()
        else:
            raise ValueError(f"unknown migration tool: {name}")
        return {
            "content": [
                {"type": "text", "text": json.dumps(value, indent=2, sort_keys=True)}
            ],
            "isError": False,
        }


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "control_capture",
            "description": "Capture candidate facts from an authenticated user turn.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "session_id": {"type": "string"},
                    "authenticated_user": {"type": "boolean"},
                },
                "required": ["message", "authenticated_user"],
                "additionalProperties": False,
            },
        },
        {
            "name": "control_sync_openclaw_memory",
            "description": "Refresh the isolated mirror from OpenClaw's native memory files without reading the conversation transcript.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "control_prepare",
            "description": "Build a preview and inject it only when migration mode permits.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "session_id": {"type": "string"},
                    "host_run_id": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "control_exposure_shown",
            "description": "Confirm that the host placed one requested context exposure.",
            "inputSchema": {
                "type": "object",
                "properties": {"exposure_id": {"type": "string"}},
                "required": ["exposure_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "control_status",
            "description": "Read fail-closed migration status and evidence counts.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
