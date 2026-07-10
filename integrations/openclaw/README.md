# OpenClaw plugin: memory-aetnamem

Gives an OpenClaw assistant automatic, auditable memory: auto-recall before
prompts, auto-capture after turns, and agent-callable search and forget tools.
Memory operations use the aetnamem engine's quarantine, recognized fact-slot
supersession, logical purge receipts, and hash-chained events. These controls
do not authenticate subject IDs or recover provenance that the host removed;
see the main README's guarantee boundaries.

## How it works

The plugin spawns `aetna000 mcp` as a child process and talks newline-
delimited JSON-RPC over stdio ([src/rpc-client.ts](src/rpc-client.ts)).

| OpenClaw hook | engine call | behavior |
|---|---|---|
| `before_prompt_build` | `memory_persona` | injects a `<user_persona>` snapshot (stable fact slots first, provenance ids on every line), cached with a TTL and invalidated whenever new memory is captured |
| `before_prompt_build` | `memory_recall_block` | injects a bounded `<relevant_memories>` block; a lexical match is required (`minScore` 0.3), and the engine audits exactly which record IDs entered context |
| `agent_end` | `memory_capture` | the clean user turn runs the full write pipeline; the assistant reply is logged as a **digest only** (never becomes memory) |
| `before_message_write` | — | strips injected blocks from persisted history so recalls don't feed back |
| tool `aetnamem_search` | `memory_recall` | explicit memory search for the agent |
| tool `aetnamem_forget` | `memory_forget` | deletion on user request, returns the receipt |

Recall failures/timeouts never block a turn — the agent just proceeds
without injection.

## Install

```bash
pip install aetnamem                       # the engine
cd integrations/openclaw
npm install && npm run build               # → dist/index.mjs
```

Register the plugin with OpenClaw (plugin dir or config, per your OpenClaw
version), then configure:

```json
{
  "command": "aetna000",
  "dbPath": "~/.aetnamem/memories.db",
  "subject": "you",
  "recall": { "maxRecords": 5, "maxChars": 2000, "minScore": 0.3 },
  "capture": { "captureAssistant": true }
}
```

If `aetna000` is not on OpenClaw's PATH, set `command` to the absolute venv
path, or use `"command": "/path/to/python"` with
`"commandArgs": ["-m", "aetnamem.cli", "mcp", "--db", "...", "--subject", "you"]`.

## Verify it end-to-end

```bash
npm run smoke        # drives the real engine through every call the plugin makes
```

Because the database is plain aetnamem SQLite, the memory audit loop works
while OpenClaw runs:

```bash
aetna000 verify ~/.aetnamem/memories.db
aetna000 checkpoint ~/.aetnamem/memories.db ~/checkpoints.jsonl   # cron + anchor
aetna000 consolidate ~/.aetnamem/memories.db you                  # dedupe/repair pass
```

## Notes

- The hook/tool contracts (`before_prompt_build` → `{prependContext}`,
  `agent_end` event shape, `registerTool` with `execute(toolCallId, params)`)
  follow OpenClaw's plugin SDK; [src/types.ts](src/types.ts) declares them
  structurally so the plugin builds without the SDK installed. If your
  OpenClaw version renames a hook, adjust `index.ts` — everything else is
  host-neutral.
- Assistant replies are captured as SHA-256 digests by design. If you want
  assistant-stated facts to become memory, that must go through quarantine +
  promote, not auto-capture.
