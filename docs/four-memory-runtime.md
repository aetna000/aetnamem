# AetnaMem four-memory runtime

> **AetnaMem remembers whether remembering actually helped.**

AetnaMem coordinates four kinds of memory behind one MCP connection. An agent
does not decide which database to call and does not receive four sets of tools.
The runtime gathers each contribution, applies one global budget, records a
manifest, and returns one context pack.

## Start with the ten-step wizard

```bash
python3 -m pip install --upgrade aetnamem
aetnamem setup
```

The default output is `~/.aetnamem/runtime.json`. To accept the safe starter
defaults without prompts:

```bash
aetnamem setup --yes --preset starter --subject you \
  --agent openclaw-primary
```

Available presets:

```bash
aetnamem runtime presets
```

- `starter`: balanced local defaults for one person and one agent.
- `private`: smaller context and stricter semantic matching.
- `team`: larger budgets and team policy fields for a trusted multi-agent host.
- `benchmark`: deterministic, generous budgets for comparative evaluation.

Presets are copied into ordinary JSON. They are starting points, not hidden
server behavior.

## Connect OpenClaw

```bash
openclaw plugins install npm:openclaw-memory-aetnamem@latest --pin
openclaw aetnamem setup --single-user --subject you \
  --orchestrated --runtime-config ~/.aetnamem/runtime.json
```

The plugin discovers `memory_prepare_turn` through MCP `tools/list`. If
orchestration is enabled but the connected AetnaMem version does not expose
that tool, the default `fallback: "legacy"` behavior uses the existing persona
and semantic recall hooks. Existing plugin configurations remain legacy unless
orchestration is explicitly enabled.

## What happens on every turn

1. OpenClaw sends the user request and explicit task state to
   `memory_prepare_turn`.
2. Working memory contributes current goal, progress, and constraints.
3. Semantic memory contributes governed active records through the existing
   `Memory` retrieval pipeline.
4. Episodic memory contributes relevant recorded outcomes and promoted
   lessons.
5. Procedural memory selects relevant, versioned `SKILL.md` files.
6. The compiler enforces per-plane and global budgets.
7. The runtime stores the contribution hashes and final context manifest.
8. Stable context is placed in the system prefix and dynamic context near the
   current turn.
9. The agent acts.
10. OpenClaw calls `memory_record_outcome` with the success or failure reported
    by that integration.

A failed run that used a procedure also creates a quarantined procedure
improvement proposal. It records that the version needs review; it does not
rewrite or activate a `SKILL.md` file automatically.

The returned contract is `aetnamem-runtime-pack-v1`. It contains the unchanged
`aetnamem-context-pack-v1` semantic result, per-plane provenance, degraded
planes, placement guidance, and a manifest digest.

## Configuration

An abbreviated starter configuration:

```json
{
  "format": "aetnamem-runtime-config-v1",
  "preset": "starter",
  "db_path": "/home/you/.aetnamem/memories.db",
  "scope": {
    "subject_id": "you",
    "agent_id": "openclaw-primary"
  },
  "budgets": {
    "total_chars": 4200,
    "working_chars": 700,
    "semantic_chars": 1800,
    "episodic_chars": 900,
    "procedural_chars": 800
  },
  "planes": {
    "working": { "enabled": true },
    "semantic": {
      "enabled": true,
      "max_records": 3,
      "min_score": 0.3
    },
    "episodic": {
      "enabled": true,
      "max_outcomes": 3
    },
    "procedural": {
      "enabled": true,
      "skill_paths": ["/home/you/.openclaw/skills"]
    }
  },
  "failure_policy": "degrade",
  "cml": {
    "mode": "off",
    "design": "bernoulli",
    "policy_version": "cml-policy-v1",
    "assignment_probability": 0.5,
    "eligible_planes": [],
    "pinned_planes": []
  }
}
```

Validate it with:

```bash
aetnamem runtime validate --config ~/.aetnamem/runtime.json
aetnamem runtime status --config ~/.aetnamem/runtime.json
```

`failure_policy: "degrade"` allows a turn to proceed when one plane is
unavailable and names that plane in the result. `"fail"` stops preparation.

## Experimental Causal Memory Ledger

CML is default-off instrumentation for answering a stricter question than
retrieval relevance: did including an eligible memory contribution improve a
verified outcome enough to justify its cost?

| Mode | Context behavior | Ledger behavior |
|---|---|---|
| `off` | Existing runtime-pack v1 behavior | No intervention rows |
| `shadow` | Shows every candidate contribution | Records the assignment that would have been applied |
| `experiment` | Applies the recorded assignment to eligible contributions | Records assigned and applied arms before compilation |

`experiment` is currently restricted to the `benchmark` preset. Shadow mode is
the safe way to validate instrumentation in an ordinary deployment because it
does not withhold memory.

An explicit experimental configuration looks like:

```json
{
  "preset": "benchmark",
  "cml": {
    "mode": "experiment",
    "experiment_id": "four-plane-study-001",
    "design": "bernoulli",
    "policy_version": "cml-policy-v1",
    "assignment_probability": 0.5,
    "eligible_planes": ["working", "episodic", "procedural"],
    "pinned_planes": ["semantic"],
    "seed": "supply-from-a-trusted-benchmark-runner"
  }
}
```

CML produces `aetnamem-runtime-pack-v2`, commits candidate hashes, assignment
probabilities, assigned and applied arms, stratum, policy hash, and a seed
commitment. It never emits the raw seed. When closing a CML run, copy the
returned `manifest_sha256`:

```bash
aetnamem runtime outcome RUN_ID --success \
  --manifest-sha256 MANIFEST_SHA256 \
  --metrics '{"verified_success":true,"input_tokens":1234}' \
  --config ~/.aetnamem/runtime.json
```

This is experimental measurement infrastructure, not evidence that causal
benefit has been demonstrated. See the
[current status](current-status.md) and [research plan](../plan.md).

## Try the lifecycle without an agent

Prepare a turn:

```bash
aetnamem runtime prepare "Upload the customer report" \
  --config ~/.aetnamem/runtime.json \
  --task-state '{"goal":"upload report","progress":"PDF generated"}' \
  --session demo --task report
```

Copy the returned `run_id`, then close the loop:

```bash
aetnamem runtime outcome RUN_ID --failure \
  --config ~/.aetnamem/runtime.json \
  --summary "The upload timed out"
```

A failed outcome may create a quarantined lesson. It does not affect later
turns until a trusted operator reviews and promotes it:

```bash
aetnamem runtime promote-lesson LESSON_ID \
  --config ~/.aetnamem/runtime.json
```

Purge a value from semantic records and matching runtime payload copies:

```bash
aetnamem runtime forget --utterance "Forget my report format." \
  --config ~/.aetnamem/runtime.json
```

This returns `aetnamem-runtime-deletion-receipt-v1`. Existing content digests
and identifiers remain as non-content evidence; matching working snapshots,
outcomes, lessons, and compiled contribution payloads are cleared.

## Generic MCP

```bash
aetnamem runtime mcp --config ~/.aetnamem/runtime.json
```

This endpoint exposes the original 15 memory tools unchanged, followed by:

- `memory_prepare_turn`
- `memory_record_outcome`

The default `aetnamem mcp` command exposes only the original catalog. This
keeps existing generic MCP clients, schemas, prompts, and OpenClaw releases
compatible.

## Safety and scope

The configuration pins `subject_id` and `agent_id`. Agent-supplied MCP
arguments may refine session, task, and turn IDs, but cannot impersonate a
different configured identity.

- Working snapshots are keyed by subject, agent, session, and task.
- Semantic records retain the existing subject isolation.
- Episodic outcomes and lessons are agent scoped in the embedded runtime.
- Procedures are content-addressed, versioned, and related as `informed_by`.
- Procedure selection never authorizes tools or external effects.
- Raw hidden reasoning is not a supported working-memory input.
- Failure-derived lessons begin quarantined.
- Outcome retries are idempotent.
- Generic CLI and MCP outcomes are `caller_asserted`. A trusted host adapter
  must authenticate its own evidence before using `host_attested`.

The embedded reference runtime uses one SQLite file. Separate provider
processes can implement `MemoryPlaneProvider` and be injected through
`MemoryRuntime(..., providers={"episodic": adapter})`, but production remote
deployment still requires the host to supply authentication, networking,
authorization, and an appropriate concurrent storage backend.
