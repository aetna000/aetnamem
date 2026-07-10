# Integration guide: CLI and MCP

aetnamem has four integration surfaces. Pick by what your host can do:

| surface | use when | ships since |
|---|---|---|
| Python library (`from aetnamem import Memory`) | your agent runs Python | v0 |
| Guarded Actions (`from aetnamem.actions import ActionEngine`) | your Python host can enforce a protected execution boundary | v0 |
| CLI (`aetna000 <verb> …`) | your agent can run shell commands (OpenClaw skills, cron, CI) | v0 |
| memory MCP server (`aetna000 mcp`) | your host speaks MCP and needs memory tools | v0 |

The memory Python, CLI, and MCP surfaces drive the same `Memory` engine.
Guarded Actions is adjacent and shares its store/audit chain, but the current
MCP server does not intercept or mediate unrelated action tools. Library API
usage is covered in the
[README](../README.md); audit workflows in the
[auditing guide](auditing-guide.md). This document specifies the CLI and
MCP surfaces.

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

### `aetna000 remember <db> <subject> <message> [--session S] [--turn T] [--source-type TYPE]`

Runs the full write pipeline: appends an episode, extracts at most one
candidate fact, applies the policy gates (trust → quarantine, dedupe,
supersession), and audits every step. `--source-type` overrides source
classification (`user_message`, `webpage`, `tool_output`) — otherwise
embedded `<webpage>`/`<tool_output>` tags are detected automatically.
Because an explicit override is trusted, do not expose `--source-type` to an
untrusted caller that can relabel tool/web content as `user_message`.

```bash
$ aetna000 remember ./mem.db user-1 "My preferred airport is SFO." --session s1 --turn 1
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

### `aetna000 recall <db> <subject> <query> [--limit N] [--min-score X] [--session S]`

Top-k retrieval over **active** records only (quarantined, superseded, and
tombstoned records are never candidates). Prints a JSON array of records,
best first. Every call also writes a retrieval event with per-candidate
score breakdowns — see it via `inspect`.

```bash
aetna000 recall ./mem.db user-1 "Which airport should I book from?" --limit 3
```

With no `--min-score`, recall has vector-store semantics: it returns the
best `limit` records even if none matched lexically (trust/recency prior).
Set `--min-score 0.5` (range roughly 0–1) to require a real text match.

### `aetna000 list <db> <subject> [--all]`

Active records, oldest first. `--all` includes `superseded`, `quarantined`,
and `tombstoned` records — the way to find quarantined items awaiting
review.

### `aetna000 forget <db> <subject> (--contains TEXT | --utterance TEXT) [--session S]`

Deletes every active or quarantined record whose content contains the
selector (case-insensitive), purging record content, fact key, and the
source episode text. `--utterance` accepts natural language
(`"Forget my preferred airport."`) and reduces it to the selector;
`--contains` is the exact substring form. Exactly one is required — an
empty selector is refused rather than interpreted as "delete everything".
The forget request text itself is not stored as an episode; the audit event
keeps only `utterance_sha256` and `selector_sha256`.

```bash
$ aetna000 forget ./mem.db user-1 --utterance "Forget my preferred airport."
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

### `aetna000 promote <db> <subject> <record_id> [--session S]`

Activates a quarantined record after the user has explicitly confirmed it
(trust tier becomes `user_confirmed`; supersession applies). Errors if the
record is not quarantined. Find candidates with `list --all`.

### `aetna000 consolidate <db> <subject>`

Runs the deterministic cleanup pass: exact duplicate active records collapse
to the newest copy, and fact-key conflicts are repaired by superseding older
records. The pass writes a `memory.consolidated` audit event.

### `aetna000 persona <db> <subject> [--max-chars N]`

Builds a live-derived `<user_persona>` snapshot from active records. It is
not stored as memory; every line carries the source record id, and the build
is audited as `memory.persona_built`.

### `aetna000 scenes <db> <subject>`

Returns the deterministic L2 scene view: sessions with their episode IDs and
record IDs. This is derived from stored evidence and does not create new
memory.

### `aetna000 propose <db> <subject> [--proposer NAME]`

Reads a JSON array of derived fact proposals from stdin. Proposals must cite
existing evidence IDs and land `quarantined`; they only become active after
`promote`.

```bash
cat proposals.json | aetna000 propose ./mem.db user-1 --proposer nightly-job
```

### `aetna000 log-action <db> <subject> <action_type> [--payload JSON] [--session S] [--turn T]`

Appends an agent action event to the same audit chain as memory events.
Bare action types get an `agent.` prefix (`tool_call` → `agent.tool_call`);
dotted names pass through. Put digests in the payload, not raw content.

```bash
aetna000 log-action ./mem.db user-1 tool_call \
  --payload '{"tool":"calendar.create","args_sha256":"9f2c…"}' --session s1 --turn 3
# → {"event_id": "aud_…"}
```

### `aetna000 inspect <db> <subject>` / `aetna000 audit <db> <subject>`

`inspect` is the full evidence dump: all records (any status), episodes,
retrieval events, the audit log, and `audit_chain_valid`. `audit` is the
subset for audit review (audit log + retrieval events + chain check).
`inspect` output is the machine-readable disclosure for access/portability
requests.

### `aetna000 checkpoint <db> [sink.jsonl]` / `aetna000 verify <db> [--subject S] [--checkpoints sink.jsonl]`

Chain anchoring and verification — semantics, cadence, and anchoring
recipes are in the [auditing guide](auditing-guide.md). `verify` exits 1 on
any failure, so both are cron/CI-ready as-is.

### `aetna000 actions …`

The optional guarded-actions commands create and execute causal WorldPatch
transactions:

```text
aetna000 actions stage <db> <subject> filesystem <write_text|delete_file> ...
aetna000 actions show <db> <transaction_id>
aetna000 actions list <db> [--subject SUBJECT]
aetna000 actions approve <db> <transaction_id> --approver-label LABEL
aetna000 actions commit <db> <transaction_id> --root DIRECTORY
aetna000 actions abort <db> <transaction_id>
aetna000 actions recover <db> <transaction_id>
aetna000 actions verify <db> <transaction_id>
aetna000 actions purge-payloads <db> <transaction_id>
aetna000 actions import-journal <db> <subject> <journal.db> --source-id SOURCE
```

`stage --mode observe|preview` records a patch but deliberately cannot
execute it. The default `enforce` mode requires `--authority-id` and
`--authority-digest`, followed by a separately signed approval. Set
`AETNA000_APPROVAL_KEY` in the reviewer process or use
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
aetna000 mcp [--db PATH] [--subject NAME] [--checkpoints FILE] [--retain-query-text]
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
claude mcp add aetnamem -- aetna000 mcp
```

**Claude Desktop** (`claude_desktop_config.json`) — and any host that takes
the standard `command`/`args` JSON shape, including OpenClaw's MCP bridge
(diagrammed step by step in [openclaw-setup.md](openclaw-setup.md)):

```json
{
  "mcpServers": {
    "aetnamem": {
      "command": "aetna000",
      "args": ["mcp", "--db", "/home/you/.aetnamem/memories.db", "--subject", "you"]
    }
  }
}
```

If `aetna000` is not on the host's PATH (common when installed in a venv),
use the absolute path to the console script (`/path/to/venv/bin/aetna000`)
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
  mode): run `aetna000 verify`, `aetna000 checkpoint` (e.g. from cron), or
  `tools/verify_audit.py` against the same file the agent is using.

### Troubleshooting

| symptom | cause / fix |
|---|---|
| host reports the server "didn't respond" | the host may use `Content-Length`-framed (LSP-style) transport instead of newline-delimited JSON; check its logs — file an issue, the transport is one function |
| `spawn aetna000 ENOENT` | console script not on the host's PATH — use the absolute path or `python -m aetnamem.cli mcp` |
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
