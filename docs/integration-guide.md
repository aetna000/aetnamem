# Integration guide: CLI and MCP

aetnamem has three integration surfaces. Pick by what your host can do:

| surface | use when | ships since |
|---|---|---|
| Python library (`from aetnamem import Memory`) | your agent runs Python | v0 |
| CLI (`aetnamem <verb> …`) | your agent can run shell commands (OpenClaw skills, cron, CI) | v0 |
| MCP server (`aetnamem mcp`) | your host speaks the Model Context Protocol (Claude Code, Claude Desktop, OpenClaw's MCP bridge, …) | v0 |

All three drive the identical engine and policy gates: trust-tiered writes
with quarantine, fact-slot supersession, verifiable deletion with receipts,
and the hash-chained audit log. Library API usage is covered in the
[README](../README.md); audit workflows in the
[auditing guide](auditing-guide.md). This document specifies the CLI and
MCP surfaces.

---

## CLI reference

Conventions:

- First two arguments are always `<db-path> <subject_id>` (except
  `checkpoint`, `verify`, and `mcp`).
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

### `aetnamem recall <db> <subject> <query> [--limit N] [--min-score X] [--session S]`

Top-k retrieval over **active** records only (quarantined, superseded, and
tombstoned records are never candidates). Prints a JSON array of records,
best first. Every call also writes a retrieval event with per-candidate
score breakdowns — see it via `inspect`.

```bash
aetnamem recall ./mem.db user-1 "Which airport should I book from?" --limit 3
```

With no `--min-score`, recall has vector-store semantics: it returns the
best `limit` records even if none matched lexically (trust/recency prior).
Set `--min-score 0.5` (range roughly 0–1) to require a real text match.

### `aetnamem list <db> <subject> [--all]`

Active records, oldest first. `--all` includes `superseded`, `quarantined`,
and `tombstoned` records — the way to find quarantined items awaiting
review.

### `aetnamem forget <db> <subject> (--contains TEXT | --utterance TEXT) [--session S]`

Deletes every active or quarantined record whose content contains the
selector (case-insensitive), purging record content, fact key, and the
source episode text. `--utterance` accepts natural language
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

Activates a quarantined record after the user has explicitly confirmed it
(trust tier becomes `user_confirmed`; supersession applies). Errors if the
record is not quarantined. Find candidates with `list --all`.

### `aetnamem consolidate <db> <subject>`

Runs the deterministic cleanup pass: exact duplicate active records collapse
to the newest copy, and fact-key conflicts are repaired by superseding older
records. The pass writes a `memory.consolidated` audit event.

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

### `aetnamem checkpoint <db> [sink.jsonl]` / `aetnamem verify <db> [--subject S] [--checkpoints sink.jsonl]`

Chain anchoring and verification — semantics, cadence, and anchoring
recipes are in the [auditing guide](auditing-guide.md). `verify` exits 1 on
any failure, so both are cron/CI-ready as-is.

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
instead of relying on `--subject`. Isolation is enforced per subject at the
storage layer.

### Tool catalog

Every tool returns one `text` content block containing pretty-printed JSON
— the same payloads as the CLI. Tool-level failures (e.g. promoting a
record that isn't quarantined) come back as `isError: true` with a message,
not as protocol errors, so the agent can read and recover.

| tool | required args | optional args | returns |
|---|---|---|---|
| `memory_remember` | `message` | `subject_id`, `source_type`, `session_id`, `turn_id` | `{episode_id, records, duplicate_ids}` |
| `memory_recall` | `query` | `subject_id`, `limit` (10), `min_score`, `session_id` | array of records, best first |
| `memory_recall_block` | `query` | `subject_id`, `max_records` (5), `max_chars` (2000), `min_score` (0.3), `session_id` | `{block, record_ids, count}` — bounded `<relevant_memories>` block; injection is audited |
| `memory_persona` | — | `subject_id`, `max_chars` (1500), `session_id` | `{block, record_ids, count}` — live-derived `<user_persona>` snapshot, audited |
| `memory_capture` | `role`, `content` | `subject_id`, `tool_name`, `session_id`, `turn_id` | user → full pipeline; assistant/tool\_\* → digest-only audit event |
| `memory_list` | — | `subject_id`, `include_inactive` (false) | array of records |
| `memory_forget` | `contains` *or* `utterance` | `subject_id`, `session_id`, `turn_id` | `{deleted, record_ids, receipt}` |
| `memory_promote` | `record_id` | `subject_id`, `session_id` | the activated record |
| `memory_audit` | — | `subject_id` | `{audit_log, retrieval_events, audit_chain_valid}` |
| `memory_verify` | — | `subject_id`, `checkpoints_path` | `{valid, subjects}` |
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

- **The policy gates are server-side.** The calling agent only sees the
  verbs; it cannot write an active record from webpage content, cannot skip
  supersession, and cannot delete without generating a chained audit event
  and receipt.
- **Prompt injection cannot reach deletion or durable memory.** Forget
  intent inside `<webpage>`/`<tool_output>` content is ignored by design,
  and untrusted extractions quarantine.
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
