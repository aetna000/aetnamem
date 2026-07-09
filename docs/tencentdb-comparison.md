# aetnamem vs TencentDB Agent Memory

This comparison uses:

- `aetnamem` current repo, Python package + CLI + MCP server.
- `/Users/javadtaghia/gitlab/TencentDB-Agent-Memory_TWO`, branch
  `fix-memory-safety-controls`, commit `ea82976`.
- MemoryStackBench `seven_sins_v0_1`.

## Short version

TencentDB Agent Memory is a broader OpenClaw-native memory system. It does
automatic capture, long-horizon context offload, L0/L1/L2/L3 layering,
persona/scene generation, and symbolic Mermaid task-state compression. It is
closer to a full OpenClaw memory plugin and context engine.

aetnamem is narrower but sharper: auditable memory as an engine. It is built
around explicit verbs, provenance, quarantine, deletion receipts, hash-chained
audit events, external checkpoints, and a standalone verifier. It is easier to
install outside OpenClaw and easier to reason about in compliance/audit terms.

The right positioning is not "TencentDB is bad." It is:

> TencentDB optimizes for agent productivity and context compression.
> aetnamem optimizes for auditable trust, deletion, and explainable memory
> behavior across any agent host.

## Benchmark result

Local run against `seven_sins_v0_1`:

| target | local checkout | score |
|---|---:|---:|
| aetnamem | current repo | 33/33 |
| TencentDB Agent Memory | `fix-memory-safety-controls` / `ea82976` | 33/33 |

Important context: the checked-in MemoryStackBench site result for TencentDB
Agent Memory was older and showed 26/33, failing webpage poisoning, stale
temporal inspection, and deletion retention. The local TencentDB branch I
tested includes memory-safety fixes and now passes this suite.

So the current comparison should focus on product architecture, speed,
operational simplicity, and integration model rather than only the benchmark
score.

## Architecture

### TencentDB Agent Memory

Architecture shape:

- Node/OpenClaw plugin.
- OpenClaw startup activation.
- OpenClaw hooks for before-prompt recall and after-turn capture.
- Standalone HTTP gateway for Hermes/sidecar usage.
- L0 raw conversations.
- L1 structured memories extracted by LLM.
- L2 scene blocks.
- L3 persona/profile.
- Optional context offload that replaces long tool traces with Mermaid
  symbolic state and file-backed drill-down.
- SQLite + FTS/sqlite-vec locally, Tencent Cloud VectorDB path available.

Strength:

- Deep OpenClaw integration.
- Automatic memory capture, not dependent on the agent remembering to call
  `memory_remember`.
- Richer long-term memory model: scenes/personas/SOP-like abstractions.
- Context compression/offload is a real differentiator for long tool-heavy
  sessions.
- Better fit if the target user lives inside OpenClaw and wants the plugin to
  invisibly improve agent performance.

Weakness:

- Much larger moving surface: Node 22, OpenClaw plugin APIs, postinstall patch,
  gateway, scheduler, LLM extraction pipeline, optional embeddings, offload
  state, local files, SQLite/vector store, profile sync.
- Harder to audit end to end because behavior emerges from hooks, background
  jobs, LLM extractors, and layered files.
- Deletion semantics are more complex because L0, L1, L2/L3, raw conversation
  search, and offload artifacts can all contain related evidence.
- It is tied closely to OpenClaw/Hermes unless run through its gateway.

### aetnamem

Architecture shape:

- Python package.
- Zero-runtime-dependency engine.
- CLI and MCP server.
- Explicit six memory verbs plus promote, log-action, checkpoint, verify.
- SQLite by default.
- Records + episodes + retrieval events + audit log.
- Trust policy gates: source classification, quarantine, dedupe,
  supersession, forget/purge.
- Hash-chained audit events and external checkpoint support.
- Standalone verifier that does not import the engine.

Strength:

- Easier to inspect and prove.
- Stronger audit/compliance story: deletion receipts, digest-only audit plane,
  chain verification, checkpoint verification, standalone verifier.
- Easier install path outside OpenClaw: `pip install aetnamem`.
- Works with any MCP host, not just OpenClaw.
- Deterministic v0 behavior makes failures debuggable.
- Much smaller runtime and operational footprint.

Weakness:

- It does not yet have TencentDB's automatic OpenClaw hook integration.
- It does not yet do context offload / Mermaid symbolic compression.
- It does not yet build L2 scenes or L3 persona summaries.
- With MCP alone, the agent must call memory tools correctly unless the host or
  prompt makes that automatic.

## Speed

The speed profiles are fundamentally different.

### aetnamem

Fast path:

- in-process Python or stdio MCP
- deterministic extraction
- local SQLite writes
- local FTS/ranking
- no LLM call on write/recall

For the seven-sins benchmark, aetnamem completed essentially immediately in
the local run.

Expected production feel:

- memory write: milliseconds
- recall: milliseconds to low tens of milliseconds for small local stores
- verify/checkpoint: depends on database size, but local and deterministic

### TencentDB Agent Memory

Fast path:

- OpenClaw hook calls into plugin.
- Recall can be bounded by `recall.timeoutMs`.
- Capture can write L0 quickly.

Slow path:

- L1 extraction uses an LLM.
- L2/L3 summarization/persona generation uses LLMs.
- Benchmark adapter starts a standalone gateway and flushes sessions so L1
  extraction completes.

For the local seven-sins benchmark, TencentDB was much slower than aetnamem
because it exercised gateway startup plus LLM extraction/flush per scenario.
That does not mean OpenClaw runtime recall is always slow; it means safety
validation has a higher operational cost because memory formation is LLM and
pipeline dependent.

## Quality

TencentDB can produce richer memory quality when the LLM extraction works:

- higher-level scenes
- persona summaries
- workflow/SOP-style memory
- compact symbolic task state

aetnamem produces narrower but more controlled memory quality:

- explicit factual records
- clear provenance
- deterministic updates
- visible quarantine
- deletion receipts
- auditable recall events

For your product thesis, aetnamem's quality bar should be "can prove why this
memory exists and why it was returned." TencentDB's quality bar is "does this
help a long-running OpenClaw agent perform better with less context?"

Those are different games.

## OpenClaw integration

TencentDB currently wins on native OpenClaw ergonomics.

It is an OpenClaw plugin with startup activation, config schema, tool
contracts, hooks, auto-capture, auto-recall, and optional context offload. A
user enables the plugin and memory becomes part of the runtime.

aetnamem is easier to install generally, but its OpenClaw path is currently
MCP-based:

```json
{
  "mcpServers": {
    "aetnamem": {
      "command": "aetnamem",
      "args": ["mcp", "--db", "~/.aetnamem/memories.db", "--subject", "you"]
    }
  }
}
```

That is portable and clean, but less automatic. The agent must use
`memory_remember`, `memory_recall`, and `memory_log_action` at the right times.

## Recommendation

Do not try to clone TencentDB's whole architecture first. That would move
aetnamem away from its strongest wedge.

Instead:

1. Keep aetnamem's core as the audit-grade memory engine.
2. Add an OpenClaw-native adapter/plugin layer that automatically calls the
   existing engine.
3. Add optional context-offload later, but make its artifacts audit-visible and
   deletion-aware from day one.

The most valuable next feature is not L2/L3 persona. It is:

> an OpenClaw plugin wrapper for aetnamem that auto-captures, auto-recalls,
> logs tool calls, and writes checkpoints, while preserving the same audit
> receipts and standalone verifier.

That would close TencentDB's biggest integration advantage without losing
aetnamem's audit advantage.

## Benchmarking next

The seven-sins benchmark is now not enough to separate the two current local
branches. Add comparison suites for:

- latency: recall p50/p95, write p50/p95, session flush time
- token cost: prompt tokens injected per turn
- OpenClaw automation: does memory work without explicit tool-calling?
- audit completeness: can an external verifier reconstruct memory mutations,
  recalls, deletions, and tool calls?
- deletion blast radius: does forget purge L0, L1, L2/L3, offload refs, and
  recall logs where applicable?
- poisoning variants: webpage, tool output, email, search result, quoted text,
  and assistant-generated summaries
- long-horizon usefulness: repeated task sessions where context offload and
  persona/scene memory can actually help

Expected outcome:

- TencentDB should do well on OpenClaw automation, context compression, and
  long-horizon productivity.
- aetnamem should do well on auditability, deletion proof, portability, and
  deterministic safety.

That contrast is useful. It tells us what to build next.
