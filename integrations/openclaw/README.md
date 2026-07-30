# OpenClaw plugin: four-memory AetnaMem

> **AetnaMem remembers whether remembering actually helped.**

This README describes experimental npm `0.4.1-experimental.3`, compatible with
Python prerelease `v0.6.1.1a3`.
It adds an opt-in Safe Switch path while preserving the existing hooks and
tools when `safeSwitch.enabled` is false. Memory Impact remains host-side
research infrastructure. See
the repository's [current capability status](../../docs/current-status.md) for
the precise implemented, experimental, and planned boundary.

Gives an OpenClaw assistant one connection to working, semantic, episodic, and
procedural memory. Four-memory orchestration is opt-in; existing auto-recall,
auto-capture, search, and forget behavior remains the compatibility fallback.
Memory operations use the aetnamem engine's quarantine, recognized fact-slot
supersession, logical purge receipts, and hash-chained events. These controls
do not authenticate subject IDs or recover provenance that the host removed;
see the main README's guarantee boundaries.

## How it works

The plugin spawns `aetnamem mcp` as a child process and talks newline-
delimited JSON-RPC over stdio ([src/rpc-client.ts](src/rpc-client.ts)).

| OpenClaw hook | engine call | behavior |
|---|---|---|
| `before_prompt_build` | `memory_persona` | in cache-aware mode, adds a stable `<user_persona>` through `appendSystemContext`; correction, capture, and plugin-driven forgetting invalidate it |
| `before_prompt_build` | `memory_recall_block` | adds query-specific `<relevant_memories>` through `appendContext`; a lexical match is required and the audit retains full record IDs even when the model sees compact references |
| `agent_end` | `memory_capture` | the clean user turn runs the full write pipeline; the assistant reply is logged as a **digest only** (never becomes memory) |
| `before_message_write` | — | strips injected blocks from persisted history so recalls don't feed back |
| tool `aetnamem_search` | `memory_recall` | explicit memory search for the agent |
| tool `aetnamem_forget` | `memory_forget` | deletion on user request, returns the receipt |
| tool `aetnamem_observe` | `memory_observe` | submits a typed, quarantined text observation after OpenClaw analyzes host-controlled media |
| tool `aetnamem_forget_artifact` | `memory_forget_artifact` | purges AetnaMem derivatives of one exact-byte digest on an explicit user request |

With `orchestration.enabled`, `before_prompt_build` instead calls
`memory_prepare_turn`, and `agent_end` closes the run through
`memory_record_outcome`. Capability detection uses MCP `tools/list`; missing
runtime tools fall back to the legacy hooks by default.

Recall failures/timeouts never block a turn — the agent just proceeds
without injection.

With `safeSwitch.enabled`, the plugin instead uses the private trial protocol.
Capture and preview never return model context; canary and active return only
human-approved candidates. Agent-callable AetnaMem tools are not registered in
this mode. A missing or tampered state fails closed to no injection.

The two media tools introduced in npm `0.3.1` remain available in the normal
integration. They do not inspect OpenClaw media
hooks or store media bytes. OpenClaw supplies an exact-byte SHA-256, secretless
host reference, and extractor identity after analysis; AetnaMem preserves
that evidence and quarantines the text. See the repository
[multimodal observation guide](../../docs/multimodal-observations.md).

## Install

### Supported customer installation

```bash
# 1. Install and verify the engine.
python -m pip install --pre aetnamem==0.6.1.1a3
aetnamem --version

# 2. Let the engine install, configure, restart, and verify this bridge.
aetnamem openclaw install

# 3. Review the native mirror. Model context is unchanged.
aetnamem openclaw memory status
aetnamem dashboard
```

The installer records the absolute engine path, so the OpenClaw service does
not have to inherit the interactive shell's Python `PATH`. It installs npm
`0.4.1-experimental.3` internally, starts shadow Safe Switch mode, synchronizes
native Markdown memory into an isolated evidence database, restarts the gateway,
requires a successful RPC probe, and verifies the retained configuration. On
failure it stops the trial and restores the prior plugin configuration.

For an advanced direct four-memory setup, finish evaluating the trial and
restore its baseline first:

```bash
aetnamem trial rollback
aetnamem setup
openclaw aetnamem setup --single-user --subject you \
  --orchestrated --runtime-config ~/.aetnamem/runtime.json
```

`--single-user` describes the supported deployment boundary and is retained in
the public quickstart; current releases accept one fixed `subject` per plugin
instance. Do not use that subject for multiple authenticated users. The setup
command enables the required conversation-hook permission, applies bounded
recall defaults, and restarts the gateway. The supported customer takeover is
instead `aetnamem trial activate`: it freezes and relocates native supplemental
memory, disables duplicate native recall/writing, and preserves an exact
rollback journal.

For repository development, install the Python worktree first, verify its
command, then build and register the local bridge:

```bash
python3 -m pip install -e ../..
aetnamem --version
npm ci
npm run build
openclaw plugins install "$PWD"
```

Direct `openclaw plugins install` is a development/manual recovery path. It
installs only this JavaScript bridge and cannot prove that the Python engine is
available. Customer instructions therefore use `aetnamem openclaw install`.

Register the plugin with OpenClaw (plugin dir or config, per your OpenClaw
version), then configure:

```json
{
  "command": "aetnamem",
  "dbPath": "~/.aetnamem/memories.db",
  "subject": "you",
  "recall": { "maxRecords": 3, "maxChars": 1200, "minScore": 0.3 },
  "persona": { "maxChars": 600 },
  "capture": { "captureAssistant": true },
  "cacheAware": { "enabled": true, "compactReferences": true },
  "tools": { "enabled": true },
  "orchestration": {
    "enabled": true,
    "agentId": "openclaw-primary",
    "runtimeConfig": "~/.aetnamem/runtime.json",
    "fallback": "legacy"
  }
}
```

`openclaw aetnamem setup` in release 0.2.4 enables cache-aware placement
for new configurations.
Existing configurations without `cacheAware.enabled` retain the pre-0.2.4
combined `prependContext` layout. Set `tools.enabled` to `false` only when
automatic recall/capture is sufficient; doing so removes the explicit search
and forget schemas from model context, so forgetting must remain available
through a trusted UI, CLI, or another host control.

In active takeover mode the plugin bounds supplemental memory context and the
native `MEMORY.md`/daily-memory paths are no longer loaded or written.
OpenClaw skills remain procedures; AetnaMem stores and selects the user/project
facts and outcomes that make those procedures task-specific. The dashboard
reports a context-budget projection, not a guaranteed token saving.

## Why this can reduce token use

Without selective memory, durable facts often remain in an always-loaded file
or are repeatedly reconstructed from conversation history. The model receives
that material again on later calls whether the current task needs it or not.

With this plugin, AetnaMem stores durable facts outside the prompt and adds only:

- a persona block capped at **600 characters**;
- at most **3 relevant memories** capped at **1,200 characters total**;
- nothing when recall has no lexical match.

The maximum default memory addition is therefore 1,800 characters—roughly 450
tokens using a simple four-characters-per-token estimate. Actual tokenization
depends on the model and language.

Illustrative calculation, not a measured product claim: if an agent previously
replayed 8,000 tokens of durable memory across 20 model calls, that component
would consume about 160,000 input tokens. Replacing it with a 450-token bounded
pack would consume at most about 9,000 input tokens: roughly 151,000 fewer tokens
for the **memory component**. System prompts, selected skills, tools, current
conversation, outputs, cache writes/reads, and model reasoning are separate.

Prompt caching remains complementary: caching makes an identical repeated
prefix cheaper, while AetnaMem determines which durable information needs to be
in the prompt at all.

## Measured OpenClaw + DeepSeek result

On 2026-07-21 UTC we compared native memory, the pre-0.2.4 AetnaMem layout, and
the cache-aware 0.2.4 release using OpenClaw 2026.7.1-2 and DeepSeek V4 Flash
(thinking off). The synthetic hospital-operations workload contained 94 facts
in a 19,489-character native `MEMORY.md`; each of 10 pre-registered questions
ran twice per arm in a fresh session using a rotating three-arm order.

| Metric | Native `MEMORY.md` | Current AetnaMem | Cache-aware AetnaMem |
|---|---:|---:|---:|
| prompt tokens | 596,581 | 521,858 | **517,118** |
| median prompt tokens / task | 29,829 | 26,076.5 | **25,844.5** |
| cache-read tokens | 243,200 | 158,720 | **158,720** |
| provider-reported cost | $0.056427 | $0.055411 | **$0.054752** |
| correct answers | 20/20 | 20/20 | 20/20 |
| target retrieved | — | 20/20 | 20/20 |

Against native memory, cache-aware AetnaMem used **79,463 fewer prompt tokens
(13.320%)** and cost **2.968% less**. Against the current layout it used 4,740
fewer prompt tokens (0.908%) and cost 1.190% less. Both AetnaMem audit chains
verified.

The cache-aware layout did **not** recover additional absolute cache hits:
current and optimized AetnaMem both received 158,720 cache-read tokens. The
optimized bundle's gain came from reducing model-visible overhead through
compact references and omitted optional tool schemas; this three-arm run does
not isolate how much each change contributed. An earlier 2026-07-20 run found
AetnaMem cost 0.674% more than native under a different observed cache mix.
Together the runs show why cache state, tokens, cost, and correctness must be
reported separately rather than turning one bill into a universal claim.

This is measured evidence, not a universal savings promise or a clinical
pilot. It covers one model, one OpenClaw release, 20 matched tasks per arm, and
a synthetic mature memory. See the [machine-readable trials and full method](https://github.com/aetna000/aetnamem/tree/main/bench/openclaw_memory/results),
the [pre-registered cases](https://github.com/aetna000/aetnamem/blob/main/bench/openclaw_memory/cases.json),
and the [benchmark protocol](https://github.com/aetna000/aetnamem/tree/main/bench/openclaw_memory).

## Two-minute memory demo

After the three install commands, tell the OpenClaw assistant:

```text
Remember that production PostgreSQL requires sslmode=verify-full.
```

Start a new session, then ask:

```text
What SSL mode does production PostgreSQL require?
```

The plugin captures the user-stated fact after the first turn and injects the
matching bounded memory before the second answer. Then test lifecycle behavior:

```text
Use sslmode=require instead going forward.
Forget the PostgreSQL SSL preference.
```

The correction supersedes the recognized fact slot; forgetting returns a
deletion receipt. Independently verify the audit chain with:

```bash
aetnamem verify ~/.aetnamem/memories.db
```

## Measure your real savings

Use the same tasks, model, tools, and fresh-session policy for both runs:

1. Before installation, record `/context detail` and provider-reported input,
   cache-read, and output tokens for 10 representative tasks.
2. Install AetnaMem, exercise the demo above, and confirm recall works.
3. Back up `MEMORY.md`; remove only durable facts now verified in AetnaMem.
   Keep bootstrap instructions and active working state.
4. Disable any overlapping third-party auto-memory injection.
5. Repeat the same 10 tasks in fresh sessions and compare medians as well as
   task success. Do not compare token counts alone.

Report results separately. Count prompt tokens as uncached input plus
cache-read tokens; otherwise a cache hit is mistaken for removed context:

| Metric | Before | With AetnaMem | Change |
|---|---:|---:|---:|
| median prompt tokens per task | | | |
| median uncached input tokens | | | |
| median cache-read tokens | | | |
| successful tasks / 10 | | | |
| stale-memory errors | | | |
| median latency | | | |

Savings are not automatic if the old memory remains loaded. Adding AetnaMem on
top of unchanged native memory can increase tokens slightly. The plugin does
not shorten `SKILL.md` files or choose skills; OpenClaw still owns procedural
skills, while AetnaMem supplies bounded facts, decisions, constraints, and past
outcomes relevant to their execution.

If `aetnamem` is not on OpenClaw's PATH, set `command` to the absolute venv
path, or use `"command": "/path/to/python"` with
`"commandArgs": ["-m", "aetnamem.cli", "mcp", "--db", "...", "--subject", "you"]`.

## Verify development builds end-to-end

```bash
npm run smoke        # drives the real engine through every call the plugin makes
```

Because the database is plain aetnamem SQLite, the memory audit loop works
while OpenClaw runs:

```bash
aetnamem verify ~/.aetnamem/memories.db
aetnamem checkpoint ~/.aetnamem/memories.db ~/checkpoints.jsonl   # cron + anchor
aetnamem consolidate ~/.aetnamem/memories.db you                  # dedupe/repair pass
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
