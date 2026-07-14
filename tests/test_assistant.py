from __future__ import annotations

from pathlib import Path

from aetnamem import Memory
from aetnamem.actions import ActionEngine, ApprovalAuthority, FilesystemAdapter
from aetnamem.assistant import AssistantLoop
from aetnamem.broker import ToolBroker


class ToolCallingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return '{"tool":"write_file","arguments":{"path":"report.md","content":"# Weekly\\n"}}'
        return "I staged the report write for approval."


class ForgetProvider:
    def complete(self, messages, tools):
        return '{"tool":"memory_forget","arguments":{"utterance":"Forget my report file."}}'


def build(tmp_path: Path):
    memory = Memory(tmp_path / "mem.db")
    (tmp_path / "workspace").mkdir()
    engine = ActionEngine(
        memory,
        adapters=[FilesystemAdapter(tmp_path / "workspace")],
        approval_authority=ApprovalAuthority("approval-secret-that-is-at-least-32-bytes-long"),
    )
    broker = ToolBroker(engine)
    broker.register_default_memory_tools()
    broker.register_guarded(
        "write_file",
        "Write UTF-8 text to a file in the workspace.",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
        adapter="filesystem",
        operation="write_text",
    )
    return memory, engine, broker


def test_assistant_captures_user_message_and_stages_write(tmp_path: Path) -> None:
    memory, engine, broker = build(tmp_path)
    loop = AssistantLoop(memory, broker, ToolCallingProvider())

    result = loop.chat(
        subject_id="u1",
        session_id="s1",
        message="Write my weekly report to report.md.",
    )

    assert result["reply"] == "I staged the report write for approval."
    assert result["tool_result"]["status"] == "awaiting_approval"
    assert engine.list("u1")[0]["state"] == "awaiting_approval"
    assert not (tmp_path / "workspace" / "report.md").exists()
    episodes = memory.store.list_episodes("u1")
    assert episodes and episodes[0]["source_type"] == "user_message"
    memory.close()


def test_assistant_allows_forget_only_from_user_forget_request(tmp_path: Path) -> None:
    memory, _, broker = build(tmp_path)
    memory.remember("u1", "My report file is report.md.", source_type="user_message")
    loop = AssistantLoop(memory, broker, ForgetProvider())

    result = loop.chat(
        subject_id="u1",
        session_id="s1",
        message="Forget my report file.",
    )

    assert result["tool_result"]["status"] == "executed"
    assert memory.recall("u1", "report file") == []
    memory.close()
