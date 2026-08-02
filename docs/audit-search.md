# Search memories and trace their influence

AetnaMem lets a person start with an ordinary clue—words such as “preferred
airport”, a date, a session, a tool name, or a failed outcome—without first
knowing a memory or event ID.

The investigation workflow has three commands:

| Command | Question it answers |
|---|---|
| `aetnamem memories` | What does AetnaMem currently remember about this user? |
| `aetnamem search` | Which memories or evidence match this clue? |
| `aetnamem trace` | How did matching memory flow into retrieval, context, actions, and outcomes? |

These commands do not call agent `recall()` and never add an event to the
agent's behavioral evidence chain. By default they are read-only. An operator
can explicitly record digest-only access in a separate investigator chain.

## Quick start

List active memories in a readable form:

```bash
aetnamem memories ./memories.db --subject user-1
```

Include quarantined, superseded, and tombstoned records:

```bash
aetnamem memories ./memories.db --subject user-1 --all
```

Search using words rather than an internal ID:

```bash
aetnamem search ./memories.db "preferred airport" --subject user-1
```

Turn the clue into a chronological evidence trail:

```bash
aetnamem trace ./memories.db "preferred airport" --subject user-1
```

After building an optional semantic index, use `--mode semantic` or
`--mode hybrid` to find paraphrases rather than exact wording:

```bash
aetnamem search ./memories.db "departure location" \
  --subject user-1 \
  --mode hybrid
```

The vector layer only nominates canonical memory records; it does not generate
an answer or replace evidence. Setup, verification, ranking explanations, and
purge behavior are documented in
[Semantic investigation search](semantic-search.md).

## Audit Explorer for OpenClaw

The local OpenClaw dashboard includes a global **Audit Explorer** in addition
to ordinary memory search:

```bash
aetnamem dashboard daemon open
```

It searches the complete subject audit chain with an FTS5 evidence index and
compound SQLite indexes. The browser receives one stable cursor page at a
time; it does not load the complete audit lifetime into JavaScript.

An investigator can combine:

- free-text evidence, digest, model, and identifier search;
- exact or wildcard event type, actor, session, record, and time filters;
- 15-minute, one-hour, 24-hour, seven-day, and all-time ranges;
- admission, recall, context-injection, response, and deletion stages;
- newest/oldest ordering and 50, 100, 250, or 500-row pages.

The histogram represents the currently filtered evidence. Selecting a bucket
narrows the investigation to that exact interval. Selecting an event opens its
canonical payload, chain sequence, previous hash, event hash, and linked
identifiers. Those identifiers pivot back into the explorer or open the exact
memory-record history. Saved views remain in the operator's local browser.

Filtered evidence can be exported as CSV, JSON, NDJSON, or human-readable
text. Each export records its filters, result count, verification result,
result digest, report digest, and creation time. Export access is appended to
the separate investigator-access chain. A single export is deliberately
bounded to 100,000 events and says `truncated: true` if that boundary is
reached; use narrower time ranges for larger investigations.

### Candidate, return, injection, and response are different facts

The record drill-down shows separate counts for considered, returned,
injected, and response-bound evidence. New context-injection events carry the
exact retrieval ID, and the OpenClaw response event carries both the retrieval
and context-event IDs. A candidate-only retrieval can never be displayed as a
delivery. Older evidence that predates those identifiers is retained with an
explicit `legacy-session-time` assurance label rather than represented as an
exact link.

The dashboard is currently a protected loopback operator surface. It provides
a deep local investigation workflow, not organization-wide SSO, RBAC, remote
retention management, or a distributed Splunk replacement.

## Record who investigated

Add `--audit-access` when the investigation itself must be reviewable:

```bash
aetnamem search ./memories.db "departure location" \
  --subject user-1 \
  --mode hybrid \
  --audit-access \
  --access-actor auditor@example.test
```

The access event stores the actor label, operation, query digest, filter
digest, result-ID digest and count, semantic epoch, and verification-report
digest. It does not store the raw query or result content. Access events form
their own hash chain, so an investigation does not alter the agent evidence
being investigated or invalidate semantic verification caches.

List and verify that chain:

```bash
aetnamem access-log ./memories.db --subject user-1
```

`--access-actor` is caller-supplied metadata, not authentication. A service or
dashboard should set it from a trusted authenticated identity. A plain SHA-256
query digest can still be guessed when the query space is predictable; a
deployment requiring resistance to such guessing should place the CLI behind
an access layer that records a keyed digest.

The trace resolver follows available relationships among records, media
artifacts and observations, episodes, retrieval candidates and returned IDs,
audit events, four-memory runtime runs, context manifests, interventions,
outcomes, and guarded-action transactions.
It also reports whether the subject's local hash chain verifies.

## Save a report

Text is the default for the terminal:

```bash
aetnamem trace ./memories.db "preferred airport" \
  --subject user-1 \
  --output airport-trace.txt
```

Use JSON for evidence processing, archival, or another user interface:

```bash
aetnamem trace ./memories.db "preferred airport" \
  --subject user-1 \
  --format json \
  --output airport-trace.json
```

The `.json` extension selects JSON automatically, so `--format json` is
optional in the preceding example. An explicit `--format text|json` always
wins. When `--output` is omitted, the complete report is written to stdout
and can be piped normally.

```bash
aetnamem search ./memories.db calendar --subject user-1 --format json |
  jq '.results[] | {kind, id, created_at, summary}'
```

## Narrow a search

Search all evidence from a session:

```bash
aetnamem search ./memories.db --subject user-1 --session session-123
```

Search one evidence family:

```bash
aetnamem search ./memories.db calendar \
  --subject user-1 \
  --scope events
```

Available scopes are `all`, `memories`, `media`, `episodes`, `retrievals`,
`events`, `runs`, and `actions`. The `media` scope ships in `v0.5.2`.

Useful filters include:

```bash
# Event types accept shell-style wildcards.
aetnamem search ./memories.db --subject user-1 --event-type 'memory.*'

# Search a UTC date interval.
aetnamem search ./memories.db airport --subject user-1 \
  --since 2026-07-01 --until 2026-07-31

# Filter runtime evidence by memory plane.
aetnamem search ./memories.db --subject user-1 --plane episodic

# Find unsuccessful recorded outcomes.
aetnamem search ./memories.db --subject user-1 --outcome failed

# Select more than one memory state.
aetnamem search ./memories.db airport --subject user-1 \
  --scope memories --status active --status superseded
```

Words in a query use case-insensitive AND matching across the selected
evidence. Exact phrases rank ahead of separated terms. Use `--limit` to bound
the returned result set.

## Trace with or without a known ID

A free-text clue is normally enough:

```bash
aetnamem trace ./memories.db "book my flight" --subject user-1
```

When an identifier is available, it can be used directly:

```bash
aetnamem trace ./memories.db --subject user-1 --session session-123
aetnamem trace ./memories.db --subject user-1 --run run_123
aetnamem trace ./memories.db --subject user-1 --record rec_123
aetnamem trace ./memories.db --subject user-1 --event-type memory.recall
```

The text report is intended for human review. The JSON report preserves each
item's original structured data and extracted links for independent analysis.

## What “verified” means

`Integrity: VERIFIED (local hash chain)` means the recorded events for that
subject pass AetnaMem's hash-chain rules. It does not detect deletion from the
end of the chain or replacement of the whole database. For that, create
checkpoints on a schedule, store them in a different trust domain, and verify
against them:

```bash
aetnamem checkpoint ./memories.db ./checkpoints.jsonl
aetnamem verify ./memories.db --checkpoints ./checkpoints.jsonl
```

The search report does not claim that an input was truthful, an actor label
was authenticated, or a remote effect occurred. Those conclusions require
trusted host identity and receipt evidence.

## Privacy and deletion boundaries

Audit search is an authorized administrative capability: reports can contain
retained user memory, episode text, context contributions, and operational
metadata. Protect the database and exported reports accordingly. A
`subject_id` is a storage scope, not authentication; expose these commands
through a trusted access-control layer in a multi-user deployment.

After a logical erasure, search can still locate the deletion transition,
record IDs, and retained digests. It cannot and should not recover purged
plaintext. Likewise, queries are normally represented in historical
retrievals by `query_sha256`; raw retrieval query text exists only when the
engine was deliberately configured with `retain_query_text=True`.

For chain construction, external checkpoints, deletion receipts, and the full
threat model, continue with the [auditing guide](auditing-guide.md) and
[audit-log specification](audit-log-spec.md).
