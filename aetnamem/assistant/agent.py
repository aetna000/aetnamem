from __future__ import annotations

from dataclasses import dataclass
import json
import secrets
from typing import Any

from aetnamem.actions.policy import ActionPolicyViolation
from aetnamem.assistant.providers import AssistantProvider
from aetnamem.broker import AuthorityRef, BrokerContext, ToolBroker
from aetnamem.core.policy import is_forget_request
from aetnamem.memory import Memory


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
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or "tool" not in payload:
            return None
        tool = str(payload["tool"])
        arguments = payload.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        try:
            result = self.broker.dispatch(
                tool,
                arguments,
                BrokerContext(
                    subject_id=subject_id,
                    actor_id="assistant",
                    session_id=session_id,
                    authority=authority,
                    source_type="tool_output",
                    user_attested=tool == "memory_forget" and is_forget_request(user_message),
                ),
            )
        except ActionPolicyViolation as exc:
            return {"ok": False, "status": "refused", "message": str(exc)}
        return result.to_dict()


def _sha256_text(value: str) -> str:
    from aetnamem.core.canonical import sha256_hex

    return sha256_hex(value)
