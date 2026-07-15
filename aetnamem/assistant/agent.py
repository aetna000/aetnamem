from __future__ import annotations

from dataclasses import dataclass
import json
import re
import secrets
from typing import Any

from aetnamem.actions.policy import ActionPolicyViolation
from aetnamem.assistant.providers import AssistantProvider
from aetnamem.broker import AuthorityRef, BrokerContext, ToolBroker, UnknownToolError
from aetnamem.core.policy import is_forget_request
from aetnamem.memory import Memory

# Thinking models (e.g. qwen3) interleave <think> blocks with the reply, and
# most models like wrapping tool-call JSON in markdown fences.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?|\n?```\s*$")


def _clean_reply(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def _unfence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def _is_tool_call(text: str) -> bool:
    try:
        payload = json.loads(_unfence(text))
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and "tool" in payload


def _summary_for(tool_result: dict[str, Any]) -> str:
    status = tool_result.get("status")
    if status == "awaiting_approval":
        return "I've staged that action — it's waiting for your approval."
    if status == "executed":
        return "Done."
    message = tool_result.get("message") or status or "the tool call failed"
    return f"I couldn't complete that: {message}"


@dataclass
class AssistantLoop:
    memory: Memory
    broker: ToolBroker
    provider: AssistantProvider

    def chat(
        self,
        *,
        subject_id: str,
        message: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not message.strip():
            raise ValueError("message is required")

        self.memory.remember(
            subject_id,
            message,
            session_id=session_id,
            source_type="user_message",
            actor="user",
        )
        authority = AuthorityRef.from_task(f"task_{secrets.token_hex(12)}", message)
        memories = self.memory.recall(subject_id, message, session_id=session_id, limit=6)
        tools = self.broker.list_tools()

        assistant_text = self.provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a local desktop assistant. Use aetnamem tools for memory "
                        "or effects. Write/delete effects are only staged for human approval."
                    ),
                },
                {
                    "role": "system",
                    "content": "Relevant memory:\n" + json.dumps(memories, sort_keys=True),
                },
                {"role": "user", "content": message},
            ],
            tools,
        )
        assistant_text = _clean_reply(assistant_text)
        tool_result = self._maybe_call_tool(
            assistant_text,
            subject_id=subject_id,
            session_id=session_id,
            authority=authority,
            user_message=message,
        )
        if tool_result is not None:
            followup = self.provider.complete(
                [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": assistant_text},
                    {
                        "role": "system",
                        "content": "Tool result:\n" + json.dumps(tool_result, sort_keys=True),
                    },
                ],
                tools,
            )
            followup = _clean_reply(followup)
            # Small models often just repeat the tool call instead of
            # summarizing; only the first call per turn is dispatched, so
            # narrate the outcome deterministically instead.
            if not followup or _is_tool_call(followup):
                followup = _summary_for(tool_result)
            assistant_text = followup

        self.memory.log_action(
            subject_id,
            "assistant.reply",
            payload={
                "reply_sha256": _sha256_text(assistant_text),
                "tool_status": tool_result.get("status") if tool_result else None,
            },
            session_id=session_id,
            actor="assistant",
        )
        return {
            "reply": assistant_text,
            "memories": memories,
            "tool_result": tool_result,
        }

    def _maybe_call_tool(
        self,
        text: str,
        *,
        subject_id: str,
        session_id: str | None,
        authority: AuthorityRef,
        user_message: str,
    ) -> dict[str, Any] | None:
        try:
            payload = json.loads(_unfence(text))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or "tool" not in payload:
            return None
        tool = str(payload["tool"])
        arguments = payload.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {
                "ok": False,
                "status": "invalid_arguments",
                "message": "tool arguments must be a JSON object",
            }
        try:
            result = self.broker.dispatch(
                tool,
                arguments,
                BrokerContext(
                    subject_id=subject_id,
                    actor_id="assistant",
                    session_id=session_id,
                    authority=authority,
                    source_type="user_message" if tool == "memory_remember" else "tool_output",
                    user_attested=(
                        tool == "memory_remember"
                        or (tool == "memory_forget" and is_forget_request(user_message))
                    ),
                ),
            )
        except UnknownToolError:
            return {"ok": False, "status": "unknown_tool", "message": f"unknown tool: {tool}"}
        except ActionPolicyViolation as exc:
            return {"ok": False, "status": "refused", "message": str(exc)}
        except ValueError as exc:
            return {"ok": False, "status": "refused", "message": str(exc)}
        return result.to_dict()


def _sha256_text(value: str) -> str:
    from aetnamem.core.canonical import sha256_hex

    return sha256_hex(value)
