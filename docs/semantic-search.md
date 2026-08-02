# Semantic search

AetnaMem always keeps canonical memory in SQLite. Embeddings are an optional, derived investigator index for finding paraphrases and conceptually related memories.

```bash
python -m pip install "aetnamem[semantic]"
aetnamem index build memories.db --subject user-1 --embedder sentence-transformers --model all-MiniLM-L6-v2
aetnamem index verify memories.db --subject user-1
aetnamem search memories.db "travel preference" --subject user-1 --mode hybrid
```

Ollama, OpenAI-compatible and deterministic hashing providers are also supported; use `aetnamem index build --help` for their exact options.

## Integrity model

- Vectors never become canonical memory.
- Every vector binds a record content digest, model identity, dimensions and index epoch.
- Search verifies the current epoch and revalidates every candidate against the canonical record.
- Purge and supersession invalidate or remove derived vectors.
- A dimension mismatch fails or skips safely; it is never silently truncated.
- Provider model versions or digests are preserved when the provider exposes them.

Semantic search improves reach but adds a model, tokenizer, preprocessing, numerical and index-state dependency to replay. Lexical results remain easier to explain by matched terms. Hybrid mode reports lexical rank, semantic rank, similarity and reciprocal-rank-fusion score so an investigator can see why a result appeared.

Semantic investigator queries can be logged by digest. The optional index does not automatically change agent recall or promote a quarantined memory.
