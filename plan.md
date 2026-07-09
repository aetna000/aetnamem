# aetnamem Architecture And Roadmap

`aetnamem` is a local-first, audit-grade memory engine for agents. The core
claim is narrow on purpose: memory should be useful, but it must also be
explainable, erasable, and independently verifiable.

## Current Product Thesis

Most agent memory systems optimize for recall quality first. `aetnamem`
optimizes for auditable trust:

- every memory record has provenance;
- untrusted webpage/tool content is quarantined, not silently activated;
- corrections supersede old facts instead of accumulating contradictions;
- deletion purges record content, fact keys, and source episode text;
- every write, recall, deletion, checkpoint, and agent action can join a
  tamper-evident per-subject audit chain.

SQLite is the default because it gives the embedded developer experience a
single local file with transactions and FTS. The audit guarantee does not
depend on SQLite specifically; it comes from the data model and hash-chain
rules documented in [docs/audit-log-spec.md](docs/audit-log-spec.md).

## Implemented Surfaces

- Python library: `from aetnamem import Memory`
- CLI: `aetnamem remember`, `recall`, `forget`, `audit`, `verify`, and the
  rest of the engine verbs
- MCP server over stdio: `aetnamem mcp`
- OpenClaw plugin wrapper: automatic recall/capture on OpenClaw hooks
- Independent verifier: [tools/verify_audit.py](tools/verify_audit.py)
- Benchmark adapter and target files under [bench](bench)

## Core Layers

| layer | status | purpose |
|---|---|---|
| L0 episodes | implemented | raw user evidence, purged by deletion |
| L1 records | implemented | active/quarantined/superseded/tombstoned facts with provenance |
| L2 scenes | implemented | deterministic per-session view derived from episodes/records |
| L3 persona | implemented | live-derived `<user_persona>` snapshot with record IDs |
| derived proposals | implemented | evidence-cited proposals that land quarantined |
| consolidation | implemented | deterministic duplicate/fact-key repair |

## Data Model

The important tables are:

- `episodes`: source messages and source metadata;
- `records`: semantic facts, statuses, provenance links, fact keys, and
  tombstone state;
- `retrieval_events`: recall query digests, ranked candidate scores, returned
  IDs, thresholds, and limits;
- `audit_log`: per-subject hash-chained events for memory and agent actions.

The erasable data plane is `episodes` and `records`. The immutable audit
plane stores digests and structural metadata, not message text or fact values.

## Invariants

1. All public reads and writes are scoped by `subject_id`.
2. User-authored facts can become active; webpage/tool-derived facts land
   `quarantined` until promoted.
3. Recall only considers active records.
4. Forget requests never mean "delete everything" when the selector is empty.
5. Forget request text is not stored as an episode; only hashes enter the
   audit plane.
6. Deletion tombstones matching active/quarantined records and purges their
   content, fact keys, FTS rows, and source episode text.
7. Retrieval events preserve enough candidate scoring metadata to explain why
   a record was or was not returned.
8. Checkpoints are required to detect tail truncation and database
   replacement.

## Benchmark Contract

Development is gated against MemoryStackBench's `seven_sins_v0_1` suite using
the canonical files in [bench](bench):

- [bench/targets/aetnamem.yaml](bench/targets/aetnamem.yaml)
- [bench/adapters/aetnamem.py](bench/adapters/aetnamem.py)

The benchmark is a conformance gate, not the architecture. Unit tests should
cover the policy functions directly with non-benchmark vocabulary so the
score stays honest.

## Roadmap

1. **Harden the current engine.**
   Keep expanding tests around audit invariants, deletion receipts, MCP
   contracts, OpenClaw hooks, and independent verification.

2. **Improve retrieval quality without weakening auditability.**
   Add optional embeddings/vector search behind the existing retrieval event
   model. Every returned result must still be explainable by scores and IDs.

3. **Add LLM-backed extraction as a quarantined proposal path.**
   LLM output should propose evidence-cited facts. Activation still requires
   the same quarantine/promote policy.

4. **Add server deployments.**
   Put HTTP/FastAPI and Docker around the existing engine. Server mode should
   preserve the same subject isolation, receipt format, checkpoint format, and
   independent verifier.

5. **Add stronger storage/security backends.**
   Postgres/pgvector, crypto-shredding, retention policies, signatures for
   checkpoints/receipts, and optional Firestore support should all be storage
   or deployment layers over the same semantics.

6. **Deepen agent audit.**
   Standardize conventions for model calls, tool calls, tool results,
   memory reads, memory writes, policy decisions, and user-visible responses
   so an auditor can reconstruct what the agent knew and did.

## Non-Goals For The Current Version

- Closed-source SaaS enablement: the project is AGPL-3.0.
- Prompt-only safety guarantees: policy gates must live in the engine.
- Benchmark-specific shortcuts.
- Storing raw prompts, raw forget requests, or raw tool outputs in the audit
  plane.
