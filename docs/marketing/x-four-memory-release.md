# X article — AetnaMem 0.5.0: memory that has to earn its place

AI agents do not have one kind of memory.

They have at least four:

- **Working memory:** what am I doing now?
- **Semantic memory:** what facts do I know?
- **Episodic memory:** what happened last time?
- **Procedural memory:** how should I do this?

Today those memories are usually scattered across the context window,
`MEMORY.md`, conversation history, traces, and `SKILL.md` files.

That fragmentation creates two problems.

First, setup becomes a project of its own. The agent host has to coordinate
different files, stores, hooks, and retrieval rules.

Second, memory gets confused with usefulness. A system can prove that it
retrieved a memory, but not that the memory improved the result.

## Four memories, one connection

AetnaMem 0.5.0 gives OpenClaw and any MCP-capable agent one local-first memory
runtime:

| Memory | Agent-native form | AetnaMem form |
|---|---|---|
| Working | Context window or scratchpad | Task snapshots in `memory.db` |
| Semantic | `MEMORY.md` or profile | Governed facts in `memory.db` |
| Episodic | History and traces | Outcomes and reviewed lessons in `memory.db` |
| Procedural | `SKILL.md` or runbook | Versioned skill index; source file stays on disk |

The agent receives one bounded context pack containing the current state,
relevant facts, useful experience, and the right procedure.

Existing integrations remain compatible. Four-memory orchestration is opt-in,
and the original Python `Memory`, CLI, and default MCP catalog remain in place.

## What we measured

We compared native OpenClaw `MEMORY.md` with the same durable facts behind
AetnaMem’s bounded, audited recall.

The checked-in experiment used:

- OpenClaw 2026.7.1-2;
- DeepSeek V4 Flash with thinking off;
- 94 durable facts in a 19,489-character native memory;
- 10 pre-registered questions, each run twice in fresh sessions;
- rotating arm order;
- provider-reported tokens and cost;
- exact-answer scoring and retrieval evidence.

Results:

| Metric | Native `MEMORY.md` | AetnaMem cache-aware |
|---|---:|---:|
| Prompt tokens | 596,581 | **517,118** |
| Provider-reported cost | $0.056427 | **$0.054752** |
| Correct answers | 20/20 | **20/20** |
| Target retrieved | — | **20/20** |

In this workload, AetnaMem used **79,463 fewer prompt tokens—13.320%—and cost
2.968% less**, while both arms remained 20/20 correct.

The audit chain also verified.

This is a measured result, not a universal savings promise. It is one
synthetic workload, one model, and one host. The optimized bundle changed
placement, reference size, and optional tool-schema overhead together, so the
experiment does not assign the gain to one isolated mechanism.

Raw evidence and protocol:

https://github.com/aetna000/aetnamem/tree/main/bench/openclaw_memory

## The next question: did remembering actually help?

Retrieval is not impact.

If an agent succeeds after receiving a memory, it may have succeeded without
it. That is why AetnaMem now includes the default-off experimental foundation
for **Memory Impact**, technically called the Causal Memory Ledger.

“Causal” simply means cause and effect:

> Did giving the agent this eligible memory change the verified outcome?

The ledger can commit which memory contributions were candidates, which were
assigned, which were actually shown, and which reported outcome followed.
Shadow mode records assignments without changing the agent’s context. Actual
withholding is restricted to the benchmark preset.

The instrumentation is real. The causal result is not yet claimed. The
planted-effect benchmark, estimators, Grok CLI study, and held-out evaluation
remain the falsifiable next phase.

## Install

The Python package remains one normal install—no snapshot package, no sudo,
and no separate runtime:

```bash
pip install aetnamem
```

For OpenClaw:

```bash
openclaw plugins install npm:openclaw-memory-aetnamem@latest --pin
aetnamem setup
openclaw aetnamem setup --single-user --subject you
```

The published cache-aware OpenClaw path above is the path used for the measured
comparison. Full four-memory OpenClaw orchestration additionally requires npm
plugin v0.3.0; verify that `@latest` resolves to v0.3.0 before adding
`--orchestrated --runtime-config ~/.aetnamem/runtime.json`. Generic MCP hosts
can use the v0.5.0 runtime directly with `aetnamem runtime mcp`.

Repository:

https://github.com/aetna000/aetnamem

**AetnaMem remembers whether remembering actually helped.**

#AI #AIAgents #OpenClaw #MCP #AgentMemory #OpenSource
