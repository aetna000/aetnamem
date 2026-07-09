#!/usr/bin/env python3
"""Grok/xAI tool-calling playground for aetnamem.

This uses the xAI Responses API with custom function tools. Grok chooses
when to call memory tools; this script executes those calls locally against
the same aetnamem engine used by Python, CLI, MCP, and OpenClaw.

No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aetnamem import Memory

API_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = os.environ.get("AETNAMEM_GROK_MODEL", "grok-4.5")
DEFAULT_DB = os.environ.get(
    "AETNAMEM_GROK_DB", str(Path.home() / ".aetnamem" / "grok-playground.db")
)
DEFAULT_SUBJECT = os.environ.get("AETNAMEM_GROK_SUBJECT", "grok-demo")
DEFAULT_PROMPT = (
    "Remember that my preferred editor is Zed. Then tell me what editor you "
    "should assume I use. Finally forget my preferred editor and explain what "
    "the deletion receipt proves."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "aetnamem_capture",
        "description": (
            "Capture a user-stated durable fact or preference into auditable "
            "long-term memory. Use only for facts the user directly states."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The user's fact or preference."},
                "session_id": {"type": "string", "description": "Conversation/session id."},
            },
            "required": ["content"],
        },
    },
    {
        "type": "function",
        "name": "aetnamem_search",
        "description": "Search active auditable memory records.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to recall."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "session_id": {"type": "string", "description": "Conversation/session id."},
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "aetnamem_forget",
        "description": (
            "Delete matching memories only when the user explicitly asks to "
            "forget/remove/delete something. Returns a deletion receipt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "utterance": {"type": "string", "description": "The user's forget request."},
                "session_id": {"type": "string", "description": "Conversation/session id."},
                "turn_id": {"type": "string", "description": "Turn id."},
            },
            "required": ["utterance"],
        },
    },
    {
        "type": "function",
        "name": "aetnamem_audit",
        "description": "Return audit-chain status and recent audit event metadata.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--subject", default=DEFAULT_SUBJECT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Exercise the local memory tools without calling xAI.",
    )
    args = parser.parse_args()

    memory = Memory(args.db)
    if args.dry_run:
        dry_run(memory, args.subject)
        return

    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise SystemExit("Set XAI_API_KEY, or run with --dry-run.")

    prompt = (
        "You are Grok using aetnamem as auditable long-term memory. "
        "Use memory tools when the user asks you to remember, recall, forget, "
        "or prove memory behavior. Do not invent receipts; call the tool.\n\n"
        f"User: {args.prompt}"
    )
    response = xai_request(
        api_key,
        {
            "model": args.model,
            "input": [{"role": "user", "content": prompt}],
            "tools": TOOLS,
            "parallel_tool_calls": False,
        },
    )

    for step in range(args.max_steps):
        calls = list(function_calls(response))
        if not calls:
            break

        outputs = []
        for call in calls:
            name = str(call.get("name"))
            call_id = str(call.get("call_id"))
            arguments = json.loads(str(call.get("arguments") or "{}"))
            print(f"tool[{step + 1}]: {name}({json.dumps(arguments, sort_keys=True)})")
            result = dispatch_tool(memory, args.subject, name, arguments)
            print(json.dumps(redact_for_console(result), indent=2, sort_keys=True))
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, sort_keys=True),
                }
            )

        response = xai_request(
            api_key,
            {
                "model": args.model,
                "input": outputs,
                "tools": TOOLS,
                "previous_response_id": response["id"],
                "parallel_tool_calls": False,
            },
        )

    print("\nfinal:")
    print(extract_text(response) or json.dumps(response, indent=2, sort_keys=True))
    print(f"\ndatabase: {args.db}")


def xai_request(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"xAI API error {error.code}: {body}") from error


def function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in response.get("output", [])
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]


def extract_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def dispatch_tool(
    memory: Memory, subject_id: str, name: str, args: dict[str, Any]
) -> dict[str, Any] | list[dict[str, Any]]:
    if name == "aetnamem_capture":
        return memory.capture(
            subject_id,
            "user",
            str(args["content"]),
            session_id=args.get("session_id") or "grok-playground",
        )
    if name == "aetnamem_search":
        return memory.recall(
            subject_id,
            str(args["query"]),
            session_id=args.get("session_id") or "grok-playground",
            limit=max(1, min(int(args.get("limit", 5)), 20)),
        )
    if name == "aetnamem_forget":
        return memory.forget(
            subject_id,
            utterance=str(args["utterance"]),
            session_id=args.get("session_id") or "grok-playground",
            turn_id=args.get("turn_id"),
        )
    if name == "aetnamem_audit":
        audit = memory.audit(subject_id)
        return {
            "audit_chain_valid": audit["audit_chain_valid"],
            "audit_event_count": len(audit["audit_log"]),
            "retrieval_event_count": len(audit["retrieval_events"]),
            "recent_event_types": [
                event["event_type"] for event in audit["audit_log"][-8:]
            ],
        }
    return {"error": f"unknown tool: {name}"}


def redact_for_console(value: Any) -> Any:
    """Keep demo output compact while preserving receipts and ids."""
    if isinstance(value, list):
        return [redact_for_console(item) for item in value[:5]]
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if "records" in result:
        result["records"] = [
            {"id": record.get("id"), "status": record.get("status"), "content": record.get("content")}
            for record in result.get("records", [])
        ]
    return result


def dry_run(memory: Memory, subject_id: str) -> None:
    session_id = "grok-dry-run"
    print("capture:")
    print(
        json.dumps(
            dispatch_tool(
                memory,
                subject_id,
                "aetnamem_capture",
                {"content": "My preferred editor is Zed.", "session_id": session_id},
            ),
            indent=2,
            sort_keys=True,
        )
    )
    print("\nsearch:")
    print(
        json.dumps(
            dispatch_tool(
                memory,
                subject_id,
                "aetnamem_search",
                {"query": "preferred editor", "session_id": session_id},
            ),
            indent=2,
            sort_keys=True,
        )
    )
    print("\nforget:")
    print(
        json.dumps(
            dispatch_tool(
                memory,
                subject_id,
                "aetnamem_forget",
                {"utterance": "Forget my preferred editor.", "session_id": session_id},
            ),
            indent=2,
            sort_keys=True,
        )
    )
    print("\naudit:")
    print(
        json.dumps(
            dispatch_tool(memory, subject_id, "aetnamem_audit", {}),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
