from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from aetnamem import Memory
from aetnamem.investigate import search_evidence, trace_evidence
from aetnamem.semantic import HashingEmbedder, SemanticIndex


ROOT = Path(__file__).resolve().parents[1]


def _envelope(
    text: str = "The receipt shows a total of $42.",
    *,
    payload: bytes = b"exact-image-bytes",
    provider: str = "grok",
    version: str = "vision-1",
    host_reference: str = "openclaw://media/receipt-1",
) -> dict:
    return {
        "text": text,
        "modality": "image",
        "media_sha256": hashlib.sha256(payload).hexdigest(),
        "host_reference": host_reference,
        "segment": {"region": "x=10,y=20,w=300,h=80"},
        "extractor": {
            "provider": provider,
            "model": "grok-vision",
            "version": version,
        },
        "confidence": 0.86,
    }


def test_observation_is_one_quarantined_record_with_provenance() -> None:
    memory = Memory(":memory:")
    admitted = memory.remember_observation("alice", _envelope())

    assert admitted["duplicate"] is False
    assert admitted["record"]["status"] == "quarantined"
    assert admitted["record"]["content"] == "The receipt shows a total of $42."
    assert admitted["record"]["confidence"] is None
    assert admitted["observation"]["confidence"] == 0.86
    assert memory.list("alice") == []

    all_records = memory.list("alice", include_inactive=True)
    assert len(all_records) == 1
    provenance = all_records[0]["media_observation"]
    assert provenance["modality"] == "image"
    assert provenance["extractor"]["provider"] == "grok"
    assert provenance["digest_assurance"] == "caller_asserted"


def test_invalid_or_mismatched_digest_fails_closed() -> None:
    memory = Memory(":memory:")
    invalid = _envelope()
    invalid["media_sha256"] = "not-a-digest"
    with pytest.raises(ValueError, match="64-character"):
        memory.remember_observation("alice", invalid)
    assert memory.store.list_media_artifacts("alice") == []

    ambiguous_time = _envelope()
    ambiguous_time["observed_at"] = "2026-07-25T12:00:00"
    with pytest.raises(ValueError, match="timezone"):
        memory.remember_observation("alice", ambiguous_time)

    admitted = memory.remember_observation("alice", _envelope())
    mismatch = _envelope("A second observation.", payload=b"different")
    mismatch["artifact_id"] = admitted["artifact"]["id"]
    with pytest.raises(ValueError, match="digest mismatch"):
        memory.remember_observation("alice", mismatch)
    assert len(memory.store.list_media_observations("alice")) == 1


def test_verified_by_aetnamem_cannot_be_self_certified() -> None:
    memory = Memory(":memory:")
    claimed = _envelope()
    claimed["digest_assurance"] = "verified_by_aetnamem"
    with pytest.raises(ValueError, match="reserved"):
        memory.remember_observation("alice", claimed)
    with pytest.raises(ValueError, match="reserved"):
        memory.remember_observation(
            "alice",
            _envelope(),
            forced_assurance="verified_by_aetnamem",
        )
    assert memory.store.list_media_artifacts("alice") == []

    host_asserted = _envelope()
    host_asserted["digest_assurance"] = "host_asserted"
    admitted = memory.remember_observation("alice", host_asserted)
    assert admitted["observation"]["digest_assurance"] == "host_asserted"


def test_reruns_supersede_only_same_lineage_and_never_displace_promoted_fact() -> None:
    memory = Memory(":memory:")
    first = memory.remember_observation("alice", _envelope("First extraction."))
    second = memory.remember_observation("alice", _envelope("Corrected extraction."))

    first_record = memory.store.get_record("alice", first["record"]["id"])
    assert first_record["status"] == "superseded"
    assert second["record"]["status"] == "quarantined"

    third = memory.remember_observation(
        "alice", _envelope("Independent extraction.", provider="other")
    )
    assert memory.store.get_record("alice", second["record"]["id"])["status"] == "quarantined"
    assert third["record"]["status"] == "quarantined"

    promoted = memory.promote("alice", second["record"]["id"])
    assert promoted["status"] == "active"
    independently_promoted = memory.promote("alice", third["record"]["id"])
    assert independently_promoted["status"] == "active"
    fourth = memory.remember_observation("alice", _envelope("Another correction."))
    assert memory.store.get_record("alice", second["record"]["id"])["status"] == "active"
    assert memory.store.get_record("alice", third["record"]["id"])["status"] == "active"
    assert fourth["record"]["status"] == "quarantined"

    promoted_fourth = memory.promote("alice", fourth["record"]["id"])
    assert promoted_fourth["status"] == "active"
    assert (
        memory.store.get_record("alice", second["record"]["id"])["status"]
        == "superseded"
    )
    active_ids = {item["id"] for item in memory.list("alice")}
    assert fourth["record"]["id"] in active_ids
    assert third["record"]["id"] in active_ids
    assert second["record"]["id"] not in active_ids

    promoted_event = next(
        item
        for item in reversed(memory.audit("alice")["audit_log"])
        if item["event_type"] == "memory.record_promoted"
        and item["record_id"] == fourth["record"]["id"]
    )
    assert second["record"]["id"] in promoted_event["payload"]["supersedes"]
    assert (
        second["observation"]["id"]
        in promoted_event["payload"]["superseded_observation_ids"]
    )


def test_exact_envelope_is_idempotent() -> None:
    memory = Memory(":memory:")
    first = memory.remember_observation("alice", _envelope())
    duplicate = memory.remember_observation("alice", _envelope())

    assert duplicate["duplicate"] is True
    assert duplicate["observation"]["id"] == first["observation"]["id"]
    assert len(memory.store.list_media_observations("alice")) == 1


def test_artifact_retains_first_host_reference_for_identical_bytes() -> None:
    memory = Memory(":memory:")
    first = memory.remember_observation(
        "alice",
        _envelope(
            "First location.",
            host_reference="openclaw://media/receipt-1",
        ),
    )
    second = memory.remember_observation(
        "alice",
        _envelope(
            "Second location.",
            host_reference="hermes://media/receipt-copy",
        ),
    )

    assert second["artifact"]["id"] == first["artifact"]["id"]
    assert second["artifact"]["host_reference"] == "openclaw://media/receipt-1"
    admission = next(
        item
        for item in reversed(memory.audit("alice")["audit_log"])
        if item["event_type"] == "media.observation_admitted"
        and item["record_id"] == second["record"]["id"]
    )
    assert admission["payload"]["host_reference_sha256"] == hashlib.sha256(
        b"hermes://media/receipt-copy"
    ).hexdigest()


def test_forget_artifact_has_narrow_verified_receipt() -> None:
    memory = Memory(":memory:")
    admitted = memory.remember_observation("alice", _envelope())
    digest = admitted["artifact"]["media_sha256"]

    forgotten = memory.forget_artifact("alice", digest)

    assert forgotten["deleted"] is True
    receipt = forgotten["receipt"]
    assert receipt["format"] == "aetnamem-artifact-deletion-receipt-v1"
    assert receipt["digest_identity"] == "sha256-of-exact-byte-stream"
    assert receipt["host_file_deleted"] is False
    assert receipt["verification"]["valid"] is True
    assert receipt["artifact_id"] == admitted["artifact"]["id"]
    assert admitted["observation"]["id"] in receipt["purged_observation_ids"]
    assert admitted["record"]["id"] in receipt["purged_record_ids"]
    assert admitted["record"]["id"] in receipt["linked_record_ids"]

    record = memory.store.get_record("alice", admitted["record"]["id"])
    assert record["status"] == "tombstoned"
    assert record["content"] == ""
    assert memory.store.get_media_artifact(
        "alice", artifact_id=admitted["artifact"]["id"]
    )["host_reference"] == ""


def test_exact_digest_deletion_does_not_claim_a_reencoded_copy() -> None:
    memory = Memory(":memory:")
    original = memory.remember_observation(
        "alice", _envelope("Original image observation.", payload=b"jpeg")
    )
    reencoded = memory.remember_observation(
        "alice", _envelope("Re-encoded image observation.", payload=b"png")
    )

    memory.forget_artifact("alice", original["artifact"]["media_sha256"])

    assert memory.store.get_media_artifact(
        "alice", artifact_id=original["artifact"]["id"]
    )["status"] == "tombstoned"
    assert memory.store.get_media_artifact(
        "alice", artifact_id=reencoded["artifact"]["id"]
    )["status"] == "active"
    assert memory.store.get_record(
        "alice", reencoded["record"]["id"]
    )["status"] == "quarantined"


def test_ordinary_content_forget_also_purges_linked_observation_metadata() -> None:
    memory = Memory(":memory:")
    admitted = memory.remember_observation(
        "alice", _envelope("A private access code is 2468.")
    )
    memory.promote("alice", admitted["record"]["id"])

    forgotten = memory.forget("alice", selector="access code")

    assert forgotten["deleted"] is True
    assert forgotten["receipt"]["media_cleanup"]["observation_ids"] == [
        admitted["observation"]["id"]
    ]
    observation = memory.store.get_media_observation(
        "alice", admitted["observation"]["id"]
    )
    assert observation["status"] == "tombstoned"
    assert observation["segment"] == {}
    assert observation["extractor"] == {}
    assert observation["confidence"] is None
    artifact = memory.store.get_media_artifact(
        "alice", artifact_id=admitted["artifact"]["id"]
    )
    assert artifact["status"] == "tombstoned"
    assert artifact["host_reference"] == ""


def test_media_is_searchable_and_traceable_without_known_ids() -> None:
    memory = Memory(":memory:")
    admitted = memory.remember_observation(
        "alice", _envelope("A red bicycle is beside the station.")
    )

    report = search_evidence(memory, "alice", "red bicycle", scope="all")
    kinds = {item["kind"] for item in report["results"]}
    assert {"memory", "observation"} <= kinds

    trace = trace_evidence(memory, "alice", "red bicycle")
    trace_kinds = {item["kind"] for item in trace["timeline"]}
    assert {"artifact", "observation", "memory", "episode", "event"} <= trace_kinds
    assert any(
        item["id"] == admitted["artifact"]["id"] for item in trace["timeline"]
    )


def test_artifact_forget_purges_registered_semantic_vectors(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    index_path = tmp_path / "vectors.db"
    memory = Memory(db_path)
    admitted = memory.remember_observation("alice", _envelope())
    index = SemanticIndex(index_path)
    index.build(memory, "alice", HashingEmbedder(dimensions=16))
    index.close()

    forgotten = memory.forget_artifact(
        "alice", admitted["artifact"]["media_sha256"]
    )
    cleanup = forgotten["receipt"]["semantic_index_cleanup"]
    assert cleanup["verified_absent"] is True

    reopened = SemanticIndex(index_path)
    try:
        count = reopened._conn.execute(
            "SELECT COUNT(*) AS count FROM vector_entries WHERE object_id = ?",
            (admitted["record"]["id"],),
        ).fetchone()["count"]
        assert count == 0
        assert reopened.verify(memory, "alice")["valid"] is True
    finally:
        reopened.close()
        memory.close()


def test_missing_registered_index_rolls_back_artifact_forget(tmp_path) -> None:
    memory = Memory(tmp_path / "memory.db")
    admitted = memory.remember_observation("alice", _envelope())
    index_path = tmp_path / "vectors.db"
    index = SemanticIndex(index_path)
    index.build(memory, "alice", HashingEmbedder(dimensions=16))
    index.close()
    index_path.unlink()

    with pytest.raises(RuntimeError, match="registered semantic index is missing"):
        memory.forget_artifact("alice", admitted["artifact"]["media_sha256"])

    artifact = memory.store.get_media_artifact(
        "alice", artifact_id=admitted["artifact"]["id"]
    )
    record = memory.store.get_record("alice", admitted["record"]["id"])
    assert artifact["status"] == "active"
    assert record["status"] == "quarantined"
    assert not any(
        event["event_type"] == "media.artifact_forgotten"
        for event in memory.audit("alice")["audit_log"]
    )
    memory.close()


def test_cli_observe_and_forget_artifact(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    envelope_path = tmp_path / "observation.json"
    envelope = _envelope()
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
    environment = {"PYTHONPATH": str(ROOT)}

    observed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aetnamem.cli",
            "observe",
            str(db_path),
            "alice",
            "--envelope",
            str(envelope_path),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert observed.returncode == 0, observed.stderr
    result = json.loads(observed.stdout)
    assert result["record"]["status"] == "quarantined"

    forgotten = subprocess.run(
        [
            sys.executable,
            "-m",
            "aetnamem.cli",
            "forget-artifact",
            str(db_path),
            "alice",
            envelope["media_sha256"],
            "--artifact-id",
            result["artifact"]["id"],
        ],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert forgotten.returncode == 0, forgotten.stderr
    receipt = json.loads(forgotten.stdout)["receipt"]
    assert receipt["verification"]["valid"] is True
