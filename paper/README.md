# Aetnamem technical papers

Author: **aetna000.com**

This directory contains two reproducible technical manuscripts and one
publication-ready article collection.

## X article collection

> **Aetnamem Explained: Twenty Articles on Governed Memory for AI**

`aetnamem-x-articles.tex` contains 20 standalone, high-level articles derived
from the governed-memory paper. They explain lifecycle, trust, quarantine,
deterministic recall, rebuildable graphs, recall forensics, audit checkpoints,
approval-bound effects, encryption boundaries, scale evidence, and the product
direction. The language is intended for X Articles while retaining the source
paper's limitations and measured scope.

Build the collection with:

```bash
cd paper
make aetnamem-x-articles.pdf
```

## Governed memory white paper

> **Governed Memory Without Embeddings: Deterministic Recall, Rebuildable
> Graph Indexes, and Approval-Bound Effects in aetnamem**

This arXiv-ready technical white paper documents release `v0.3.0`. It explains
the governed memory lifecycle, the decision not to use embedding retrieval,
candidate-capped FTS5 and graph recall, confidence and ambiguity boundaries,
audit and crash behavior, platform-specific encryption, and approval-bound
workspace effects. It separates implemented guarantees from deployment
assumptions and unvalidated scale projections.

Source and evidence:

- `governed-memory.tex` and `sections/governed-memory/`;
- `governed-memory-references.bib`;
- `data/governed-memory-probe.json` and
  `scripts/run_governed_memory_probe.py`;
- `aetnamem-governed-memory.pdf`.

Build only this paper with:

```bash
cd paper
make aetnamem-governed-memory.pdf
```

## Control-plane report

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
- `aetnamem-governed-memory.pdf` - governed memory technical white paper;
- `aetnamem-x-articles.pdf` - 20-article high-level publication collection;
- `build/aetnamem-control-plane.pdf` - intermediate compiled copy;
- `build/aetnamem-governed-memory.pdf` - intermediate governed memory copy;
- `figures/*.pdf` - vector publication figures;
- `figures/*.png` - review-friendly figure previews.

`make verify` checks the pinned tabular data, queries the recorded demo
database, executes both standalone verifiers against the committed demo
artifacts, and confirms that the governed-memory manuscript matches its probe
JSON. The papers' benchmark tables are pinned snapshots; refreshing them
requires a deliberate new benchmark run and provenance update.

## Submission notes

Before an arXiv submission, confirm the author attribution (`aetna000.com`),
affiliation, email, license selection, and subject category. The manuscripts
intentionally include limitations, evidence provenance, and reproducibility
statements; do not remove those to make the results sound stronger than the
evidence.
