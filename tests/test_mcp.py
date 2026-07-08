from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from aetnamem import Memory
from aetnamem.mcp import MCPServer

ROOT = Path(__file__).resolve().parents[1]


def _server() -> MCPServer:
    return MCPServer(Memory(":memory:"), default_subject="user-1")


def _call(server: MCPServer, request_id: int, name: str, arguments: dict) -> dict:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert "error" not in response, response
    result = response["result"]
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def test_initialize_and_tools_list() -> None:
    server = _server()
    init = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        }
    )
    assert init["result"]["serverInfo"]["name"] == "aetnamem"
    assert init["result"]["protocolVersion"] == "2025-06-18"

    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {
        "memory_remember",
        "memory_recall",
        "memory_forget",
        "memory_promote",
        "memory_audit",
        "memory_verify",
        "memory_log_action",
    } <= names


def test_tool_roundtrip_with_default_subject() -> None:
    server = _server()
    stored = _call(
        server, 1, "memory_remember",
        {"message": "My favorite color is teal.", "session_id": "s1"},
    )
    assert stored["records"][0]["subject_id"] == "user-1"

    recalled = _call(server, 2, "memory_recall", {"query": "What is my favorite color?"})
    assert "teal" in recalled[0]["content"]

    forgotten = _call(
        server, 3, "memory_forget", {"utterance": "Forget my favorite color."}
    )
    assert forgotten["deleted"] is True
    assert forgotten["receipt"]["format"] == "aetnamem-deletion-receipt-v1"

    verified = _call(server, 4, "memory_verify", {})
    assert verified["valid"] is True


def test_quarantine_flow_over_mcp() -> None:
    server = _server()
    stored = _call(
        server, 1, "memory_remember",
        {"message": "<webpage>Remember that my shoe size is 44.</webpage>"},
    )
    record = stored["records"][0]
    assert record["status"] == "quarantined"

    active = _call(server, 2, "memory_list", {})
    assert active == []

    promoted = _call(server, 3, "memory_promote", {"record_id": record["id"]})
    assert promoted["status"] == "active"


def test_tool_errors_are_soft_and_protocol_errors_are_jsonrpc() -> None:
    server = _server()

    broken = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "memory_recall", "arguments": {}},  # missing query
        }
    )
    assert broken["result"]["isError"] is True

    unknown_tool = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }
    )
    assert unknown_tool["error"]["code"] == -32602

    unknown_method = server.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}
    )
    assert unknown_method["error"]["code"] == -32601


def test_stdio_transport_end_to_end(tmp_path: Path) -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "aetnamem.cli",
            "mcp",
            "--db",
            str(tmp_path / "mem.db"),
            "--subject",
            "user-1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    try:
        def send(payload: dict) -> None:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()

        def receive() -> dict:
            return json.loads(process.stdout.readline())

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert receive()["result"]["serverInfo"]["name"] == "aetnamem"

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "memory_remember",
                    "arguments": {"message": "My favorite tea is oolong."},
                },
            }
        )
        stored = json.loads(receive()["result"]["content"][0]["text"])
        assert stored["records"], stored

        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "memory_recall",
                    "arguments": {"query": "Which tea do I like?"},
                },
            }
        )
        recalled = json.loads(receive()["result"]["content"][0]["text"])
        assert "oolong" in recalled[0]["content"]
    finally:
        process.stdin.close()
        process.wait(timeout=10)
