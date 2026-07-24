from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
from typing import Sequence

import pytest

from aetnamem import Memory
from aetnamem.investigate import search_evidence, trace_evidence
from aetnamem.semantic import (
    OllamaEmbedder,
    OpenAICompatibleEmbedder,
    SemanticIndex,
)


ROOT = Path(__file__).resolve().parents[1]


class ConceptEmbedder:
    @property
    def identity(self) -> dict:
        return {
            "provider": "test",
            "model": "concepts",
            "version": "1",
            "normalization": "l2",
        }

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        if any(word in lowered for word in ("airport", "sydney", "departure", "flight")):
            return [1.0, 0.0, 0.0]
        if any(word in lowered for word in ("color", "teal", "paint")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


class EmbeddingHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict, str | None]] = []
    digest = "sha256:" + ("a" * 64)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.requests.append(
            (self.path, payload, self.headers.get("Authorization"))
        )
        if self.path == "/api/embed":
            body = {"embeddings": [[3.0, 4.0] for _ in payload["input"]]}
        elif self.path == "/v1/embeddings":
            body = {
                "data": [
                    {"index": index, "embedding": [float(index + 1), 1.0]}
                    for index, _ in reversed(list(enumerate(payload["input"])))
                ]
            }
        else:
            self.send_error(404)
            return
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/tags":
            self.send_error(404)
            return
        encoded = json.dumps(
            {
                "models": [
                    {
                        "name": "embed-model:latest",
                        "model": "embed-model:latest",
                        "digest": self.digest,
                    }
                ]
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_http_embedding_adapters_use_batch_contracts_and_normalize() -> None:
    EmbeddingHandler.requests = []
    EmbeddingHandler.digest = "sha256:" + ("a" * 64)
    server = ThreadingHTTPServer(("127.0.0.1", 0), EmbeddingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    try:
        ollama = OllamaEmbedder("embed-model", endpoint=endpoint)
        assert ollama.identity["model_digest"] == "sha256:" + ("a" * 64)
        assert ollama.identity["version"] == ollama.identity["model_digest"]
        assert ollama.embed_documents(["one", "two"]) == [
            pytest.approx([0.6, 0.8]),
            pytest.approx([0.6, 0.8]),
        ]

        compatible = OpenAICompatibleEmbedder(
            "embed-model", endpoint=endpoint, api_key="secret"
        )
        vectors = compatible.embed_documents(["one", "two"])
        assert vectors[0] == pytest.approx([2**-0.5, 2**-0.5])
        assert vectors[1] == pytest.approx([2 / 5**0.5, 1 / 5**0.5])
        assert EmbeddingHandler.requests[0][0] == "/api/embed"
        assert EmbeddingHandler.requests[1][0] == "/v1/embeddings"
        assert EmbeddingHandler.requests[1][2] == "Bearer secret"
        EmbeddingHandler.digest = "sha256:" + ("b" * 64)
        with pytest.raises(ValueError, match="digest changed"):
            ollama.verify_identity()
        with pytest.raises(ValueError, match="must not contain credentials"):
            OpenAICompatibleEmbedder(
                "embed-model", endpoint="https://user:secret@example.test"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_semantic_search_finds_paraphrase_and_explains_canonical_result(
    tmp_path: Path,
) -> None:
    memory = Memory(tmp_path / "mem.db")
    airport = memory.remember("u1", "My preferred airport is Sydney.")["records"][0]
    memory.remember("u1", "My favorite color is teal.")
    index = SemanticIndex(tmp_path / "vectors.db")
    embedder = ConceptEmbedder()
    try:
        built = index.build(memory, "u1", embedder)
        assert built["entry_count"] == 2

        lexical = search_evidence(
            memory, "u1", "departure location", scope="memories"
        )
        assert lexical["results"] == []

        semantic = search_evidence(
            memory,
            "u1",
            "departure location",
            scope="memories",
            mode="semantic",
            semantic_index=index,
            embedder=embedder,
        )
        assert semantic["results"][0]["id"] == airport["id"]
        explanation = semantic["results"][0]["retrieval"]
        assert explanation["semantic_rank"] == 1
        assert explanation["canonical_validation"]["digest_matched"] is True

        hybrid = search_evidence(
            memory,
            "u1",
            "departure location",
            scope="memories",
            mode="hybrid",
            semantic_index=index,
            embedder=embedder,
        )
        assert hybrid["results"][0]["id"] == airport["id"]
        assert hybrid["results"][0]["retrieval"]["rrf_score"] > 0
        assert index.search(memory, "u1", "departure location", embedder) == index.search(
            memory, "u1", "departure location", embedder
        )

        traced = trace_evidence(
            memory,
            "u1",
            "departure location",
            mode="semantic",
            semantic_index=index,
            embedder=embedder,
        )
        assert any(item["id"] == airport["id"] for item in traced["timeline"])

        memory.remember("u1", "My backup email is recovery@example.com.")
        with pytest.raises(ValueError, match="verification failed"):
            search_evidence(
                memory,
                "u1",
                "account recovery",
                scope="memories",
                mode="semantic",
                semantic_index=index,
                embedder=embedder,
            )
        rebuilt = index.build(memory, "u1", embedder)
        assert rebuilt["entry_count"] == 3
        status = index.status("u1")
        assert len(status["epochs"]) == 2
        assert not index._conn.execute(
            """
            SELECT 1 FROM vector_entries v
            JOIN vector_epochs e ON e.epoch_id = v.epoch_id
            WHERE e.status = 'retired'
            """
        ).fetchall()
    finally:
        index.close()
        memory.close()


def test_stale_or_cross_subject_vectors_fail_closed(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "mem.db")
    record = memory.remember("u1", "My preferred airport is Sydney.")["records"][0]
    index = SemanticIndex(tmp_path / "vectors.db")
    embedder = ConceptEmbedder()
    try:
        index.build(memory, "u1", embedder)
        memory.store._conn.execute(
            "UPDATE records SET content = ? WHERE id = ?",
            ("tampered content", record["id"]),
        )
        assert index.search(memory, "u1", "departure", embedder) == []
        report = index.verify(memory, "u1")
        assert report["valid"] is False
        assert report["stale_vectors"] == [record["id"]]

        memory.store._conn.execute(
            "UPDATE records SET content = ? WHERE id = ?",
            ("User's preferred airport is Sydney.", record["id"]),
        )
        index._conn.execute(
            "UPDATE vector_entries SET subject_id = 'u2' WHERE object_id = ?",
            (record["id"],),
        )
        assert index.search(memory, "u1", "departure", embedder) == []
        report = index.verify(memory, "u1")
        assert report["valid"] is False
        assert report["cross_subject_vectors"] == [record["id"]]
    finally:
        index.close()
        memory.close()


def test_dimension_mismatch_raises_for_direct_search(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "mem.db")
    record = memory.remember("u1", "My preferred airport is Sydney.")["records"][0]
    index = SemanticIndex(tmp_path / "vectors.db")
    embedder = ConceptEmbedder()
    try:
        index.build(memory, "u1", embedder)
        index._conn.execute(
            """
            UPDATE vector_entries
            SET dimensions = 2, vector = ?
            WHERE object_id = ?
            """,
            (b"\x00" * 8, record["id"]),
        )
        with pytest.raises(ValueError, match="active epoch"):
            index.search(memory, "u1", "departure", embedder)
    finally:
        index.close()
        memory.close()


def test_verification_cache_uses_generation_and_batch_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory = Memory(tmp_path / "mem.db")
    memory.remember("u1", "My preferred airport is Sydney.")
    index = SemanticIndex(tmp_path / "vectors.db")
    embedder = ConceptEmbedder()
    try:
        index.build(memory, "u1", embedder)
        index._conn.execute("DELETE FROM verification_cache")
        calls = 0
        original = memory.store.get_records

        def counted(subject_id: str, record_ids: list[str]) -> dict:
            nonlocal calls
            calls += 1
            return original(subject_id, record_ids)

        monkeypatch.setattr(memory.store, "get_records", counted)
        assert index.verify(memory, "u1")["valid"] is True
        assert index.verify(memory, "u1")["valid"] is True
        assert calls == 1

        memory.remember("u1", "My favorite color is teal.")
        assert index.verify(memory, "u1")["valid"] is False
        assert calls == 2
    finally:
        index.close()
        memory.close()


def test_investigator_access_is_separate_and_digest_only(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "mem.db")
    memory.remember("u1", "My preferred airport is Sydney.")
    try:
        before = len(memory.audit("u1")["audit_log"])
        report = search_evidence(
            memory,
            "u1",
            "airport",
            scope="memories",
            audit_access=True,
            access_actor="auditor@example.test",
        )
        assert report["access_audit_id"].startswith("access_")
        assert len(memory.audit("u1")["audit_log"]) == before
        events = memory.store.list_investigation_access("u1")
        assert len(events) == 1
        assert events[0]["actor"] == "auditor@example.test"
        assert "airport" not in json.dumps(events[0])
        assert memory.store.verify_investigation_access("u1")["valid"] is True
    finally:
        memory.close()


def test_forget_removes_vectors_and_returns_verified_v2_receipt(
    tmp_path: Path,
) -> None:
    memory = Memory(tmp_path / "mem.db")
    record = memory.remember("u1", "My backup email is private@example.com.")[
        "records"
    ][0]
    index = SemanticIndex(f"{tmp_path / 'mem.db'}.vectors.db")
    embedder = ConceptEmbedder()
    index.build(memory, "u1", embedder)
    index.close()
    try:
        forgotten = memory.forget("u1", utterance="Forget my backup email.")
        receipt = forgotten["receipt"]
        assert receipt["format"] == "aetnamem-deletion-receipt-v2"
        assert receipt["semantic_index_cleanup"]["verified_absent"] is True

        reopened = SemanticIndex(f"{tmp_path / 'mem.db'}.vectors.db")
        try:
            assert reopened.search(memory, "u1", "private email", embedder) == []
            assert reopened.verify(memory, "u1")["valid"] is True
            count = reopened._conn.execute(
                "SELECT COUNT(*) AS count FROM vector_entries WHERE object_id = ?",
                (record["id"],),
            ).fetchone()["count"]
            assert count == 0
        finally:
            reopened.close()
    finally:
        memory.close()


def test_custom_index_is_registered_and_missing_sidecar_blocks_false_purge(
    tmp_path: Path,
) -> None:
    memory = Memory(tmp_path / "mem.db")
    record = memory.remember("u1", "My backup email is private@example.com.")[
        "records"
    ][0]
    custom_path = tmp_path / "custom" / "semantic.db"
    index = SemanticIndex(custom_path)
    index.build(memory, "u1", ConceptEmbedder())
    index.close()
    assert memory.store.semantic_index_paths("u1")[0]["index_path"] == str(
        custom_path.resolve()
    )

    custom_path.unlink()
    with pytest.raises(RuntimeError, match="registered semantic index is missing"):
        memory.forget("u1", utterance="Forget my backup email.")
    assert memory.store.get_record("u1", record["id"])["status"] == "active"
    assert not any(
        event["event_type"] == "memory.forget"
        for event in memory.audit("u1")["audit_log"]
    )
    memory.close()


def test_cli_index_build_hybrid_search_and_verify(tmp_path: Path) -> None:
    db = str(tmp_path / "mem.db")
    environment = {"PYTHONPATH": str(ROOT)}

    def run(*arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "aetnamem.cli", *arguments],
            capture_output=True,
            text=True,
            env=environment,
        )

    assert run("remember", db, "u1", "My preferred airport is Sydney.").returncode == 0
    built = run(
        "index",
        "build",
        db,
        "--subject",
        "u1",
        "--embedder",
        "hashing",
        "--model",
        "64",
    )
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["format"] == "aetnamem-index-build-v1"

    searched = run(
        "search",
        db,
        "airport",
        "--subject",
        "u1",
        "--mode",
        "hybrid",
        "--format",
        "json",
    )
    assert searched.returncode == 0, searched.stderr
    result = json.loads(searched.stdout)["results"][0]
    assert result["retrieval"]["semantic_rank"] == 1
    assert result["retrieval"]["canonical_validation"]["digest_matched"] is True

    verified = run("index", "verify", db, "--subject", "u1")
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["valid"] is True
