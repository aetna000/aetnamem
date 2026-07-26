# Memory Impact Lab

This directory documents the reproducible AetnaMem 0.6.0 experiment. The
product command creates a complete local lab, including a frozen SQLite
snapshot, isolated workspace, hidden verifier, host signing key and three task
splits. The generated suite has 24 tasks spanning eight required families; it
is a plumbing/shakeout suite, not a powered confirmatory sample:

```bash
aetnamem impact init ./memory-impact-lab
cd ./memory-impact-lab

# Gate 1: prove the estimator on planted effects without spending model tokens.
aetnamem impact run --protocol protocol.yaml --stage synthetic

# Gate 2: run only train and validation tasks across all 16 W/S/E/P arms.
aetnamem impact run --protocol protocol.yaml --stage grok-train \
  --confirm-paid-run

# Gate 3: freeze the policy before any held-out outcome exists, then run held-out.
aetnamem impact run --protocol protocol.yaml --stage grok-held-out \
  --confirm-paid-run

aetnamem impact verify results/ --public-key host-public-key.pem
aetnamem impact report results/ --public-key host-public-key.pem \
  --output reports/memory-impact.html
```

`protocol.example.yaml` is JSON-compatible YAML so AetnaMem needs no YAML
dependency. Copy it only when building a custom suite; `impact init` is the
safer starting point because it generates internally consistent paths and
fixtures.

## What is controlled

Each task block contains every arm from `0000` through `1111` exactly once.
The bit order is working, semantic, episodic, procedural. The random order,
run IDs and assignment tokens are committed before execution. Every run uses
a fresh SQLite and workspace clone. A benchmark fails closed if an assigned
contribution is missing or truncated.

Grok receives the compiled context in its prompt and no AetnaMem MCP tools.
It cannot recall around a withheld plane or record its own verified outcome.
The host verifier runs after Grok exits and signs a receipt binding the
assignment, manifest, output, workspace, verifier and metrics.

## What the result means

The primary estimand is intention-to-treat: the effect of offering a registered
plane bundle, including its content, length, placement and policy. Reports do
not claim that Grok read a memory or that one individual memory caused an
outcome.

The synthetic gate establishes estimator calibration. The Grok trial establishes
an effect only for its registered tasks and model. The final product claim
requires a policy frozen from training evidence to win on unseen task families
under the same budget, followed by a second-model or independent replication.

## Checked-in entry points

- `run_grok.py` starts the paid training stage.
- `verify_outcome.py` is a generic digest-only hidden verifier example.
- `estimate_effects.py` analyzes exported observation JSON.
- `verify_experiment.py` verifies a completed result directory.
- `protocol.example.yaml` shows the registered schema.
- `tasks/`, `snapshots/`, and `reports/` document the expected artifact layout.

Private host keys, run outputs and generated snapshots must not be committed.
