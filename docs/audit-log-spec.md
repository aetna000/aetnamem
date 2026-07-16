# aetnamem audit log specification (v1)

This document freezes the on-disk audit format so that integrity can be
verified by independent implementations — you should not need to trust
aetnamem's code to check aetnamem's claims.
[tools/verify_audit.py](../tools/verify_audit.py) is a reference verifier
written against this spec using only the Python standard library.

## Canonical serialization

Every hashed structure serializes as JSON with **sorted keys**, separators
`(",", ":")` (no whitespace), and UTF-8 encoding. Hashes are lowercase hex
SHA-256. In Python terms:

```python
sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
```

## The audit event chain

Table `audit_log`, one row per event:

| column | meaning |
|---|---|
| `sequence` | global monotonically increasing integer (SQLite AUTOINCREMENT) |
| `event_id` | `aud_<uuid4hex>` |
| `subject_id` | tenant/user scope; chains are per subject |
| `event_type` | e.g. `episode.ingested`, `memory.record_created`, `memory.record_quarantined`, `memory.record_promoted`, `memory.duplicate_ignored`, `memory.recall`, `memory.forget`, `memory.forget_rejected`, `graph.*`, `entity.*`, `edge.*`, `alias.*`, `agent.*`, `action.*` |
| `created_at` | ISO-8601 UTC timestamp |
| `actor` | `user`, `system`, `agent`, … |
| `session_id`, `turn_id`, `record_id` | optional context, may be null |
| `payload` | canonical JSON object |
| `prev_hash` | `event_hash` of the same subject's previous event; null for the first |
| `event_hash` | hash of the preimage below |

The **preimage** of `event_hash` is the canonical JSON of exactly this
object (keys shown unsorted for readability; canonical form sorts them):

```json
{
  "event_id": ..., "subject_id": ..., "event_type": ..., "created_at": ...,
  "actor": ..., "session_id": ..., "turn_id": ..., "record_id": ...,
  "payload": {...}, "prev_hash": ...
}
```

**Chain rule.** For each subject, order events by `sequence`. The first
event's `prev_hash` is null; every later event's `prev_hash` equals the
previous event's `event_hash`, and every `event_hash` must recompute from
its preimage.

## Content rules for engine-generated events

Core memory events and retrieval events store **digests and structural
metadata**: `message_sha256` for ingested episodes, `query_sha256` for recall
queries (`retrieval_events.query` is empty unless the engine was constructed
with `retain_query_text=True`), `selector_sha256` for forget selectors,
`utterance_sha256` for natural-language forget requests, and record/episode
IDs. Fact *slot names* (`fact_key`, e.g. "backup email") may appear in
non-deletion payloads for debuggability; fact *values* and message text
do not. Purging a record clears its content and its `fact_key`.

Guarded-action events follow the same split: plan, argument, preview,
precondition, result, observation, error, and compensation **digests** may
enter `action.*` payloads, while raw arguments, before-images, previews,
provider results, and compensation material live in the erasable
`action_payloads` table. The action tables are not part of this v1 hash
preimage; action IDs are carried in event payloads. See
[guarded-actions.md](guarded-actions.md).

This is an engine-path convention, not a database constraint. The low-level
`Memory.log_action()` / `memory_log_action` API accepts an arbitrary caller
payload, and `retain_query_text=True` deliberately stores raw retrieval query
text outside the audit table. Callers must use digests rather than raw or
secret values in custom action payloads.

This separation lets engine-generated history remain append-only while the
live content columns in `records`, `episodes`, and `action_payloads` can be
logically purged. It does not sanitize SQLite free pages, WAL files, backups,
snapshots, exports, or replicas.

## Checkpoints (`aetnamem-checkpoint-v1`)

A checkpoint pins every subject's chain head at a moment in time:

```json
{
  "format": "aetnamem-checkpoint-v1",
  "created_at": "...",
  "subjects": {"<subject_id>": {"sequence": N, "event_hash": "...", "event_count": C}},
  "checkpoint_sha256": "<hash of the document without this field>"
}
```

`Memory.checkpoint(sink_path=...)` appends one canonical-JSON line per
checkpoint to a JSONL sink. **The sink must live somewhere the database
owner cannot rewrite** — WORM/object-lock storage, a transparency log, an
RFC 3161 timestamp, or at minimum a different trust domain. A checkpoint
stored next to the database detects accidents, not adversaries.

`audit_verification_state` is a local performance cache for incremental
verification. Its cached event is re-read and hash-checked before verifying
the suffix; audit-row update/delete triggers invalidate it and force a full
replay. Because the cache is in the same database, it is not part of this
trust format and cannot replace an externally stored checkpoint.

**Containment rule.** For each pinned subject: the event at `sequence` must
exist and its `event_hash` must equal the pinned value.

## Deletion receipts (`aetnamem-deletion-receipt-v1`)

`forget()` returns a receipt binding the deletion to the chain:

```json
{
  "format": "aetnamem-deletion-receipt-v1",
  "subject_id": ..., "created_at": ...,
  "selector_sha256": ...,
  "purged_record_ids": [...], "purged_episode_ids": [...],
  "purged_graph_ids": [...],
  "audit_event_id": ..., "audit_event_hash": ...,
  "receipt_sha256": "<hash of the receipt without this field>"
}
```

To verify: recompute `receipt_sha256`; look up `audit_event_id` in the
chain; its `event_hash` must equal `audit_event_hash` and its payload must
list the same purged record, episode, and derived graph IDs. Because the event is chained, the receipt is as
tamper-evident as the chain itself.

## Threat model — what each layer detects

| attack | detected by |
|---|---|
| editing, inserting, or reordering past events | chain rule |
| deleting events from the middle of a chain | chain rule |
| deleting events from the **end** of a chain | checkpoint containment only |
| replacing the whole database | checkpoint containment only |
| backdating via the system clock at write time | not detected — anchor checkpoints to a trusted timestamp source |

`reset_subject()` erases a subject wholesale (it exists for test harnesses);
any anchored checkpoint covering that subject will subsequently fail
verification, which is the intended signal.

## Verification procedure

1. For every subject: apply the chain rule (recompute all hashes).
2. For every anchored checkpoint: recompute `checkpoint_sha256`, then apply
   the containment rule per subject.
3. For any deletion receipt presented: apply the receipt rule above.

A database passes only if all three hold.
