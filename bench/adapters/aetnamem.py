from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from memorybench.adapters.base import MemoryStackAdapter
from memorybench.adapters.mem0 import answer_from_records


class AetnamemAdapter(MemoryStackAdapter):
    """aetnamem embedded SQLite adapter."""

    capabilities = {
        "inspect_memory": True,
        "delete_memory": True,
        "retrieval_log": True,
        "multi_user": True,
        "multi_tenant": False,
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._load_local_package()

        from aetnamem import Memory

        self._root_dir = Path(
            self.config.get("data_dir")
            or tempfile.mkdtemp(prefix="memorystackbench-aetnamem-")
        )
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root_dir / "aetnamem.sqlite"
        self._memory = Memory(self._db_path)
        self._turn_counts: dict[tuple[str, str], int] = {}

    def reset_subject(self, subject_id: str) -> None:
        self._memory.reset_subject(subject_id)
        for key in list(self._turn_counts):
            if key[0] == subject_id:
                del self._turn_counts[key]

    def send(self, subject_id: str, session_id: str, message: str) -> str:
        from aetnamem.extract import classify_source, is_forget_request

        turn_id = self._next_turn_id(subject_id, session_id)
        if is_forget_request(message):
            result = self._memory.forget(
                subject_id,
                utterance=message,
                session_id=session_id,
                turn_id=turn_id,
            )
            return "I deleted matching memories." if result["deleted"] else "I did not find matching memories to delete."

        source_type = classify_source(message)
        result = self._memory.remember(
            subject_id,
            message,
            session_id=session_id,
            turn_id=turn_id,
            source_type=source_type,
        )

        if result["records"] or source_type != "user_message":
            return "Acknowledged."

        retrieved = self._memory.recall(subject_id, message, session_id=session_id)
        return answer_from_records(message, retrieved)

    def inspect_memory(self, subject_id: str) -> list[dict[str, Any]]:
        return self._memory.list(subject_id)

    def delete_memory(self, subject_id: str, selector: dict[str, Any]) -> bool:
        return bool(self._memory.forget(subject_id, selector=selector)["deleted"])

    def get_retrieval_log(self, subject_id: str, session_id: str) -> list[dict[str, Any]]:
        active_by_id = {
            record["memory_id"]: record
            for record in self._memory.list(subject_id)
        }
        events: list[dict[str, Any]] = []
        for event in self._memory.get_retrieval_log(subject_id, session_id=session_id):
            ids = list(event.get("memory_ids") or event.get("returned_ids") or [])
            enriched = dict(event)
            enriched["memory_ids"] = ids
            enriched["records"] = [
                active_by_id[memory_id]
                for memory_id in ids
                if memory_id in active_by_id
            ]
            events.append(enriched)
        return events

    def close(self) -> None:
        self._memory.close()
        if not self.config.get("keep_data") and not self.config.get("data_dir"):
            shutil.rmtree(self._root_dir, ignore_errors=True)

    def _next_turn_id(self, subject_id: str, session_id: str) -> int:
        key = (subject_id, session_id)
        self._turn_counts[key] = self._turn_counts.get(key, 0) + 1
        return self._turn_counts[key]

    def _load_local_package(self) -> None:
        package_path = self.config.get("package_path")
        if package_path:
            path = Path(package_path).expanduser().resolve()
        else:
            path = Path(__file__).resolve().parents[3] / "aetnamem"
        if path.exists():
            sys.path.insert(0, str(path))
