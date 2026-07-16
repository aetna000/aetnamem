# Using aetnamem's auditability

This is the operational guide: how to run the audit features day to day and
what to hand to a data subject, a security reviewer, or an external auditor.
For the frozen wire format and hash recipes, see
[audit-log-spec.md](audit-log-spec.md).

## The mental model

aetnamem separates two logical planes:

- **Data plane** (`records`, `episodes`, `action_payloads`) — memory content
  and raw guarded-action material. Engine APIs can logically purge it.
- **Audit plane** (`audit_log`, plus retrieval metadata) — engine-append-only
  evidence *that* things happened. Core paths use digests and structural
  metadata. Raw retrieval query text is optional, and custom `log_action()`
  payloads are caller-controlled.

Trust is layered, and each layer catches what the one below cannot:

| layer | catches | you get it by |
|---|---|---|
| hash chain | edits, inserts, reordering, mid-chain deletion | automatic on every write |
| anchored checkpoints | tail truncation, database replacement | running `checkpoint()` and storing the output externally |
| independent verification | "trust me" — bugs or lies in aetnamem itself | running `tools/verify_audit.py` (no aetnamem import) |

## Everyday operation

### 1. Write memory normally — the trail is automatic

```python
from aetnamem import Memory

m = Memory("./memories.db")
m.remember("user-1", "My preferred airport is SFO.",
           session_id="s1", turn_id=1)
m.recall("user-1", "Which airport should I book from?", session_id="s1")
```

Every `remember()` produces an `episode.ingested` event (with the message's
SHA-256, not the message) plus a `memory.record_created` /
`memory.record_quarantined` / `memory.duplicate_ignored` event per candidate
fact. Every `recall()` produces a retrieval event whose bounded `candidates`
ledger carries ranks, score inputs and breakdowns (`text_score`,
`trust_score`, `recency_score`, and `base_score`), threshold decisions, and
returned markers. It retains the first 50 candidates plus every returned
candidate. Graph recall additionally records seed/cap metadata, fusion inputs,
and path evidence for returned graph hits. A versioned digest of the retrieval
row is stored in the chained recall event, so direct edits to these selected
fields are detectable.

By default the query text itself is not retained, only `query_sha256`. If
you need raw queries for local debugging:

```python
m = Memory("./memories.db", retain_query_text=True)   # opt-in, off in prod
```

The retrieval digest supports reconstruction within the logged ledger. It
does not independently regenerate a past FTS candidate set, and exact engine
re-execution is not expected after correction or deletion changes canonical
inputs. A deleted source remains represented by its digest and deletion
transition, not recoverable plaintext.

### 2. Checkpoint on a schedule, anchor externally

```bash
aetnamem checkpoint ./memories.db ./checkpoints.jsonl
```

Run it from cron/systemd at whatever cadence bounds your exposure — hourly
means at most one hour of tail events could vanish undetected. The critical
step is **anchoring**: `checkpoints.jsonl` must leave the machine that holds
the database, into storage its owner cannot rewrite. Options, weakest to
strongest:

- copy to a different trust domain (another host, a git repo others pull);
- object storage with retention lock, e.g.
  `aws s3api put-object --bucket audit --key ckpt/$(date -u +%FT%TZ).jsonl
  --body checkpoints.jsonl --object-lock-mode COMPLIANCE ...`;
- an RFC 3161 timestamping service or a transparency log, which also proves
  *when* the checkpoint existed.

A checkpoint sitting next to the database detects accidents, not attackers.

### 3. Verify — routinely, and after any incident

```bash
aetnamem verify ./memories.db --checkpoints ./checkpoints.jsonl
```

Exit code is 0/1, so wire it into CI or monitoring directly. From Python:

```python
result = m.verify(checkpoints_path="./checkpoints.jsonl")
result["valid"]                       # overall boolean
result["subjects"]["user-1"]          # chain_valid, checkpoints_checked, failures
```

For frequent local health checks, suffix verification avoids replaying an
ever-growing chain:

```bash
aetnamem verify ./memories.db --incremental
```

The cached head is re-read and hash-checked before each suffix verification.
SQLite triggers invalidate the cache if an audit row is updated or deleted,
forcing a full replay next time. The cache is stored in the same database and
therefore improves performance only; it does not replace an externally
anchored checkpoint.

For anything adversarial (or for a third party), use the standalone
verifier, which implements the spec without importing aetnamem:

```bash
python tools/verify_audit.py ./memories.db --checkpoints ./checkpoints.jsonl
```

## Data-governance workflows

### Handling a memory-content erasure request

```python
result = m.forget("user-1", utterance="Forget my backup email.",
                  session_id="dsar-2026-041")

result["deleted"]         # True if anything matched
result["record_ids"]      # what was purged
receipt = result["receipt"]
```

The receipt is the artifact you retain with the request: it names the purged
record and episode IDs, carries the selector
only as a digest, and binds to the `memory.forget` audit event by ID and
hash — so it is exactly as tamper-evident as the chain. Store receipts with
the request ticket. If the caller used a natural-language `utterance`, that
request text is not stored as an episode; the audit event stores only
`utterance_sha256`.

To verify the live database's logical purge afterwards:

1. `m.recall("user-1", <related query>)` returns nothing derived from the
   purged content — retrieval never sees tombstoned records.
2. `m.inspect("user-1")` shows the record with `status="tombstoned"`,
   `content=""`, `fact_key=None`, and the source episode as `[purged]`.
3. The audit log records that the identified records were created and later
   purged without retaining their fact values.

This does not establish forensic erasure from SQLite free pages, WAL files,
backups, snapshots, exports, or replicas. Those stores need separate retention
and secure-deletion procedures.

Note `forget()` refuses an empty selector rather than deleting everything,
and forget intent embedded in webpage/tool content is ignored by design
(deletion cannot be prompt-injected).

### Producing a memory-data export

`m.inspect(subject_id)` exports memory records (any status) with
provenance, all episodes, all retrieval events, the audit log, and
`audit_chain_valid`. It does not include guarded-action payload tables,
database free pages, backups, or external systems, so it is not by itself a
complete organization-wide subject export.

### Rectifying a recognized fact slot

Corrections with a recognized matching `fact_key` use supersession, not
in-place edits: `remember()` a corrected statement with the same fact slot
("Actually, use OAK as my preferred airport") and
the old record flips to `superseded`, linked via `supersedes_id`, leaving
the correction history inspectable. Unkeyed contradictions require explicit
review.

### Reviewing quarantine

Facts extracted from webpages/tool output land `quarantined`: invisible to
`recall()` and `list()`, but visible with provenance in `inspect()`:

```python
pending = [r for r in m.list("user-1", include_inactive=True)
           if r["status"] == "quarantined"]
m.promote("user-1", pending[0]["id"], session_id="s9")   # explicit user consent
```

Promotion writes `memory.record_promoted`, upgrades trust to
`user_confirmed`, and applies supersession like any other write. Never
promote in bulk without showing the user the content.

## Auditing the agent, not just the memory

The same chain accepts agent action events, so one verifiable trail answers
*what did the agent know, read, decide, call, and show*:

```python
m.log_action("user-1", "model_call",
             {"model": "claude-sonnet-5", "prompt_sha256": "..."},
             session_id="s1", turn_id=3)
m.log_action("user-1", "tool_call",
             {"tool": "calendar.create", "args_sha256": "...", "status": "ok"},
             session_id="s1", turn_id=3)
m.log_action("user-1", "response_shown",
             {"response_sha256": "..."}, session_id="s1", turn_id=3)
```

Conventions that keep the trail useful:

- pass the **same `session_id`/`turn_id`** you pass to `remember`/`recall`,
  so memory reads and actions interleave correctly in one timeline;
- log **digests, not payloads** — `log_action()` does not enforce this for you;
- bare names get an `agent.` prefix (`tool_call` → `agent.tool_call`); use
  dotted names for your own taxonomy;
- retention periods, required fields, access controls, and regulatory
  applicability are deployment/legal decisions; do not use
  `reset_subject()` as a production retention mechanism.

Reconstruct a session:

```python
events = [e for e in m.audit("user-1")["audit_log"] if e["session_id"] == "s1"]
```

## What to hand an external auditor

1. The database file (or a copy) and the anchored checkpoint file.
2. [audit-log-spec.md](audit-log-spec.md) — the format they verify against.
3. `tools/verify_audit.py` and, for guarded actions,
   `tools/verify_actions.py` as independent standard-library implementations.
4. Deletion receipts for any contested erasures.

They do not need aetnamem installed or network access to verify the recorded
hash structure. Verification does not establish authorship or prove remote
effects beyond adapter evidence.

## Known limits (roadmap)

- Checkpoints and receipts are **hashed, not signed** — relative to a trusted
  anchored head they support consistency checks, not authorship. Key-based
  signatures are planned.
- Record/episode content is plaintext at rest; **crypto-shredding**
  (per-record keys, erasure = key destruction) is the planned hardening.
- Logical purge does not sanitize SQLite free pages, WAL, backups, exports,
  snapshots, or replicas.
- Timestamps trust the local clock at write time; anchor checkpoints to an
  RFC 3161 service if you need trusted time.
- No retention policies yet (storage limitation must be enforced by the
  caller), and no automatic special-category (GDPR Art. 9) flagging.
