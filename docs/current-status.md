# AetnaMem current capability status

> **AetnaMem remembers whether remembering actually helped.**

This page is the canonical status boundary for the repository. Release notes
describe historical releases, specifications describe contracts or proposals,
and [`plan.md`](../plan.md) describes future research. None of those documents
should be read as proof that every named capability is generally available.

Status as of **2026-08-01**:

| Area | Status | What that means |
|---|---|---|
| Python `Memory`, CLI, and 19-tool MCP | Released core plus experimental compatibility additions | The v0.6.1 surface remains supported; `memory_get_record` and `memory_get_source` are additive in v0.7.0a4 |
| Verified OpenClaw installer | Experimental preview (`v0.7.0a4`) | Engine-owned bridge install/upgrade, absolute executable binding, staged terminal progress, native-memory shadow start, gateway restart/RPC probe, retained-config verification, and rollback on failure |
| Safe Switch control plane | Experimental preview (`v0.7.0a4`) | Customer surface has two states: OpenClaw active while AetnaMem mirrors without changing context, or AetnaMem active; rollback restores OpenClaw. Detailed retrieval/exposure events remain internal audit evidence rather than customer modes |
| Safe Switch OpenClaw adapter | Experimental preview (`npm v0.5.0-experimental.2`) | Private host protocol, startup MCP handshake, silent shadow recall, no agent memory tools during trial, verified native-memory takeover and rollback; active takeover adds system guidance plus an enforced `before_tool_call` guard for the exact frozen native-memory paths |
| OpenClaw native-memory mirror | Experimental preview (`v0.7.0a4`) | Verified byte-for-byte pre-shadow baseline, observed native-state versions, hash-bound Markdown import with source-file and line provenance, isolated SQLite mirror, status/search/trace |
| OpenClaw memory takeover | Experimental preview (`v0.7.0a4`) | Final mirror verification, complete switch-time snapshot, standard `memory_search` / `memory_get` compatibility, audited exact reads, unsupported-capability gate, verified native-path tool guard, active-period memory export, divergent-file preservation, hash-verified rollback, readiness-checked activation from legacy `off`, repeat activation after completed rollback, and explicit interrupted-cutover recovery |
| Safe Switch Hermes adapter | Beta (`v0.6.1`) | General lifecycle-hook plugin that coexists with the selected Hermes memory provider; restart required after installation |
| Safe Switch dashboard | Experimental preview (`v0.7.0a4`) | One functional page: active provider, focused sentence-level memory search with source provenance, exact mirrored source manifest, verification checks, visible elapsed progress for slow operations, and activate/restore control. No preview, canary, emergency, candidate queue, or mock comparison UI. Loopback-only API, daemon-lifetime access key, HttpOnly cookie, CSRF and origin controls remain |
| Dashboard daemon | Experimental preview (`v0.7.0a4`) | Detached local start/open/stop/restart/status/remove lifecycle with PID validation; one protected access URL remains valid for the daemon lifetime, OS-native open bypasses editor link handlers, restart rotates credentials, and startup fails closed without a URL; removal preserves memory and evidence |
| Agent memory skills | Beta (`v0.6.1`) | Provider-neutral governed-memory, audit and trial workflows with deterministic CLI wrappers; skills are procedural guidance, while the engine and authenticated host remain the evidence boundary |
| OpenClaw Safe Switch demonstration | Completed single-task integration check | Actual OpenClaw `2026.7.1-2` and DeepSeek baseline/AetnaMem comparison, activation and verified rollback passed; the 12.9% token reduction is scoped to that one task |
| Multimodal observation envelopes | Public (`v0.5.2`) | Typed text observations, indexed artifact provenance, quarantine, lineage-closing promotion, search/trace surfacing, and exact-artifact deletion; no media bytes or media embeddings; `verified_by_aetnamem` is reserved until an engine-owned byte-hashing path exists |
| MCP media tools | Public (`v0.5.2`) | `memory_observe` and `memory_forget_artifact` add governed multimodal observations |
| Four-memory runtime | Public, opt-in (`v0.5.2`; introduced in `v0.5.0`) | Working, semantic, episodic, and procedural orchestration |
| OpenClaw orchestration | Public, opt-in (`v0.4.0`) | Runtime hooks with capability detection and legacy fallback; unchanged when Safe Switch is disabled |
| Audit search and trace | Public (`v0.5.1`) | Lexical discovery, relationship expansion, text/JSON reports, and optional separate digest-only investigator access chain |
| Semantic investigation search | Public, opt-in (`v0.5.1`) | Exact vector sidecar for `memories`/`search`/`trace`; generation-cached verification, batched canonical validation, strict dimensions, Ollama digest pinning, and hybrid RRF; agent recall unchanged |
| Semantic index deletion | Public, opt-in (`v0.5.1`) | Vector-aware v2 deletion receipt, strict absence verification, and dirty-epoch rebuild signal |
| CML `off` mode | Public default | Legacy runtime-pack v1 behavior remains unchanged |
| CML `shadow` mode | Experimental | Records deterministic Bernoulli assignments but shows all candidate contributions |
| CML `experiment` mode | Experimental, benchmark-only | Bernoulli mode remains compatible; registered balanced-factorial mode applies one precommitted arm and fails closed on token or exposure mismatch |
| CML intervention ledger | Public experimental surface | Stores candidate hashes, assigned/applied state, propensities, arm IDs, stratum, seed commitment, policy identity and balanced schedule binding before context compilation |
| CML outcome binding | Public experimental surface | Caller assertions remain labeled; `host_attested` now requires a valid signed Memory Impact receipt bound to the committed manifest |
| Generic runtime MCP outcome trust | Caller asserted | MCP transport alone does not authenticate the host or prove task success |
| Memory Impact restricted MCP profile | Implemented (`v0.6.0`) | Experimental agent receives no AetnaMem memory or outcome tools; context and verification remain host-controlled |
| Factorial estimators and confidence intervals | Implemented experimental framework (`v0.6.0`) | Reports ITT plane effects, pairwise interactions, 16 arm rates, cost, tokens, latency and missing runs |
| Synthetic planted-effect benchmark | Implemented executable gate (`v0.6.0`) | Repeated calibration checks error, direction, interval coverage, null false positives and a confounded observational comparison |
| Grok CLI reference study | 100-run exploratory recovery pilot complete | Controller, paid edit smoke gate, task schema, metrology, cloning, receipts and report pipeline are implemented. After a 256-call instrumentation-failure study, a corrected capped pilot produced 100 verified receipts, 57 successes and six complete balanced blocks at USD 8.3339928 plus a USD 0.016532 smoke. The all-four arm was 6/6 versus no-memory 1/6, but 284 registered runs remain missing, no held-out policy was run, and no causal product claim is supported |
| Held-out outcome-per-cost policy | Implemented gate; result pending | Policy is frozen from training receipts before held-out runs; no production adaptive behavior or winning claim ships |
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

Implemented experimental machinery is not evidence of improvement. AetnaMem
can precommit balanced interventions, prove exact exposure, accept signed host
outcomes, calibrate its estimator and freeze a policy before held-out
evaluation. It cannot claim that memory improves Grok success, cost, latency,
or safety until a registered paid trial, held-out evaluation and replication
pass.

The existing MemoryStackBench and OpenClaw token/cost results remain useful
for their stated scopes. They are not CML causal results.

## Document map

| Document type | Source |
|---|---|
| Current implementation truth | This page and tests |
| Semantic investigation search | [`semantic-search.md`](semantic-search.md) |
| Multimodal observation boundary | [`multimodal-observations.md`](multimodal-observations.md) |
| CML architecture and falsifiable research plan | [`plan.md`](../plan.md) |
| Four-memory user and configuration guide | [`four-memory-runtime.md`](four-memory-runtime.md) |
| Memory Impact experiment guide | [`memory-impact.md`](memory-impact.md) |
| Current experimental preview notes | [`releases/v0.7.0a4.md`](releases/v0.7.0a4.md) |
| Public historical release notes | [`releases/v0.4.1.md`](releases/v0.4.1.md) and earlier |
| Remaining engineering work | [`TODO.md`](../TODO.md) |
| Draft application proposals | Documents explicitly marked `draft / proposal` |
