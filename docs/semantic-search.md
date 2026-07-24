# Semantic investigation search

AetnaMem can add embedding-based discovery to its human-facing memory and
audit search without changing agent recall.

The semantic index is a **lens, never a source**:

- canonical records remain in `memories.db`;
- vectors live in a disposable `memories.db.vectors.db` sidecar;
- the vector index nominates record IDs;
- every result is reloaded from canonical SQLite;
- subject, status, and content digest are checked before a result is shown.

No generated answer is added to this path. This is semantic evidence
retrieval, not an LLM answering from RAG context.

## Compatibility boundary

Semantic mode currently affects only:

```text
aetnamem memories --query ...
aetnamem search ...
aetnamem trace ...
```

It does not change `Memory.recall()`, `memory_recall` over MCP, OpenClaw
automatic recall, four-memory context compilation, or memory admission. The
default search mode remains lexical.

The normal installation remains:

```bash
pip install aetnamem
```

Ollama and OpenAI-compatible endpoints require no additional Python package.
For an in-process Sentence Transformers model:

```bash
pip install "aetnamem[semantic]"
```

The sidecar is plaintext SQLite and embeddings must be treated as sensitive
derived content. A local Ollama or Sentence Transformers provider keeps
memory and queries on the machine. A remote OpenAI-compatible provider
receives retained memory text during index construction and receives each
semantic query; use one only when that data flow is authorized.

## Build an index

### Ollama

```bash
ollama pull nomic-embed-text

aetnamem index build ./memories.db \
  --subject user-1 \
  --embedder ollama \
  --model nomic-embed-text
```

The default Ollama endpoint is `http://127.0.0.1:11434`. Override it with
`--endpoint`. The adapter uses Ollama's current
[`POST /api/embed`](https://docs.ollama.com/api/embed) batch endpoint.

### Sentence Transformers

```bash
aetnamem index build ./memories.db \
  --subject user-1 \
  --embedder sentence-transformers \
  --model sentence-transformers/all-MiniLM-L6-v2
```

The adapter uses the documented
[`encode_document` and `encode_query`](https://sbert.net/docs/package_reference/sentence_transformer/model.html)
methods when the installed model exposes them, with normalized vectors;
otherwise it uses `SentenceTransformer.encode`.

### OpenAI-compatible endpoint

Keep the API key out of shell history:

```bash
export MY_EMBEDDING_API_KEY="..."

aetnamem index build ./memories.db \
  --subject user-1 \
  --embedder openai-compatible \
  --model your-embedding-model \
  --endpoint https://embedding.example.test \
  --api-key-env MY_EMBEDDING_API_KEY
```

`hashing` is also available as a dependency-free diagnostic provider for
tests and plumbing checks. It is not a semantic-quality model and must not be
used to support semantic retrieval claims.

Each build creates a versioned epoch, verifies it, atomically changes the subject's
active-epoch pointer, and erases vector entries belonging to retired epochs.
Model identities are never mixed inside an epoch.

## Search by meaning

```bash
# Existing deterministic text search.
aetnamem search ./memories.db "departure location" \
  --subject user-1 --mode lexical

# Exact cosine search over the active vector epoch.
aetnamem search ./memories.db "departure location" \
  --subject user-1 --mode semantic

# Reciprocal Rank Fusion of lexical and semantic ranks.
aetnamem search ./memories.db "departure location" \
  --subject user-1 --mode hybrid
```

The active epoch records its provider, model, version, endpoint identity,
dimensions, and normalization. Search reconstructs that provider configuration
unless explicitly overridden. A provider/model/version mismatch fails instead
of silently querying incompatible vectors.

For Ollama, AetnaMem resolves the selected local model through `/api/tags`,
stores its SHA-256 model digest, and checks the current digest again for every
new search process. A changed model fails closed instead of being treated as
the model that built the epoch. Other providers may not expose an immutable
revision; for those providers, `unverified` remains the honest default unless
the deployment supplies `--model-version`.

Use `--min-similarity` to control semantic nomination:

```bash
aetnamem search ./memories.db "departure location" \
  --subject user-1 --mode hybrid --min-similarity 0.35
```

Hybrid ranking uses Reciprocal Rank Fusion. Governance is not blended into a
relevance score: the report separately shows why a result matched and why its
canonical record was eligible.

```text
Why matched: lexical rank 7 · semantic rank 1 · similarity 0.91 · RRF ...
Canonical: subject=yes · status=active · digest=verified
```

The same mode works as the discovery step for a trace:

```bash
aetnamem trace ./memories.db \
  "Why did the agent choose Sydney?" \
  --subject user-1 --mode hybrid \
  --output sydney-investigation.json
```

Only the starting-memory discovery is semantic. The timeline is expanded using
canonical record, episode, retrieval, manifest, run, action, and outcome
relationships.

## Index status and verification

```bash
aetnamem index status ./memories.db --subject user-1
aetnamem index verify ./memories.db --subject user-1
```

Verification fails when it finds:

- an orphaned vector;
- a vector for a tombstoned record;
- a vector assigned to the wrong subject;
- a canonical content-digest mismatch;
- a dimension mismatch;
- an indexable canonical record missing from the active epoch;
- vector entries remaining in a retired epoch.

These are release-blocking invariants, not retrieval-quality percentages.

Successful and failed verification reports are cached only while both the
canonical-record generation and semantic-index generation remain unchanged.
SQLite triggers maintain those counters even for direct SQL mutations. Record
validation and verification use batched canonical fetches, avoiding one
database query per vector. Every returned candidate is still checked against
canonical subject, status, and content digest.

## Deletion

When no semantic sidecar exists, `forget()` continues to return the existing
`aetnamem-deletion-receipt-v1`.

When an index exists, `forget()` additionally:

1. tombstones and purges canonical content;
2. removes the record from every vector epoch;
3. marks affected epochs dirty so operators know a clean rebuild is due;
4. verifies that no vector entry still references the record;
5. verifies overall index consistency;
6. checkpoints the sidecar WAL;
7. returns `aetnamem-deletion-receipt-v2` with cleanup and verification
   report digests.

Canonical validation remains the immediate safety boundary: a tombstoned,
missing, cross-subject, or digest-mismatched candidate is dropped even if a
stale sidecar survives a process or storage failure.

Logical deletion does not sanitize old filesystem snapshots, replicas,
exports, backups, process memory, swap, or storage-device remnants. Apply the
same retention and encryption controls to the vector sidecar as to the
canonical database. Rebuild after deletion to create a clean epoch:

```bash
aetnamem index build ./memories.db \
  --subject user-1 \
  --embedder ollama \
  --model nomic-embed-text
```

## Reproducibility and evaluation

Text and JSON reports include retrieval mode, lexical rank, semantic rank,
cosine similarity, fused RRF score, active epoch, and canonical validation.
Exact cosine over a fixed epoch snapshot is deterministic: fixed query
embedding plus fixed epoch produces the same ordering, with record ID as tie-breaker.
Approximate-nearest-neighbor indexing is deliberately excluded from this first
implementation.

Exact search remains linear in the number of vectors and their dimensions.
Verification caching and batched record reads remove redundant database work;
they do not turn exact cosine search into a sublinear algorithm. When NumPy is
already available, larger candidate sets use a vectorized exact matrix
operation; the dependency-free Python implementation remains the fallback.
Benchmark with the deployment's actual record count before setting latency
expectations.

Safety is tested as invariants: tombstoned, stale, and cross-subject vectors
fail closed; purging leaves no vector entry; fixed inputs rank deterministically;
and existing lexical and agent recall behavior remains unchanged.

Retrieval quality must be measured separately with a labeled paraphrase set,
using Recall@5/10, MRR, nDCG, latency, build time, and embedding cost. The
diagnostic hashing provider is excluded from quality comparisons.

> Search by meaning, verify against canonical memory, and trace the result to
> auditable evidence.
