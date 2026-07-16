# Benchmark integration

Canonical copies of the aetnamem integration files for
[MemoryStackBench](https://github.com/aetna000/MemoryStackBench):

- `targets/aetnamem.yaml` — target manifest
- `adapters/aetnamem.py` — `MemoryStackAdapter` implementation

CI overlays these onto a fresh MemoryStackBench clone and requires 33/33 on
`seven_sins_v0_1` before a change can merge. Once these files are upstreamed
into MemoryStackBench itself, the overlay step goes away and the benchmark
repo stays the neutral referee.

## Local graph scale probe

`graph_recall.py` creates a temporary in-memory store, inserts synthetic
records plus a two-hop relation, and compares bounded lexical and graph recall.
It reports median/p95 latency, target rank, logged candidate count, and graph
nodes visited:

```bash
python bench/graph_recall.py --records 10000 --iterations 25
```

This is a repeatable local probe, not a replacement for MemoryStackBench or a
claim about production hardware. Use it to catch accidental O(N) retrieval or
audit-payload growth while changing graph retrieval.
