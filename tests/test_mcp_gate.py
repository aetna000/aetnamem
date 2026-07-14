from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aetnamem.mcp.gate import GatePolicy, McpGate, UpstreamClient

FAKE = str(Path(__file__).parent / "_fake_mcp_upstream.py")


@pytest.fixture
def gate():
    upstream = UpstreamClient([sys.executable, FAKE])
    upstream.start()
    g = McpGate(upstream, GatePolicy(read_only=frozenset({"search"})))  # explicit allowlist
    yield g
    upstream.stop()


def test_list_hides_write_tools(gate):
    tools = gate.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "search" in names          # read-only annotation → passes through
    assert "delete_all" not in names  # unannotated write → removed


def test_calling_a_blocked_tool_is_refused(gate):
    gate.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    reply = gate.handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "delete_all", "arguments": {}},
    })
    assert reply["result"]["isError"] is True
    assert "disabled under aetnamem enforcement" in reply["result"]["content"][0]["text"]


def test_read_only_tool_forwards(gate):
    gate.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    reply = gate.handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "search", "arguments": {"q": "hi"}},
    })
    assert reply["result"]["isError"] is False
    assert reply["result"]["content"][0]["text"] == "ran search"


def test_call_before_list_still_blocks(gate):
    reply = gate.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "delete_all", "arguments": {}},
    })
    assert reply["result"]["isError"] is True


def test_explicit_block_overrides_readonly_hint():
    upstream = UpstreamClient([sys.executable, FAKE])
    upstream.start()
    try:
        gate = McpGate(
            upstream,
            GatePolicy(read_only=frozenset({"search"}), blocked=frozenset({"search"})),
        )
        tools = gate.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        assert {t["name"] for t in tools} == set()  # even the read-only tool is blocked
    finally:
        upstream.stop()


def test_readonly_hint_is_not_trusted_by_default():
    upstream = UpstreamClient([sys.executable, FAKE])
    upstream.start()
    try:
        gate = McpGate(upstream, GatePolicy())
        tools = gate.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        assert {t["name"] for t in tools} == set()
    finally:
        upstream.stop()


def test_readonly_hint_can_be_enabled_for_trusted_manifests():
    upstream = UpstreamClient([sys.executable, FAKE])
    upstream.start()
    try:
        gate = McpGate(upstream, GatePolicy(allow_readonly_hint=True))
        tools = gate.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        assert {t["name"] for t in tools} == {"search"}
    finally:
        upstream.stop()
