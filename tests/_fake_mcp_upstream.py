"""A minimal fake upstream MCP server for gate tests.

Advertises one read-only tool (annotated) and one write tool (unannotated),
and echoes tools/call. Not a test module (leading underscore keeps pytest away).
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        if "id" not in msg:  # notification
            continue
        rid = msg["id"]
        if method == "initialize":
            out = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}
        elif method == "tools/list":
            out = {
                "tools": [
                    {
                        "name": "search",
                        "description": "Read-only search.",
                        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
                        "annotations": {"readOnlyHint": True},
                    },
                    {
                        "name": "delete_all",
                        "description": "Destructive write.",
                        "inputSchema": {"type": "object"},
                    },
                ]
            }
        elif method == "tools/call":
            params = msg.get("params") or {}
            out = {"content": [{"type": "text", "text": f"ran {params.get('name')}"}], "isError": False}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": out}), flush=True)


if __name__ == "__main__":
    main()
