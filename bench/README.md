# Benchmark integration

Canonical copies of the aetnamem integration files for
[MemoryStackBench](https://github.com/aetna000/MemoryStackBench):

- `targets/aetnamem.yaml` — target manifest
- `adapters/aetnamem.py` — `MemoryStackAdapter` implementation

CI overlays these onto a fresh MemoryStackBench clone and requires 33/33 on
`seven_sins_v0_1` before a change can merge. Once these files are upstreamed
into MemoryStackBench itself, the overlay step goes away and the benchmark
repo stays the neutral referee.
