# Aetnamem scientific report

This directory is a reproducible paper package for:

> **Evidence Before Effect: Aetnamem's Auditable Memory and Guarded-Action
> Control Plane for AI Agents**

The manuscript separates three kinds of evidence:

- a fresh local run of MemoryStackBench `seven_sins_v0_1` against aetnamem
  commit `0cd082c9cac14f35a66ff946395a31847322005d`;
- the public 19-target leaderboard snapshot at MemoryStackBench commit
  `10b9407ce54c92bcb8aee24099505427aabeebcd`;
- the deterministic flagship demo and its committed SQLite/checkpoint evidence.

The phrase "perfect benchmark result" means 33/33 check-level assertions,
5/5 scenarios, and 81/81 severity-weighted points. It is a deterministic
memory-engine result, not a score for a language model. Twelve of the 19 public
targets reached 33/33 in the pinned snapshot, so the paper reports a tie rather
than claiming a unique leaderboard win.

## Build

Requirements:

- Python 3.10+ with Matplotlib;
- Tectonic 0.16+ (or adapt the Makefile for another LaTeX engine).

```bash
cd paper
make
make verify
```

Outputs:

- `aetnamem-control-plane.pdf` - shareable compiled paper;
- `build/aetnamem-control-plane.pdf` - intermediate compiled copy;
- `figures/*.pdf` - vector publication figures;
- `figures/*.png` - review-friendly figure previews.

`make verify` checks the pinned tabular data, queries the recorded demo
database, and executes both standalone verifiers against the committed demo
artifacts. The paper's benchmark tables are pinned snapshots; refreshing them
requires a deliberate new benchmark run and provenance update.

## Submission notes

Before an arXiv submission, confirm the author name, affiliation, email,
license selection, and subject category. The manuscript intentionally includes
limitations, benchmark-owner disclosure, and a reproducibility statement; do
not remove those to make the result sound stronger than the evidence.
