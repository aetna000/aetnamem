# Graph Memory: design for massive, governed recall

Status: **implemented through Phase 4**. The graph is a derived index with
deterministic extraction, bounded seed-and-spread recall, governed lifecycle
propagation, scheduled consolidation, reviewer-gated reversible entity
merges, digest-verified subject/year history partitions, incremental audit
verification, and scheduled SQLite optimization.
Record and graph FTS indexes use ordinary row-ID maps so writes, corrections,
and deletions do not scan the virtual tables during index maintenance.

Enable graph recall for the desktop service with
`AETNAMEM_GRAPH_RECALL=1`. For one CLI query, pass `aetnamem recall ...
--graph`. Existing databases can be indexed without changing canonical data:

```bash
aetnamem graph-backfill ./memories.db SUBJECT
aetnamem graph-inspect ./memories.db SUBJECT
aetnamem graph-consolidate ./memories.db SUBJECT
aetnamem graph-merges ./memories.db SUBJECT --status pending
```

`--rebuild` drops and recreates only derived graph rows. The local scale probe
is `python bench/graph_recall.py --records 10000`. Automatic maintenance runs
hourly when graph recall is enabled; configure it with
`AETNAMEM_GRAPH_MAINTENANCE_SECONDS`, `AETNAMEM_GRAPH_ARCHIVE_AFTER_DAYS`, and
`AETNAMEM_GRAPH_ARCHIVE_DIR`.

---

## 1. Why a graph

aetnamem's canonical memory is a flat set of records: sentences with provenance,
trust tiers, quarantine, supersession via `fact_key`, and a hash-chained audit
log. That design is honest and auditable, but it has two ceilings:

1. **Scale.** Before Phase 0, `recall()` ranked every active record per query.
   Capping candidates with FTS5 fixes the constant factor, but lexical seeding alone
   cannot *scope* a huge memory — it can only rank what the query's words
   happen to touch.
2. **Reach.** Lexical recall cannot join. *"What airport does my boss
   prefer?"* requires two facts (`boss → Sarah`, `Sarah → SEA`) that share no
   words with the query. No amount of BM25 tuning performs that join.

A graph solves both: retrieval becomes **seed + bounded spread** (cost
independent of total memory size), and multi-hop questions become path
traversals that can be *shown to the user* as the reason a memory surfaced.

The enabling observation: **aetnamem is already an implicit graph.** Records
point to source episodes (`episode_id`), corrections point to what they
replace (`supersedes_id`), guarded actions point to evidence records, and the
audit chain links events. What is missing is only *entities* and *typed
relations*. The implemented derived index makes that implicit graph explicit — without
changing what the system trusts.

## 2. The prime directive: the graph is an index, not the truth

Episodes and the audit chain remain the sole source of truth. The graph
(entities, edges, aliases) is a **derived, rebuildable index** over them.

Consequences, in order of importance:

- A bad extraction or entity-merge pass can never corrupt memory: drop the
  graph, replay extraction from episodes, and you are whole.
- Extraction is conservative, deterministic, versioned, and can be re-run
  later without rewriting canonical records.
- The backing store can change (partitioning, cold archives, a different
  engine) without a data-integrity migration — only an index rebuild.
- Nothing about the existing guarantees moves: quarantine, tombstoning,
  supersession, deletion receipts, and audit chaining apply to graph objects
  exactly as they apply to records today.

## 3. Data model

The core index uses three tables beside the existing `records`/`episodes`:

```sql
CREATE TABLE entities (
  id            TEXT PRIMARY KEY,          -- ent_<hex>
  subject_id    TEXT NOT NULL,
  canonical     TEXT NOT NULL,             -- display name: "Sarah", "report.md"
  normalized    TEXT NOT NULL,             -- deterministic identity key
  kind          TEXT NOT NULL,             -- person | file | place | project |
                                           -- preference | org | other
  status        TEXT NOT NULL,             -- active | quarantined | merged | tombstoned
  merged_into   TEXT,                      -- set when status = 'merged'
  source_record TEXT,                      -- record that first introduced it
  created_at    TEXT NOT NULL,
  updated_at    TEXT,
  FOREIGN KEY (merged_into) REFERENCES entities(id)
);

CREATE TABLE entity_aliases (
  id            TEXT PRIMARY KEY,          -- als_<digest>
  entity_id     TEXT NOT NULL,
  subject_id    TEXT NOT NULL,
  surface       TEXT NOT NULL,             -- "my boss", "J", "the weekly report"
  normalized    TEXT NOT NULL,
  source_record TEXT,                      -- provenance: which record taught us this
  trust_tier    TEXT NOT NULL,
  status        TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  UNIQUE (subject_id, entity_id, surface),
  FOREIGN KEY (entity_id) REFERENCES entities(id)
);

CREATE TABLE edges (
  id            TEXT PRIMARY KEY,          -- edg_<hex>
  subject_id    TEXT NOT NULL,
  src_entity    TEXT NOT NULL,
  relation      TEXT NOT NULL,             -- preferred_airport | works_with |
                                           -- lives_in | stored_in | ...
  relation_label TEXT NOT NULL,            -- original normalized slot label
  dst_entity    TEXT,                      -- entity-valued edges
  dst_value     TEXT,                      -- literal-valued edges ("every Friday")
  record_id     TEXT NOT NULL,             -- the record this edge was derived from
  trust_tier    TEXT NOT NULL,             -- min(trust of contributing sources)
  confidence    REAL,
  status        TEXT NOT NULL,             -- active | superseded | quarantined | tombstoned
  supersedes_id TEXT,
  extractor_version TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  updated_at    TEXT,
  FOREIGN KEY (record_id)  REFERENCES records(id),
  FOREIGN KEY (src_entity) REFERENCES entities(id)
);

CREATE INDEX idx_edges_src ON edges(subject_id, src_entity, relation, status);
CREATE INDEX idx_edges_dst ON edges(subject_id, dst_entity, status);
```

Operational Phase 3/4 state is separate:

- `graph_merge_proposals` stores pending/approved/rejected/reverted reviewer
  decisions and their evidence record IDs.
- `graph_archive_partitions` and `graph_archive_members` bind inactive edges
  to digest-verified SQLite partitions by subject and year.
- `audit_verification_state` caches the last locally verified chain head for
  suffix-only verification. It is a performance cache, never a trust anchor.

Design notes:

- **`fact_key` generalizes to `(src_entity, relation)`.** Today a correction
  supersedes the record sharing its `fact_key`; tomorrow a new edge
  supersedes the active edge with the same `(src_entity, relation)` (for
  single-valued relations). Multi-valued relations (`works_with`) skip
  supersession. Same semantics, finer grain.
- **Every edge cites its record** (`record_id`), and records already cite
  episodes — so every edge has a two-hop provenance chain to raw user words.
- **Trust is computed, not asserted:** a derived edge carries the *minimum*
  trust tier of its contributing sources. An edge derived from a quarantined
  record is born quarantined.
- **Aliases are learned per-user with provenance**, not hand-curated. "my
  boss" becomes an alias of `ent_sarah` because a trusted record said so, and
  the alias row points at that record. (This replaces the global alias-table
  idea rejected in review: no maintenance burden, fully audited.)
- **Tombstoning an edge or entity follows `forget()` semantics**: content
  cleared, receipt issued, FTS entries removed. Tombstoning a record cascades
  to edges derived from it.

Graph mutations (`entity.created`, `edge.asserted`, `edge.superseded`,
`entity.merge_proposed`, `entity.merged`, ...) join the same per-subject
audit chain as memory events today.

## 4. Retrieval: seed + spread

```text
recall(query):
  1. SEED    FTS5 over entity canonicals, aliases, edge values, and record
             content → top-M nodes (M ≈ 16), each with a lexical seed score.
  2. SPREAD  bounded traversal from seeds, depth ≤ 2:
               weight(edge) = trust(edge) × recency(edge) × relation_prior
               activation(node) = Σ incoming activation × weight, with decay per hop
             frontier capped per hop (≈ 64) — total work is
             O(M × branching²) regardless of memory size.
  3. RANK    activated edges → deterministic score
             (activation × trust × recency), identical in spirit to today's
             rank_records().
  4. RETURN  top-k edges rendered as sentences (edge → "Sarah prefers SEA"),
             each carrying its provenance chain.
```

Properties worth defending in review:

- **Deterministic and replayable.** No learned weights; `relation_prior` is a
  small static table shipped with the code and versioned. Two runs on the
  same database return identical results.
- **Explanations are paths.** The retrieval event logs, per returned edge,
  the seed it was reached from and the path taken:
  `"boss" ⇒ alias(ent_sarah) ⇒ works_with ⇒ preferred_airport ⇒ SEA`.
  The dashboard can render this as "why am I seeing this?" — massive memory
  usually means less explainable memory; here it means more.
- **Bounded audit payloads.** The retrieval event logs seeds, the frontier
  cap, path traces for returned results, and *digests* of pruned candidates —
  never O(N) candidate lists (fixing today's per-recall audit blowup).
- **Quarantine shapes the graph itself.** Spread does not traverse
  quarantined edges or entities; untrusted content cannot become a bridge
  between trusted facts. This is a property lexical ranking cannot offer.

## 5. Consolidation ("sleep")

A background pass runs on schedule with a strict rule: **every consolidation
output is a normal governed write** and reviewer decisions remain explicit.

1. **Extraction sweep.** Backfill records missing from the current extractor
   version. New edges inherit record trust and status; quarantined records
   produce quarantined graph objects.
2. **Entity resolution.** Candidate merges are *proposed*, never applied:
   high-confidence merges (exact name/alias + same kind) surface as pending
   `entity.merge_proposed` items; everything else is left separate.
   The dashboard renders "Is 'J' the same person as 'Javad'? [Merge] [Keep
   separate]" through the existing Approvals machinery. Merges are reversible
   (`merged_into` pointer, never destructive rewrites). Entity resolution is
   where graph-memory projects die; conservatism + human sign-off + the
   rebuildable-index rule is the survival strategy.
3. **Cold history and decay.** Recency already decays traversal scores.
   Superseded and tombstoned derived edges older than the configured cutoff
   move into SQLite files partitioned by subject and year. Each partition is
   SHA-256 bound in the primary database and verified before reads. Canonical
   records, episodes, deletion receipts, and audit events stay in the primary
   database; the archive operation never weakens source-of-truth guarantees.
   Each maintenance pass handles at most 10,000 edges so work stays bounded.
   `forget()` also searches superseded records and removes matching archived
   edge rows before issuing its deletion receipt.

## 6. Scale plan

| Regime | Storage | Notes |
|---|---|---|
| ≤ ~1M edges | one SQLite file, WAL | indexes above; nothing else needed |
| ~1–10M edges | same + inactive-edge DB per subject/year | hot graph stays small; spread never touches cold partitions |
| beyond | replace the derived index behind the same API | canonical records and audit semantics remain unchanged |

Supporting work at scale is implemented: locally cached incremental chain
verification re-checks its cached anchor then verifies only the suffix,
scheduled maintenance runs `PRAGMA optimize`, and inactive graph history is
physically partitioned. External checkpoints remain mandatory for detecting
whole-database replacement; the local verification cache is not an anchor.

## 7. Migration

Backfill is mechanical because the graph is derived state:

1. Ship empty graph tables; keep `recall()` unchanged (Phase 1 is invisible).
2. Backfill: one entity per subject ("you"), one entity per distinct
   `fact_key` object where extractable; every active record with a `fact_key`
   becomes an edge citing that record. Records that resist triple extraction
   simply remain records — the old path still ranks them.
3. Graph recall ships behind a flag; the golden benchmark (exact questions,
   paraphrases, corrections, forgets, *and multi-hop questions*) gates the
   default flip.
4. Blended recall remains permanent: seed+spread results merge with direct
   FTS record hits, so a fact that never became an edge is still recallable.

## 8. Phases

| Phase | Scope | Gate to next |
|---|---|---|
| 0 (implemented) | candidate-capped recall, debounced sealing, benchmarks | compatibility suite and local scale probe |
| 1 (implemented) | schema + extraction + backfill, recall unchanged by default | backfill idempotent; records remain canonical |
| 2 (implemented, opt-in) | seed+spread recall, path evidence, blended record fallback | graph invariant tests; disabled by default |
| 3 (implemented) | consolidation worker, approval-gated reversible merges, decay/archive | merge proposals reviewable in dashboard |
| 4 (implemented) | subject/year history partitions, incremental audit verification, scheduled optimization | archive digests and cached anchors verified before use |

## 9. Risks

- **Extraction coverage.** The implemented deterministic extractor is
  intentionally conservative and will miss unfamiliar sentence shapes.
  Blended direct-record recall is the safety net. A future model extractor
  must quarantine uncertain output and remain fully re-runnable from records.
- **Entity-resolution errors.** Contained by: proposal-only merges, human
  approval, reversible `merged_into` pointers, and traversal that resolves
  merged entity families without rewriting canonical records.
- **Archive loss or modification.** Detected by partition digests. Canonical
  records remain in the primary database, so a derived partition can be
  rebuilt; archive reads reject missing or modified files.
- **Relation vocabulary sprawl.** Start with a small closed set (~20
  relations) plus `related_to` as the escape hatch; widen only with benchmark
  evidence.
- **Complexity creep.** Each phase ships alone and `records`-only operation
  remains supported; the graph never becomes load-bearing for correctness,
  only for recall quality and scale.
