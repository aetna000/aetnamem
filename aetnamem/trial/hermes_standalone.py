"""Self-contained Hermes Safe Switch loader.

This file is copied into Hermes' plugin directory. Keep it standard-library
only: Hermes may run in a pipx/uv environment that cannot import the Python
environment containing the `aetnamem` executable.
"""

from __future__ import annotations

import atexit
import json
from pathlib import Path
import subprocess
import threading
from typing import Any


_CONFIG = Path(__file__).with_name(".aetnamem-config.json")
_LOCK = threading.Lock()
_PROCESS: subprocess.Popen[str] | None = None
_NEXT_ID = 1
_PENDING_EXPOSURES: dict[str, str] = {}


def _configuration() -> dict[str, str]:
    value = json.loads(_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid AetnaMem Hermes plugin configuration")
    return {
        "command": str(value["command"]),
        "state_path": str(value["state_path"]),
    }


def _start() -> subprocess.Popen[str]:
    global _PROCESS
    if _PROCESS is not None and _PROCESS.poll() is None:
        return _PROCESS
    config = _configuration()
    process = subprocess.Popen(
        [
            config["command"],
            "trial",
            "mcp",
            "--state",
            config["state_path"],
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    _PROCESS = process
    _request(
        process,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "hermes-aetnamem-safe-switch",
                "version": "0.1.0",
            },
        },
    )
    assert process.stdin is not None
    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
        + "\n"
    )
    process.stdin.flush()
    return process


def _request(
    process: subprocess.Popen[str], method: str, params: dict[str, Any]
) -> Any:
    global _NEXT_ID
    assert process.stdin is not None
    assert process.stdout is not None
    request_id = _NEXT_ID
    _NEXT_ID += 1
    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("AetnaMem trial subprocess exited")
    response = json.loads(line)
    if response.get("id") != request_id:
        raise RuntimeError("AetnaMem trial response id mismatch")
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or "RPC error"))
    return response.get("result")


def _call(name: str, arguments: dict[str, Any]) -> Any:
    with _LOCK:
        process = _start()
        result = _request(
            process,
            "tools/call",
            {"name": name, "arguments": arguments},
        )
    blocks = result.get("content", []) if isinstance(result, dict) else []
    text = blocks[0].get("text", "") if blocks else ""
    if result.get("isError"):
        raise RuntimeError(text)
    return json.loads(text) if text else None


def before_llm(
    session_id: str,
    user_message: str,
    **kwargs: Any,
) -> dict[str, str] | None:
    del kwargs
    try:
        prepared = _call(
            "trial_prepare",
            {"query": user_message or "", "session_id": session_id},
        )
        exposure_id = prepared.get("exposure_id")
        if exposure_id:
            _PENDING_EXPOSURES[session_id] = str(exposure_id)
        context = str(prepared.get("context") or "")
        if prepared.get("inject") and context:
            return {"context": context}
    except Exception:
        return None
    return None


def after_llm(
    session_id: str,
    user_message: str,
    **kwargs: Any,
) -> None:
    del kwargs
    try:
        exposure_id = _PENDING_EXPOSURES.pop(session_id, None)
        if exposure_id:
            _call("trial_exposure_shown", {"exposure_id": exposure_id})
        if user_message:
            _call(
                "trial_capture",
                {
                    "message": user_message,
                    "session_id": session_id,
                    "authenticated_user": True,
                },
            )
    except Exception:
        return


def close(**kwargs: Any) -> None:
    del kwargs
    global _PROCESS
    with _LOCK:
        process = _PROCESS
        _PROCESS = None
        if process is not None and process.poll() is None:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()


def register(ctx: Any) -> None:
    ctx.register_hook("pre_llm_call", before_llm)
    ctx.register_hook("post_llm_call", after_llm)
    ctx.register_hook("on_session_finalize", close)


atexit.register(close)
