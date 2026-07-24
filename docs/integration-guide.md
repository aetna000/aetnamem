# Integration guide: CLI and MCP

Repository version boundary: Python `v0.5.0` and OpenClaw npm `v0.3.0` are
public releases. CML measurement modes remain experimental and default off.
See [current capability status](current-status.md).

aetnamem has compatibility surfaces around `Memory` plus the opt-in
four-memory runtime. Pick by what your host can do:

| surface | use when | ships since |
|---|---|---|
| Python library (`from aetnamem import Memory`) | your agent runs Python | v0 |
| Guarded Actions (`from aetnamem.actions import ActionEngine`) | your Python host can enforce a protected execution boundary | v0 |
| Collaborative decisions (`from aetnamem.decisions import DecisionEngine`) | your authenticated host needs voting, EtD, and approved-change traceability | experimental |
| CLI (`aetnamem <verb> …`) | your agent can run shell commands (OpenClaw skills, cron, CI) | v0 |
| memory MCP server (`aetnamem mcp`) | your host speaks MCP and needs memory tools | v0 |
| four-memory Python runtime (`from aetnamem.runtime import MemoryRuntime`) | your host wants one coordinator for all four memory types | v0.5 |
| runtime MCP server (`aetnamem runtime mcp`) | your MCP host wants the complete prepare/outcome loop | v0.5 |

Collaborative decisions are an opt-in Python SDK and add nothing to the
default memory MCP catalog. Authentication, the HTTP server, and the user
interface belong to the host. See
[decision-host-integration.md](decision-host-integration.md).

The memory Python, CLI, and MCP surfaces drive the same `Memory` engine.
Guarded Actions is adjacent and shares its store/audit chain, but the current
MCP server does not intercept or mediate unrelated action tools. Library API
usage is covered in the
[README](../README.md); audit workflows in the
[auditing guide](auditing-guide.md). This document specifies the CLI and
MCP surfaces.

The default MCP catalog remains unchanged. The runtime endpoint appends only
`memory_prepare_turn` and `memory_record_outcome`; see the
[four-memory runtime guide](four-memory-runtime.md) for presets, setup, scope,
configuration, and output contracts.

`memory_record_outcome` on generic MCP is always `caller_asserted`. When CML
is enabled, it must include the `manifest_sha256` returned by
`memory_prepare_turn`. Authentication and host verification must be supplied by
a separate trusted integration; merely calling the MCP tool is not
host-attested evidence.

---

## CLI reference

Conventions:

- Most memory commands start with `<db-path> <subject_id>`; `checkpoint`,
  `verify`, `mcp`, and the `actions` subcommands have command-specific forms.
- Results print as pretty JSON on stdout; nothing else is written to stdout.
- Exit code 0 on success; `verify` exits 1 when a chain or checkpoint fails;
  any command exits nonzero on error.
- The database file is created on first use; `:memory:` works anywhere a
  path is accepted (useful for smoke tests, useless for persistence).

### `aetnamem remember <db> <subject> <message> [--session S] [--turn T] [--source-type TYPE]`

Runs the full write pipeline: appends an episode, extracts at most one
candidate fact, applies the policy gates (trust → quarantine, dedupe,
supersession), and audits every step. `--source-type` overrides source
classification (`user_message`, `webpage`, `tool_output`) — otherwise
embedded `<webpage>`/`<tool_output>` tags are detected automatically.
Because an explicit override is trusted, do not expose `--source-type` to an
untrusted caller that can relabel tool/web content as `user_message`.

```bash
$ aetnamem remember ./mem.db user-1 "My preferred airport is SFO." --session s1 --turn 1
{
  "duplicate_ids": [],
  "episode_id": "ep_0b0b02…",
  "records": [
    {
      "id": "rec_7c4456…",
      "content": "User's preferred airport is SFO.",
      "fact_key": "preferred airport",
      "status": "active",
      "trust_tier": "trusted_user",
      "source_type": "user_message",
      "source_session_id": "s1",
      "source_turn_id": "1",
      "episode_id": "ep_0b0b02…",
      "confidence": 0.9,
      "created_at": "2026-07-08T23:58:47.962986+00:00",
      "supersedes_id": null,
      …
    }
  ]
}
```

`records` is empty when nothing extractable was said (questions, chit-chat)
— that is normal, not an error. A repeated fact lands in `duplicate_ids`
instead of creating a second record. Records extracted from untrusted
sources appear with `"status": "quarantined"`.

### `aetnamem recall <db> <subject> <query> [--limit N] [--min-score X] [--session S] [--graph]`

Top-k retrieval over **active** records only (quarantined, superseded, and
tombstoned records are never candidates). Prints a JSON array of records,
best first. Every call also writes a retrieval event with a bounded ledger of
candidate score inputs and breakdowns (the first 50 plus every returned
result), digest-bound to its chained recall event. See it via `inspect`.

```bash
aetnamem recall ./mem.db user-1 "Which airport should I book from?" --limit 3
```

With no `--min-score`, recall returns the best `limit` records even if none
matched lexically (using the trust/recency prior).
Set `--min-score 0.5` (range roughly 0–1) to require a real text match.
`--graph` additionally performs bounded entity/edge traversal and blends those
hits with direct record candidates. Graph-derived records include a `graph`
object with edge, relation, depth, score, and path evidence.

### `aetnamem list <db> <subject> [--all]`

Active records, oldest first. `--all` includes `superseded`, `quarantined`,
and `tombstoned` records — the way to find quarantined items awaiting
review.

### `aetnamem forget <db> <subject> (--contains TEXT | --utterance TEXT) [--session S]`

Deletes every active, quarantined, or superseded record whose content contains
the selector (case-insensitive), purging record content, fact key, source
episode text, hot graph objects, and registered cold-history edges.
Archive partition digests are recomputed after deletion. `--utterance` accepts natural language
(`"Forget my preferred airport."`) and reduces it to the selector;
`--contains` is the exact substring form. Exactly one is required — an
empty selector is refused rather than interpreted as "delete everything".
The forget request text itself is not stored as an episode; the audit event
keeps only `utterance_sha256` and `selector_sha256`.

```bash
$ aetnamem forget ./mem.db user-1 --utterance "Forget my preferred airport."
{
  "deleted": true,
  "record_ids": ["rec_7c4456…"],
  "receipt": {
    "format": "aetnamem-deletion-receipt-v1",
    "selector_sha256": "e5a108…",
    "purged_record_ids": ["rec_7c4456…"],
    "purged_episode_ids": ["ep_0b0b02…"],
    "audit_event_id": "aud_e27964…",
    "audit_event_hash": "eb41f8…",
    "receipt_sha256": "bd4653…",
    "subject_id": "user-1",
    "created_at": "2026-07-08T23:58:48.085640+00:00"
  }
}
```

Store the `receipt` with your deletion-request ticket; it is verifiable
against the audit chain forever (rules in
[audit-log-spec.md](audit-log-spec.md)). `"deleted": false` with exit code
0 means nothing matched.

### `aetnamem promote <db> <subject> <record_id> [--session S]`

Activates a quarantined record and records the trust transition (trust tier
becomes `user_confirmed`; supersession applies). The command does not
authenticate who requested or confirmed that transition, so expose it only
through a trusted approval layer when confirmation must be human-controlled.
Errors if the record is not quarantined. Find candidates with `list --all`.

### `aetnamem consolidate <db> <subject>`

Runs the deterministic cleanup pass: exact duplicate active records collapse
to the newest copy, and fact-key conflicts are repaired by superseding older
records. The pass writes a `memory.consolidated` audit event.

### `aetnamem graph-backfill <db> <subject> [--rebuild]`

Indexes existing governed records into the derived entity/edge graph. The
operation is idempotent. `--rebuild` first removes graph rows for that subject;
episodes, records, and their audit history remain canonical and unchanged.
The command prints indexed-record and graph-object counts.

### `aetnamem graph-inspect <db> <subject>`

Prints entities, aliases, edges, merge proposals, archive partitions, and
aggregate counts. This maintenance/debug view includes inactive graph objects.

### `aetnamem graph-consolidate <db> <subject> [--archive-root DIR --archive-before ISO_TIME] [--no-prune]`

Backfills missing derived edges, creates conservative pending merge proposals,
and optionally moves inactive edge history older than the cutoff into
digest-verified SQLite partitions by subject/year. Canonical records and
episodes stay in the primary database. `--no-prune` copies without removing
the inactive hot rows.

### `aetnamem graph-merges` / `graph-merge`

```bash
aetnamem graph-merges ./mem.db user-1 --status pending
aetnamem graph-merge ./mem.db user-1 gmp_ID approve --winner ent_ID
aetnamem graph-merge ./mem.db user-1 gmp_ID reject
aetnamem graph-merge ./mem.db user-1 gmp_ID revert
```

Only exact same-kind name/alias evidence creates proposals. Approval records a
reversible `merged_into` pointer; reject and revert are also audited. The
desktop dashboard exposes pending proposals through its Approvals tab.

### `aetnamem graph-history <db> <subject> [--year YYYY]`

Reads inactive edges from registered archive partitions after verifying each
file's SHA-256 digest. Missing or modified partitions are rejected.

### `aetnamem optimize <db>`

Runs SQLite `PRAGMA optimize`. The desktop maintenance worker also runs this
on its configured schedule.

### `aetnamem persona <db> <subject> [--max-chars N]`

Builds a live-derived `<user_persona>` snapshot from active records. It is
not stored as memory; every line carries the source record id, and the build
is audited as `memory.persona_built`.

### `aetnamem scenes <db> <subject>`

Returns the deterministic L2 scene view: sessions with their episode IDs and
record IDs. This is derived from stored evidence and does not create new
memory.

### `aetnamem propose <db> <subject> [--proposer NAME]`

Reads a JSON array of derived fact proposals from stdin. Proposals must cite
existing evidence IDs and land `quarantined`; they only become active after
`promote`.

```bash
cat proposals.json | aetnamem propose ./mem.db user-1 --proposer nightly-job
```

### `aetnamem log-action <db> <subject> <action_type> [--payload JSON] [--session S] [--turn T]`

Appends an agent action event to the same audit chain as memory events.
Bare action types get an `agent.` prefix (`tool_call` → `agent.tool_call`);
dotted names pass through. Put digests in the payload, not raw content.

```bash
aetnamem log-action ./mem.db user-1 tool_call \
  --payload '{"tool":"calendar.create","args_sha256":"9f2c…"}' --session s1 --turn 3
# → {"event_id": "aud_…"}
```

### `aetnamem inspect <db> <subject>` / `aetnamem audit <db> <subject>`

`inspect` is the full evidence dump: all records (any status), episodes,
retrieval events, the audit log, and `audit_chain_valid`. `audit` is the
subset for audit review (audit log + retrieval events + chain check).
`inspect` output is the machine-readable disclosure for access/portability
requests.

### `aetnamem checkpoint <db> [sink.jsonl]` / `aetnamem verify <db> [--subject S] [--checkpoints sink.jsonl] [--incremental]`

Chain anchoring and verification — semantics, cadence, and anchoring
recipes are in the [auditing guide](auditing-guide.md). `verify` exits 1 on
any failure, so both are cron/CI-ready as-is. `--incremental` hash-checks its
locally cached anchor and verifies only new events. This reduces routine work
but is not an external trust anchor; use checkpoint files in another trust
domain for tail-truncation and database-replacement detection.

### `aetnamem actions …`

The optional guarded-actions commands create and execute causal WorldPatch
transactions:

```text
aetnamem actions stage <db> <subject> filesystem <write_text|delete_file> ...
aetnamem actions show <db> <transaction_id>
aetnamem actions list <db> [--subject SUBJECT]
aetnamem actions approve <db> <transaction_id> --approver-label LABEL
aetnamem actions commit <db> <transaction_id> --root DIRECTORY
aetnamem actions abort <db> <transaction_id>
aetnamem actions recover <db> <transaction_id>
aetnamem actions verify <db> <transaction_id>
aetnamem actions purge-payloads <db> <transaction_id>
aetnamem actions import-journal <db> <subject> <journal.db> --source-id SOURCE
```

`stage --mode observe|preview` records a patch but deliberately cannot
execute it. The default `enforce` mode requires `--authority-id` and
`--authority-digest`, followed by a separately signed approval. Set
`AETNAMEM_APPROVAL_KEY` in the reviewer process or use
`--approval-key-file`; never expose that key to the agent-facing process.
The shared key authenticates key possession, not the `--approver-label` value.
Likewise, `--authority-id/--authority-digest` are trustworthy only when a
trusted host controls staging; the CLI flags do not authenticate themselves.

The complete workflow, guarantees, Python API, and current limitations are
documented in [guarded-actions.md](guarded-actions.md).

---

## MCP server reference

### Running it

```bash
aetnamem mcp [--db PATH] [--subject NAME] [--checkpoints FILE] [--retain-query-text]
```

| flag | default | meaning |
|---|---|---|
| `--db` | `$AETNAMEM_DB`, else `~/.aetnamem/memories.db` | SQLite database (created on demand) |
| `--subject` | `default` | subject used when a tool call omits `subject_id` |
| `--checkpoints` | none | default checkpoint file for the `memory_verify` tool |
| `--retain-query-text` | off | store raw recall queries in retrieval events (debugging only) |

The server speaks MCP over **stdio**: newline-delimited JSON-RPC 2.0, UTF-8,
one message per line. It implements `initialize`, `ping`, `tools/list`, and
`tools/call`, and ignores notifications. stdout carries protocol messages
only; diagnostics go to stderr. No network port is opened, ever — the host
spawns the process and owns its lifetime. Implemented with the Python
standard library only; there are no dependencies to install.

### Host configuration

**Claude Code**

```bash
claude mcp add aetnamem -- aetnamem mcp
```

**Claude Desktop** (`claude_desktop_config.json`) — and any host that takes
the standard `command`/`args` JSON shape, including OpenClaw's MCP bridge
(diagrammed step by step in [openclaw-setup.md](openclaw-setup.md)):

```json
{
  "mcpServers": {
    "aetnamem": {
      "command": "aetnamem",
      "args": ["mcp", "--db", "/home/you/.aetnamem/memories.db", "--subject", "you"]
    }
  }
}
```

If `aetnamem` is not on the host's PATH (common when installed in a venv),
use the absolute path to the console script (`/path/to/venv/bin/aetnamem`)
or `"command": "/path/to/python", "args": ["-m", "aetnamem.cli", "mcp", …]`.

**Multi-user hosts**: pass `subject_id` explicitly on every tool call
instead of relying on `--subject`. This scopes storage queries but is not
authorization: the caller can choose another subject ID. A multi-user gateway
must authenticate the caller, derive the subject server-side, and prevent
cross-subject selection.

### Tool catalog

Every tool returns one `text` content block containing pretty-printed JSON
— the same payloads as the CLI. Tool-level failures (e.g. promoting a
record that isn't quarantined) come back as `isError: true` with a message,
not as protocol errors, so the agent can read and recover.

| tool | required args | optional args | returns |
|---|---|---|---|
| `memory_remember` | `message` | `subject_id`, `source_type`, `session_id`, `turn_id` | `{episode_id, records, duplicate_ids}` |
| `memory_recall` | `query` | `subject_id`, `limit` (10), `min_score`, `session_id`, `use_graph` (false) | array of records, best first; graph hits include path evidence |
| `memory_recall_block` | `query` | `subject_id`, `max_records` (5), `max_chars` (2000), `min_score` (0.3), `session_id`, `use_graph` (false) | `{block, record_ids, count}` — bounded `<relevant_memories>` block; injection is audited |
| `memory_persona` | — | `subject_id`, `max_chars` (1500), `session_id` | `{block, record_ids, count}` — live-derived `<user_persona>` snapshot, audited |
| `memory_context_pack` | `query` | `subject_id`, `persona_max_chars` (600), `recall_max_records` (3), `recall_max_chars` (1200), `min_score` (0.3), `reference_mode` (`compact`), `session_id`, `use_graph` | `aetnamem-context-pack-v1` with stable/dynamic blocks, hashes, full record IDs, budgets, and placement hints |
| `memory_capture` | `role`, `content` | `subject_id`, `tool_name`, `session_id`, `turn_id` | user → full pipeline; assistant/tool\_\* → digest-only audit event |
| `memory_list` | — | `subject_id`, `include_inactive` (false) | array of records |
| `memory_forget` | `contains` *or* `utterance` | `subject_id`, `session_id`, `turn_id` | `{deleted, record_ids, receipt}` |
| `memory_promote` | `record_id` | `subject_id`, `session_id` | the activated record |
| `memory_audit` | — | `subject_id` | `{audit_log, retrieval_events, audit_chain_valid}` |
| `memory_verify` | — | `subject_id`, `checkpoints_path`, `incremental` (false) | `{valid, subjects}` |
| `memory_graph_status` | — | `subject_id` | graph entities, edges, merge proposals, archives, and counts |
| `memory_graph_merges` | — | `subject_id`, `status` | merge proposals; decisions stay on reviewer surfaces |
| `memory_graph_history` | — | `subject_id`, `partition_year` | digest-verified inactive archived edges |
| `memory_log_action` | `action_type` | `subject_id`, `payload`, `session_id`, `turn_id` | `{event_id}` |

Suggested system-prompt guidance for the calling agent:

> Use `memory_remember` when the user states a durable fact or preference,
> and pass the current session/turn ids. Use `memory_recall` before acting
> on assumptions about the user. When the user asks you to forget
> something, call `memory_forget` with their words as `utterance` and show
> them the receipt's `purged_record_ids` count. If `memory_remember`
> returns a record with status `quarantined`, tell the user what was
> extracted and call `memory_promote` only if they confirm.

### Security properties for MCP deployments

- **Deterministic gates run server-side.** Given an honestly supplied source
  type, webpage/tool records quarantine, recognized fact slots supersede, and
  accepted deletion writes a chained event and receipt. The MCP caller can
  choose `source_type`, `subject_id`, and call `memory_promote`, so remote
  authorization and origin attestation still belong in the host/gateway.
- **Tagged indirect instructions are contained, not all prompt injection.**
  Forget intent still embedded in `<webpage>`/`<tool_output>` is rejected, and
  `memory_capture` logs tool/assistant traffic as digests. If an agent strips
  provenance and submits an injected instruction as a plain user operation,
  this local server cannot reconstruct the lost origin.
- **You can audit while it runs.** The database is ordinary SQLite (WAL
  mode): run `aetnamem verify`, `aetnamem checkpoint` (e.g. from cron), or
  `tools/verify_audit.py` against the same file the agent is using.

### Troubleshooting

| symptom | cause / fix |
|---|---|
| host reports the server "didn't respond" | the host may use `Content-Length`-framed (LSP-style) transport instead of newline-delimited JSON; check its logs — file an issue, the transport is one function |
| `spawn aetnamem ENOENT` | console script not on the host's PATH — use the absolute path or `python -m aetnamem.cli mcp` |
| tool result `isError: true` | read the message: missing required argument, unknown record id, or promoting a non-quarantined record |
| empty `records` from `memory_remember` | the message contained no extractable declarative fact (questions never extract) — expected behavior |
| two hosts, one database | supported for reads; SQLite WAL serializes writes, but prefer one writing host or separate `--db` paths per host |

### Wire-level example

What actually crosses stdio (one line per message):

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}
← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"aetnamem","version":"<version>"}}}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}
→ {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"memory_remember","arguments":{"message":"My favorite tea is oolong."}}}
← {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"{ …remember payload… }"}],"isError":false}}
```
