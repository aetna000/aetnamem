# Semantic search benchmark

This labeled smoke benchmark compares lexical, exact semantic, and hybrid RRF
investigation search on paraphrased queries. It reports Recall@5/10, MRR,
nDCG@10, mean query latency, and index build time.

```bash
ollama pull nomic-embed-text
python bench/semantic_search/run.py \
  --embedder ollama \
  --model nomic-embed-text \
  --output semantic-results.json
```

Or use the optional local Python adapter:

```bash
pip install "aetnamem[semantic]"
python bench/semantic_search/run.py \
  --embedder sentence-transformers \
  --model sentence-transformers/all-MiniLM-L6-v2
```

The fixture is deliberately small and is a regression/smoke instrument, not
independent evidence that one embedding model improves real agent outcomes.
Expand it with held-out, independently labeled organization-specific queries
before publishing quality claims. Safety properties such as zero tombstoned,
stale, or cross-subject results are enforced separately by unit tests and
`aetnamem index verify`.
