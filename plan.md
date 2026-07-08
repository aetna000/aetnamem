# aetnamem — Architecture Plan

An agent memory engine — in the space of mem0, Supermemory, Zep — designed from
day one to pass the audit that most of them fail. It runs fully local with zero
configuration, and the exact same code deploys to the cloud.
It shall support Firebase through a Firestore storage adapter, while keeping
SQLite as the default zero-configuration local path.

License: **AGPL-3.0** (see `LICENSE`). Anyone may use aetnamem, including
commercially, but any derivative work — including software that serves aetnamem
over a network (SaaS) — must be released under the same open-source terms.
Personal use is free. Nobody can build a closed product on it.

## Product thesis

The [MemoryStackBench](https://aetna000.github.io/MemoryStackBench/) leaderboard
(developed in the sibling `ai_lab` repo) shows exactly where existing memory
stacks fail: **webpage poisoning, retention after deletion, missing provenance,
and stale temporal updates**. So aetnamem is not "another mem0." Its
differentiator is *auditable trust*:

- every record carries full provenance,
- untrusted content can never silently become durable memory,
- deletion is real and verifiable,
- updates supersede instead of accumulate.

Tagline-level claim: **"the memory layer built to pass the audit."**

## Relationship to MemoryStackBench (`ai_lab`)

aetnamem lives in its own repo; the benchmark stays a neutral referee.
The integration is two files in `ai_lab`:

- `targets/aetnamem.yaml` — target manifest
- `memorybench/adapters/aetnamem.py` — a standard `MemoryStackAdapter`

The dev loop is **benchmark-driven development**: CI in this repo clones
`ai_lab` and runs `seven_sins_v0_1` as an acceptance gate. A change merges only
if it scores 33/33. The benchmark is simultaneously the product's conformance
suite and its public credibility story.

Two pieces of prior art carry over:

- `ai_lab`'s `store_policy.py` is a hand-written spec of *correct* memory
  behavior (trust-typed sources, forget-intent parsing, supersession).
  aetnamem is the generalization of that policy — LLM-powered instead of
  regex-hardcoded.
- The aetna `brain.js` R0–R4 layering (raw evidence → derived layers, with
  `consolidate.js` / `reflect.js`) is the mental model for the episodic →
  semantic split and the consolidation job below.

## Design principles (learned from the leaderboard)

1. **Provenance is mandatory.** Every record carries `source_type`,
   `source_session_id`, `source_turn_id`, `created_at`, `confidence`.
2. **Trust-tiered writes.** User statements and tool/webpage content are
   classified differently. Extractions from untrusted sources land
   *quarantined* and only promote on explicit user confirmation.
3. **Temporal supersession.** Updates never overwrite or duplicate — a new
   record supersedes the old one, which stays inspectable as `superseded`.
4. **Deletion that actually deletes.** Forget requests resolve to a record
   set, tombstone it, purge it, and the result is verifiable via `inspect()`.
5. **Auditability as API.** Retrieval events and mutations are logged and
   exposed through `audit()` — a first-class feature, not a debug artifact.
6. **Tenant isolation at the storage layer.** All access is scoped by
   `subject_id`; server mode adds per-API-key namespaces on top.

## Architecture

One core engine, three deployment shells around it — the same code path in all
three, so local and cloud never diverge:

```
                ┌────────────────────────────────────────────┐
                │              Deployment shells              │
                │                                            │
   pip install  │  Embedded lib     HTTP server      MCP     │
   & import  ──▶│  Memory(path)     FastAPI, auth,   server  │◀── any agent
                │  (SQLite file)    multi-tenant     (tools) │    (Claude, etc.)
                └───────────┬────────────┬────────────┬──────┘
                            ▼            ▼            ▼
                ┌────────────────────────────────────────────┐
                │                 Core engine                 │
                │                                            │
                │  Write pipeline:                           │
                │   ingest → source/trust classify →         │
                │   extract (LLM or rules) → policy gates:   │
                │     dedupe · supersede · quarantine        │
                │   → commit with full provenance            │
                │                                            │
                │  Read pipeline:                            │
                │   hybrid recall (FTS + vector + trust/     │
                │   recency weights) → retrieval event log   │
                │                                            │
                │  Forget pipeline:                          │
                │   intent → selector → tombstone + purge    │
                │   → verifiable via inspect()               │
                └───────────┬────────────────────┬───────────┘
                            ▼                    ▼
                   SQLite + FTS5 +        Postgres + pgvector
                   sqlite-vec (local       (cloud / multi-
                   default, zero-config)   tenant)
                          │
                          ▼
                   Firestore adapter
                   (Firebase-native apps)
```

### Data model

`records` — the semantic layer:

| column | notes |
|---|---|
| `id` | primary key |
| `subject_id` | tenant/user scope, enforced on every query |
| `content` | the fact, normalized |
| `embedding` | vector for hybrid recall |
| `source_type` | `user_message`, `webpage`, `tool_output`, … |
| `trust_tier` | derived from source classification |
| `source_session_id`, `source_turn_id` | provenance to the original utterance |
| `created_at`, `confidence`, `scope` | provenance & applicability |
| `status` | `active` \| `superseded` \| `quarantined` \| `tombstoned` |
| `supersedes_id` | link to the record this one replaced |
| `raw` | JSON blob of native/extra metadata |

Supporting tables:

- `episodes` — append-only episodic log of raw turns (cheap, replayable).
- `retrieval_events` — every recall: query, candidates, scores, what was returned.
- `audit_log` — every mutation: writes, promotions, supersessions, purges.

### Two memory layers + consolidation

- **Episodic**: raw turns, append-only, no interpretation.
- **Semantic**: extracted facts with provenance (the `records` table).
- A background **consolidate** pass merges duplicates, decays stale
  low-confidence records, and re-links supersession chains — the
  `consolidate.js` / `reflect.js` idea, reborn.

### Extraction is pluggable

- **LLM extractor** (default: a small fast model, e.g. Haiku, or a local
  Ollama model) proposes candidate facts with confidence.
- **Rules extractor** as deterministic fallback — the engine runs fully local
  with zero API keys, degraded gracefully.
- Either way, candidates pass through the same policy gates
  (trust / dedupe / supersede / quarantine) before commit.

### Retrieval

Hybrid recall: SQLite FTS5 (or Postgres full-text) + vector similarity +
trust/recency weighting. Quarantined and tombstoned records are never
returned. Every recall writes a `retrieval_events` row.

## The six verbs (same API in every shell)

```
remember(subject_id, message | fact, …)   # runs the write pipeline
recall(subject_id, query, …)              # hybrid retrieval + event log
list(subject_id, …)                       # enumerate active records
forget(subject_id, selector | utterance)  # tombstone + purge, verifiable
inspect(subject_id)                       # full record dump with provenance
audit(subject_id, …)                      # retrieval + mutation history
```

## Ease of use — three deployment tiers

1. **Local embedded** (the mem0-OSS moment):
   `pip install aetnamem` → `m = Memory("./memories.db")` →
   `m.remember(...)`, `m.recall(...)`, `m.forget(...)`. SQLite file, no
   services, no config, no API keys required.
2. **Self-host server**:
   `docker run -v ./data:/data aetnamem/server` — FastAPI exposing the same
   six verbs, API-key auth, SQLite or Postgres via one env var.
3. **Cloud**: the identical container on Cloud Run / Fly + managed
   Postgres/pgvector. Multi-tenancy is `subject_id` scoping plus per-key
   namespaces, which the schema already enforces. A hosted offering later is
   this same image behind billing.

Plus an **MCP server** shipping in the same package — the adoption lever:
any Claude Code / agent user gets persistent, auditable memory with one line
in their MCP config.

## Repo layout

```
aetnamem/
  core/        # records, policy gates, supersession, deletion, consolidation
  store/       # sqlite.py, postgres.py (same interface)
  extract/     # llm.py, rules.py
  retrieve/    # hybrid search, weighting, retrieval log
  server/      # FastAPI app + auth
  mcp/         # MCP server entrypoint
  cli.py       # `aetnamem serve`, `aetnamem inspect`, `aetnamem audit`
  tests/
  .github/workflows/bench.yml   # clones ai_lab, runs seven_sins as gate
```

## Phasing

1. **v0 — pass our own bench locally.** Core + SQLite + rules extractor +
   adapter/target in `ai_lab`. Goal: 33/33 on `seven_sins_v0_1` with an honest
   `implemented_store_harness` label.
2. **v1 — real product.** LLM extraction, hybrid retrieval, consolidation
   job, Python SDK docs.
3. **v2 — server + MCP + Docker.** The "easy setup" story ships here.
4. **v3 — Postgres backend + cloud recipe + multi-tenant auth.** Optionally a
   hosted beta.
5. **v3.5 — Firestore adapter.** Firebase-native persistence for teams already
   using Firestore, implemented behind the same storage interface after the
   core semantics are stable.

## My read

The thesis is strong: "auditable memory" is a clearer wedge than "better
recall." The product should win first on correctness, provenance, and deletion,
not on having every storage backend or every agent integration.

The main risk is scope creep. The plan currently contains a benchmark target, a
local library, a server, MCP, Docker, Postgres, Firestore, LLM extraction,
hybrid retrieval, consolidation, auth, and eventually cloud. That is too much
to build before proving the core policy model. I would make v0 almost boring:
one Python package, one SQLite store, deterministic extraction, and a ruthless
focus on the six verbs.

Firestore should stay in the architecture, but I would not put it in v0.
Firestore does not naturally give the same full-text/vector behavior as
SQLite/Postgres, so shipping it too early would either distort the core API or
force a weaker retrieval story. Design the storage interface so Firestore can
plug in later; do not let it steer the first implementation.

SQLite is still the right v0 default. It is a single-file, zero-service store
with transactions, indexes, FTS5, and easy local inspection. That is exactly
what the embedded developer experience needs. The audit guarantee, however,
must not depend on SQLite specifically. It should come from the data model:
append-only audit events, stable event IDs, per-subject hash chaining, explicit
record status transitions, and deletion/purge events that can be independently
verified.

For auditable agents, memory is only half the story. The same audit log should
also accept agent action events: model calls, tool calls, tool results, memory
reads, memory writes, user-visible responses, policy decisions, and errors. In
v0, these can live in SQLite as `audit_log` events. In server/cloud mode, the
same event schema should move to Postgres first, with periodic hash checkpoints
exported to object storage or another external ledger so the audit trail can be
verified outside the primary database.

## What I would do

1. **Freeze the v0 contract.**
   Define the exact Python API for `Memory`, the six verbs, return shapes, error
   types, and record statuses. Do this before writing the server, MCP, or cloud
   code.

2. **Scaffold the package.**
   Create the real repo skeleton:
   `aetnamem/core`, `aetnamem/store`, `aetnamem/extract`,
   `aetnamem/retrieve`, `aetnamem/cli.py`, and `tests`.

3. **Build SQLite first.**
   Implement migrations and repository methods for `records`, `episodes`,
   `retrieval_events`, and a hash-linked `audit_log`. Enforce `subject_id` in
   the store API, not just in higher-level code.

4. **Implement append-only evidence before smart memory.**
   `remember()` should always write an `episodes` row first. Semantic records
   should be derived from that evidence and should always point back to it.

5. **Port the deterministic policy from `ai_lab`.**
   Use `store_policy.py` as the v0 behavioral spec. The first extractor should
   be rules-based and deterministic enough to make benchmark failures obvious.
   LLM extraction comes only after the policy gates are already correct.

6. **Make policy gates explicit.**
   Implement trust classification, quarantine, dedupe, supersession, and forget
   as separate core functions with direct unit tests. These are the product, not
   incidental helpers.

7. **Ship minimal recall.**
   Start with SQLite FTS5 plus simple recency/trust scoring. Keep vector search
   behind an interface, but do not make v0 depend on embeddings.

8. **Make deletion verifiable.**
   `forget()` should resolve a selector to record IDs, tombstone them, purge
   retrievable content, and write an audit entry. `inspect()` must prove the
   forgotten content cannot come back through `recall()`.

9. **Add the benchmark adapter early.**
   Add `targets/aetnamem.yaml` and `memorybench/adapters/aetnamem.py` in
   `ai_lab` as soon as the six verbs exist. Let the benchmark drive the rest of
   v0 instead of guessing.

10. **Gate CI on both unit tests and the bench.**
    Unit tests should cover the policy functions directly. The benchmark should
    cover the public behavior. A v0 merge should require both.

11. **Only then add product polish.**
    After 33/33 locally, add Python SDK docs, packaging, examples, LLM
    extraction, vector retrieval, and consolidation.

12. **Add integrations in this order.**
    Server + Docker first, MCP second, Postgres third, Firestore fourth. MCP is
    the adoption lever, but it should sit on top of a proven engine rather than
    define the engine.

13. **Extend memory audit into agent audit.**
    Add a public `log_action()` / `audit()` path for agent action events, using
    the same subject/session/turn IDs as memory events. The long-term unit is
    not just "what did the agent remember?" but "what did the agent know, read,
    decide, call, write, forget, and show?"

## v0 acceptance checklist

- `pip install -e .` works locally.
- `Memory("./memories.db")` creates a usable SQLite-backed memory.
- The six verbs work from Python and return inspectable structured data.
- Every semantic record has provenance.
- Web/tool content is quarantined unless explicitly promoted.
- Superseded records are not returned by recall.
- Tombstoned/purged records are not returned by recall or normal list.
- `inspect()` and `audit()` expose enough evidence to debug every mutation.
- Audit events are hash-linked per subject so local tampering is detectable.
- Agent action events can be logged through the same audit pipeline.
- `ai_lab` can run `seven_sins_v0_1` against `aetnamem`.
- The score is 33/33 without hidden benchmark-only shortcuts.
