# aetnamem Architecture And Roadmap

`aetnamem` is a local-first, audit-grade memory engine for agents. The core
claim is narrow on purpose: memory should be useful, but it must also be
explainable, erasable, and independently verifiable.

## Current Product Thesis

Most agent memory systems optimize for recall quality first. `aetnamem`
optimizes for auditable trust:

- extracted records link to episodes and derived proposals cite evidence IDs;
- content classified as webpage/tool output is quarantined;
- recognized matching fact slots supersede older active records;
- deletion logically purges live record content, fact keys, FTS entries, and
  source episode text;
- engine writes, recalls, deletions, and agent actions can join a tamper-evident
  per-subject audit chain; checkpoints anchor chain heads outside that chain.

SQLite is the default because it gives the embedded developer experience a
single local file with transactions and FTS. The audit guarantee does not
depend on SQLite specifically; it comes from the data model and hash-chain
rules documented in [docs/audit-log-spec.md](docs/audit-log-spec.md).

## Implemented Surfaces

- Python library: `from aetnamem import Memory`
- Guarded-actions library: `from aetnamem.actions import ActionEngine`
- CLI: `aetnamem remember`, `recall`, `forget`, `audit`, `verify`, and the
  rest of the engine verbs
- Guarded-actions CLI: `aetnamem actions stage/show/list/approve/commit/abort/recover/verify/import-journal`
- MCP server over stdio: `aetnamem mcp`
- OpenClaw plugin wrapper: automatic recall/capture on OpenClaw hooks
- Independent verifiers: [tools/verify_audit.py](tools/verify_audit.py) and
  [tools/verify_actions.py](tools/verify_actions.py)
- Collaborative decision SDK: `from aetnamem.decisions import DecisionEngine`
- EtD profile/playground: `aetnamem.etd` and `aetnamem-etd-playground`
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
- `action_*`: guarded plans, operations, evidence, approvals, attempts,
  erasable payloads, and receipts.

The logical data plane is `episodes`, `records`, and `action_payloads`. Core
engine events use digests and structural metadata, but low-level custom action
payloads and opt-in raw retrieval queries remain caller-controlled exceptions.

## Invariants

1. Memory reads and writes are scoped by `subject_id`. Action rows carry a
   subject, while transaction lookup uses a globally unique action ID and
   action listing may intentionally span subjects.
2. Facts classified as user-authored can become active; records classified as
   webpage/tool-derived land `quarantined` until promoted. Authentic source
   attribution is a host responsibility.
3. Recall only considers active records.
4. Forget requests never mean "delete everything" when the selector is empty.
5. Forget request text is not stored as an episode; only hashes enter the
   audit plane.
6. Deletion tombstones matching active/quarantined records and logically
   purges their content, fact keys, FTS rows, and source episode text.
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
   Expand deterministic graph extraction and multi-hop benchmarks behind the
   existing retrieval event model. Every returned result must remain
   explainable by scores, paths, and record IDs.

3. **Add LLM-backed extraction as a quarantined proposal path.**
   LLM output should propose evidence-cited facts. Activation still requires
   the same quarantine/promote policy.

4. **Add server deployments.**
   Put HTTP/FastAPI and Docker around the existing engine. Server mode should
   preserve the same subject isolation, receipt format, checkpoint format, and
   independent verifier.

5. **Add stronger storage/security backends.**
   Postgres, crypto-shredding, retention policies, signatures for
   checkpoints/receipts, and optional Firestore support should all be storage
   or deployment layers over the same semantics.

6. **Deepen agent audit.**
   Standardize conventions for model calls, tool calls, tool results,
   memory reads, memory writes, policy decisions, and user-visible responses
   so an auditor can reconstruct what the agent knew and did.

7. **Expand Guarded Actions.**
   The first production-shaped vertical slice is implemented: atomic memory
   and audit writes, causal WorldPatch proposals, signed exact-plan approvals,
   a durable action ledger, explicit uncertainty, verified filesystem
   compensation, receipts, and the `aetnamem actions` CLI. The filter-only MCP
   gate is implemented; automatic write-to-WorldPatch mediation, remaining
   adapters, asymmetric identity, and encrypted payloads are
   tracked in [TODO.md](TODO.md).

8. **Harden collaborative decisions and EtD.**
   The experimental Python SDK now provides versioned decision artifacts,
   exact lineage, membership/recusal, concurrent ballots, adoption,
   institutional approval, scoped authorization, export verification, an EtD
   profile, PostgreSQL multi-process persistence, asymmetric/KMS identity and
   receipts, retention/purge receipts, a playground, and a pilot/review kit.
   Actual organizational deployment and independent methodology findings are
   external validation gates rather than repository implementation work.

## Non-Goals For The Current Version

- Closed-source SaaS enablement: the project is AGPL-3.0.
- Prompt-only safety guarantees: policy gates must live in the engine.
- Benchmark-specific shortcuts.
- Storing raw prompts, raw forget requests, or raw tool outputs in the audit
  plane.
