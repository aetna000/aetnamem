# Using aetnamem's auditability

This is the operational guide: how to run the audit features day to day and
what to hand to a data subject, a security reviewer, or an external auditor.
For the frozen wire format and hash recipes, see
[audit-log-spec.md](audit-log-spec.md).

## The mental model

aetnamem separates two planes:

- **Data plane** (`records`, `episodes`) — the actual memory content. This
  is erasable: `forget()` purges it.
- **Audit plane** (`audit_log`, `retrieval_events`) — append-only evidence
  *that* things happened. It stores digests and structural metadata, never
  message text, fact values, or query text, so it can be immutable without
  blocking erasure.

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
fact. Every `recall()` produces a retrieval event whose `candidates` list
carries the score breakdown (`text_score`, `trust_score`, `recency_score`)
for every considered record — so you can answer *"why did the agent see
this?"* later.

By default the query text itself is not retained, only `query_sha256`. If
you need raw queries for local debugging:

```python
m = Memory("./memories.db", retain_query_text=True)   # opt-in, off in prod
```

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

For anything adversarial (or for a third party), use the standalone
verifier, which implements the spec without importing aetnamem:

```bash
python tools/verify_audit.py ./memories.db --checkpoints ./checkpoints.jsonl
```

## Compliance workflows

### Handling an erasure request (GDPR Art. 17 / CCPA delete)

```python
result = m.forget("user-1", utterance="Forget my backup email.",
                  session_id="dsar-2026-041")

result["deleted"]         # True if anything matched
result["record_ids"]      # what was purged
receipt = result["receipt"]
```

The receipt is the artifact you retain (and can show the requester or a
regulator): it names the purged record and episode IDs, carries the selector
only as a digest, and binds to the `memory.forget` audit event by ID and
hash — so it is exactly as tamper-evident as the chain. Store receipts with
the request ticket.

To *prove* erasure afterwards:

1. `m.recall("user-1", <related query>)` returns nothing derived from the
   purged content — retrieval never sees tombstoned records.
2. `m.inspect("user-1")` shows the record with `status="tombstoned"`,
   `content=""`, `fact_key=None`, and the source episode as `[purged]`.
3. The audit log still proves the fact existed and was deleted on a date —
   without revealing what it was.

Note `forget()` refuses an empty selector rather than deleting everything,
and forget intent embedded in webpage/tool content is ignored by design
(deletion cannot be prompt-injected).

### Handling an access/portability request (GDPR Art. 15/20)

`m.inspect(subject_id)` is the export: all records (any status) with full
provenance, all episodes, all retrieval events, the audit log, and
`audit_chain_valid`. Serialize it as JSON and you have a machine-readable
disclosure of everything held on that subject, including the history of how
it was used (`memory.recall` events show which records were surfaced when).

### Rectification (GDPR Art. 16)

Corrections are supersession, not edits: `remember()` a corrected statement
with the same fact slot ("Actually, use OAK as my preferred airport") and
the old record flips to `superseded`, linked via `supersedes_id`, leaving
the correction history inspectable.

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
- log **digests, not payloads** — same rule as the rest of the audit plane;
- bare names get an `agent.` prefix (`tool_call` → `agent.tool_call`); use
  dotted names for your own taxonomy;
- this is the shape EU AI Act Art. 12 record-keeping expects from high-risk
  systems: automatic, timestamped, per-interaction event logs (Art. 19
  requires keeping them ≥ 6 months — don't `reset_subject()` in production).

Reconstruct a session:

```python
events = [e for e in m.audit("user-1")["audit_log"] if e["session_id"] == "s1"]
```

## What to hand an external auditor

1. The database file (or a copy) and the anchored checkpoint file.
2. [audit-log-spec.md](audit-log-spec.md) — the format they verify against.
3. `tools/verify_audit.py` as a reference implementation they can read in
   five minutes or reimplement.
4. Deletion receipts for any contested erasures.

They do not need aetnamem installed, network access, or your word.

## Known limits (roadmap)

- Checkpoints and receipts are **hashed, not signed** — they prove
  consistency, not authorship. Key-based signatures are planned.
- Record/episode content is plaintext at rest; **crypto-shredding**
  (per-record keys, erasure = key destruction) is the planned hardening.
- Timestamps trust the local clock at write time; anchor checkpoints to an
  RFC 3161 service if you need trusted time.
- No retention policies yet (storage limitation must be enforced by the
  caller), and no automatic special-category (GDPR Art. 9) flagging.
