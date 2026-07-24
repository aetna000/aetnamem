# AetnaMem current capability status

> **AetnaMem remembers whether remembering actually helped.**

This page is the canonical status boundary for the repository. Release notes
describe historical releases, specifications describe contracts or proposals,
and [`plan.md`](../plan.md) describes future research. None of those documents
should be read as proof that every named capability is generally available.

Status as of **2026-07-24**:

| Area | Status | What that means |
|---|---|---|
| Python `Memory`, CLI, and 15-tool MCP | Public release (`v0.5.0`) | Existing compatibility surface remains supported |
| Four-memory runtime | Public, opt-in (`v0.5.0`) | Working, semantic, episodic, and procedural orchestration |
| OpenClaw orchestration | Public, opt-in (`v0.3.0`) | Runtime hooks with capability detection and legacy fallback |
| CML `off` mode | Public default | Legacy runtime-pack v1 behavior remains unchanged |
| CML `shadow` mode | Experimental | Records deterministic Bernoulli assignments but shows all candidate contributions |
| CML `experiment` mode | Experimental, benchmark-only | May withhold explicitly eligible planes; pinned and ineligible planes remain present |
| CML intervention ledger | Public experimental surface | Stores candidate hashes, assigned/applied state, propensities, arm IDs, stratum, seed commitment, and policy identity before context compilation |
| CML outcome binding | Public experimental surface | CML outcomes must cite the committed context-manifest digest; structured metrics and trust labels are stored |
| Generic runtime MCP outcome trust | Caller asserted | MCP transport alone does not authenticate the host or prove task success |
| Causal estimators and confidence intervals | Planned | No causal-effect report is shipped yet |
| Synthetic planted-effect benchmark | Planned | The identification thesis has not yet passed its falsification gate |
| Grok CLI reference study | Planned | Existing Grok demos show integration behavior, not causal improvement |
| Held-out outcome-per-cost policy | Planned | No production policy should claim learned causal optimization yet |
| Remote memory-plane transport | Planned | The reference runtime is embedded and SQLite-backed |

## Safety defaults

- Every generated preset sets `cml.mode` to `off`.
- Shadow mode records the assignment that would have occurred without changing
  the model-visible context.
- Experiment mode is accepted only with the `benchmark` preset.
- Experiment activation requires an experiment ID, a non-empty seed, explicit
  eligible planes, and an assignment probability strictly between zero and
  one.
- Safety, identity, authorization, and policy context must not be made
  experiment-eligible. The present API enforces configured pinning; the
  benchmark owner is responsible for classifying contributions correctly.
- Raw experiment seeds are not emitted in manifests or status output; only a
  commitment is stored.

## Claims boundary

Implemented instrumentation is not evidence of improvement. AetnaMem can now
commit an intervention before compilation and join a reported outcome to that
manifest. It cannot yet claim that CML improves success, cost, latency, or
safety until the planned synthetic-identification and held-out real-agent
experiments pass.

The existing MemoryStackBench and OpenClaw token/cost results remain useful
for their stated scopes. They are not CML causal results.

## Document map

| Document type | Source |
|---|---|
| Current implementation truth | This page and tests |
| CML architecture and falsifiable research plan | [`plan.md`](../plan.md) |
| Four-memory user and configuration guide | [`four-memory-runtime.md`](four-memory-runtime.md) |
| Current release notes | [`releases/v0.5.0.md`](releases/v0.5.0.md) |
| Public historical release notes | [`releases/v0.4.1.md`](releases/v0.4.1.md) and earlier |
| Remaining engineering work | [`TODO.md`](../TODO.md) |
| Draft application proposals | Documents explicitly marked `draft / proposal` |
