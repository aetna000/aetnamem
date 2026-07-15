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


class RememberNoteProvider:
    def complete(self, messages, tools):
        return '{"tool":"memory_remember","arguments":{"message":"i need to cook dinner"}}'


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


def test_assistant_memory_tool_saves_explicit_note(tmp_path: Path) -> None:
    memory, _, broker = build(tmp_path)
    loop = AssistantLoop(memory, broker, RememberNoteProvider())

    result = loop.chat(
        subject_id="u1",
        session_id="s1",
        message="remember i need to cook dinner",
    )

    assert result["tool_result"]["status"] == "executed"
    records = memory.list("u1")
    assert any(record["content"] == "I need to cook dinner." for record in records)
    memory.close()


class WrongArgsProvider:
    """Simulates a small model inventing an argument name."""

    def complete(self, messages, tools):
        return '{"tool":"memory_remember","arguments":{"fact":"weekly report lives in report.md"}}'


class UnknownToolProvider:
    def complete(self, messages, tools):
        return '{"tool":"make_coffee","arguments":{}}'


class ThinkingProvider:
    """Simulates a thinking model (qwen3) wrapping a fenced tool call."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return (
                "<think>The user wants me to remember this.</think>\n"
                '```json\n{"tool":"memory_remember","arguments":{"message":"report lives in report.md"}}\n```'
            )
        return "<think>done</think>Saved it."


def test_invented_argument_names_do_not_crash_chat(tmp_path: Path) -> None:
    memory, engine, broker = build(tmp_path)
    loop = AssistantLoop(memory, broker, WrongArgsProvider())

    result = loop.chat(subject_id="u1", session_id="s1", message="Remember my report file.")

    assert result["tool_result"]["ok"] is False
    assert result["tool_result"]["status"] == "invalid_arguments"
    memory.close()


def test_unknown_tool_does_not_crash_chat(tmp_path: Path) -> None:
    memory, engine, broker = build(tmp_path)
    loop = AssistantLoop(memory, broker, UnknownToolProvider())

    result = loop.chat(subject_id="u1", session_id="s1", message="Make me a coffee.")

    assert result["tool_result"]["status"] == "unknown_tool"
    memory.close()


def test_think_blocks_and_fences_are_handled(tmp_path: Path) -> None:
    memory, engine, broker = build(tmp_path)
    loop = AssistantLoop(memory, broker, ThinkingProvider())

    result = loop.chat(subject_id="u1", session_id="s1", message="Remember: report lives in report.md.")

    assert result["tool_result"]["status"] == "executed"
    assert "<think>" not in result["reply"]
    assert result["reply"] == "Saved it."
    memory.close()
