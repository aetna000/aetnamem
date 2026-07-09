# Introducing aetnamem: auditable memory for agents

Today I published `aetnamem` v0.1.0, an open-source memory engine for agents
built around a simple claim: memory should be auditable.

Agent memory is quickly becoming infrastructure. Assistants remember user
preferences, tools write facts into stores, webpages get summarized, and
retrieval quietly shapes what the next model call sees. That is useful, but it
also creates a problem: if an agent remembers the wrong thing, keeps something
after deletion, or lets untrusted webpage text become durable memory, you need
more than vibes to debug it.

You need evidence.

`aetnamem` is my attempt to make that evidence a first-class part of the memory
layer.

## What it does

`aetnamem` is a local-first Python package and MCP server. It stores memory in
one SQLite file by default, has no runtime dependencies, and exposes the same
engine through:

- a Python API
- a CLI
- an MCP server for agent hosts

Install it:

```bash
pip install aetnamem
```

Use it from Python:

```python
from aetnamem import Memory

m = Memory("./memories.db")

m.remember("user-1", "My preferred airport is SFO.", session_id="s1")
m.remember(
    "user-1",
    "Actually, use OAK as my preferred airport going forward.",
    session_id="s2",
)

print(m.recall("user-1", "Which airport should I use?"))

receipt = m.forget("user-1", utterance="Forget my preferred airport.")
print(receipt)
```

Run it as an MCP server:

```bash
aetnamem mcp --db ~/.aetnamem/memories.db --subject you
```

Any MCP host can then use tools such as `memory_remember`, `memory_recall`,
`memory_forget`, `memory_audit`, `memory_verify`, and `memory_log_action`.

## The design principle

Most memory systems optimize for recall first. `aetnamem` optimizes for
accountability first.

Every semantic record carries provenance:

- source type
- source session
- source turn
- timestamp
- confidence
- link back to the raw episode it came from

Untrusted content is not treated like user memory. Facts extracted from
webpages or tool output are quarantined and only become active after explicit
promotion.

Updates supersede old facts instead of silently overwriting them. If the user
says their preferred airport changed from SFO to OAK, the old record becomes
`superseded`; it is inspectable, but it is not returned by recall.

Deletion is designed to be real. `forget()` tombstones matching records, purges
their content and source episode text, and returns a deletion receipt bound to
the audit chain.

## The audit layer

The audit log is hash-chained per subject. Every mutation and recall produces
an event. Agent actions can join that same chain through `log_action()`, so the
system can record not just what the agent remembered, but what it read, called,
decided, forgot, and returned.

The audit plane stores digests, not raw user content. This matters because an
immutable log should not become a reason deletion is fake.

There is also a standalone verifier:

```bash
python tools/verify_audit.py ./memories.db --checkpoints ./checkpoints.jsonl
```

That verifier uses only the Python standard library and does not import
`aetnamem`. The goal is to make audit checks independent from the engine being
audited.

## Benchmarked against memory failure modes

The development loop is benchmark-driven. `aetnamem` is gated against
MemoryStackBench's `seven_sins_v0_1` suite, which tests failure modes such as:

- webpage memory poisoning
- stale temporal updates
- retention after deletion
- missing provenance
- overgeneralization

Current score: **33/33**.

That number is not the whole product, but it is the right starting line. A
memory layer should be able to prove basic trust, deletion, and provenance
behavior before adding more integrations.

## Why local-first

The default backend is SQLite because local agent memory should be easy to run,
inspect, copy, and audit. One file is a good developer experience and a good
debugging surface.

SQLite is not the end state for every deployment. The long-term roadmap
includes server mode, Postgres, Firestore, retention policies, and stronger
external checkpointing. But the core contract should stay the same:

the same memory event should be explainable locally, in CI, and in production.

## Links

- PyPI: https://pypi.org/project/aetnamem/
- GitHub: https://github.com/aetna000/aetnamem
- Install: `pip install aetnamem`

`aetnamem` is AGPL-3.0. Personal and open-source use is welcome. If you serve a
modified version over a network, the same open-source terms apply.

The project is early, but the direction is clear: agents should not just have
memory. They should have memory you can audit.
