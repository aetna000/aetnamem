# AetnaMem Architecture, Causal Memory Ledger, and Research Plan

- **Plan status:** normative roadmap
- **Last revised:** 2026-07-24
- **Public baseline:** Python `v0.5.0`, OpenClaw npm `v0.3.0`
- **Next research milestone:** Causal Memory Ledger in benchmark-only mode

## 1. Executive decision

AetnaMem will continue to coordinate four kinds of agent memory:

- **Working:** the current goal, constraints, progress, and explicit task state.
- **Semantic:** facts, preferences, relationships, policies, and current knowledge.
- **Episodic:** previous attempts, outcomes, failures, near misses, and lessons.
- **Procedural:** applicable skills, instructions, and their exact versions.

Supporting four planes is the foundation, not the final differentiator.

The next product and research bet is the **Causal Memory Ledger (CML)**:

> **AetnaMem should measure whether remembering caused a better agent outcome, not merely record that a memory was retrieved.**

The intended product position is:

> **AetnaMem is the evidence-based memory control plane. It measures which memories actually improve an agent, preserves the proof, and spends context only where memory earns its place.**

A shorter product line is:

> **AetnaMem remembers whether remembering actually helped.**

This plan makes CML the central scientific contribution while retaining the
four-plane runtime, generic MCP support, local-first operation, auditability,
deletion, provenance, and compatibility with existing pip, npm, and OpenClaw
users.

Implementation status on 2026-07-24: Phase 1 has started. Release v0.5.0
contains default-off `off`, `shadow`, and benchmark-only `experiment` modes,
pre-compilation intervention records, assigned/applied arm and propensity
logging, runtime-pack v2, structured outcomes, manifest binding, and OpenClaw
manifest forwarding. The trusted outcome adapter, manifest verifier,
benchmark isolation, balanced allocator, causal estimators, synthetic
identification benchmark, Grok study, and held-out evaluation remain
unfinished. The canonical status table is
[`docs/current-status.md`](docs/current-status.md).

## 2. Product thesis

The complete system is:

```text
                         Agent host
                  Grok CLI / OpenClaw / MCP
                              │
                              ▼
                      AetnaMem runtime
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼                   ▼
       Working            Semantic            Episodic           Procedural
       candidates         candidates           candidates          candidates
          └───────────────────┴───────────────────┴───────────────────┘
                                      │
                                      ▼
                       Eligibility and pinning policy
                                      │
                                      ▼
                         Causal Memory Ledger
                     pre-outcome treatment assignment
                                      │
                                      ▼
                          Bounded context compiler
                                      │
                                      ▼
                              Agent action
                                      │
                                      ▼
                     Host-attested result and cost
                                      │
                                      ▼
                    Effect estimates and confidence
                                      │
                                      ▼
                   Retrieval, promotion, or demotion
```

The four planes answer **what could be remembered**. CML answers **what was
worth remembering for this class of task**.

Configuration may change topology, storage, budgets, and policy, but it should
not present the planes as four unrelated products. One deployment may benefit
from every plane while learning that some tasks need only a subset.

## 3. Current status

### 3.1 Public baseline

The latest public tag is `v0.5.0`. Its compatibility surface includes:

- `pip install aetnamem`
- `from aetnamem import Memory`
- the existing CLI and console scripts
- the default `aetnamem mcp` server and its 15-tool catalog
- `aetnamem-context-pack-v1`
- the existing SQLite records, episodes, retrieval evidence, deletion receipts,
  and audit chain
- the published OpenClaw plugin behavior

Nothing in CML may silently change those contracts.

### 3.2 Implemented in v0.5.0

The release contains a validated four-plane runtime:

- `MemoryRuntime` above the existing `Memory` compatibility engine
- working, semantic, episodic, and procedural providers
- scoped task, subject, agent, session, and run identities
- one bounded cross-plane context compiler
- hashed context manifests and stored plane contributions
- structured, idempotent outcome recording intended for a trusted host
- quarantined lesson and procedure-improvement proposals
- versioned `SKILL.md` selection that may inform but never authorize an action
- additive runtime sidecar tables
- four-plane deletion behavior
- a 10-step setup wizard and predefined configurations
- opt-in runtime CLI and MCP operations:
  - `memory_prepare_turn`
  - `memory_record_outcome`
- an opt-in OpenClaw orchestration path with capability detection and legacy
  fallback
- a deterministic four-plane coverage and leave-one-plane-out harness

The latest local validation reported:

- Python: `193 passed, 4 skipped`
- OpenClaw: build, typecheck, tests, and smoke checks passed
- Python wheel and npm package dry-run checks passed

This is released functionality, but it is not scientific proof that the four
planes or CML improve model outcomes.

The current generic MCP boundary does not authenticate the caller. Therefore,
`memory_record_outcome` input is caller-asserted unless it arrives through a
separately authenticated host adapter or carries verifiable receipts. The CML
study must correct this trust distinction; merely calling the outcome tool does
not make a result host-attested.

### 3.3 Not yet implemented or proven

- an authenticated trusted-outcome adapter and independent CML verifier
- benchmark database and namespace isolation
- a balanced block allocator beyond deterministic Bernoulli assignment
- causal estimators, confidence intervals, and interaction analysis
- synthetic recovery of planted effects under deliberate confounding
- the frozen Grok CLI study and held-out outcome-per-cost evaluation
- pre-action seed commitments
- explicit `cml.mode: off | shadow | experiment` activation
- authenticated outcome attestation and strict scope/manifest binding
- effect estimation or confidence intervals
- model-backed 16-condition factorial experiments
- learned memory selection evaluated on held-out tasks
- production adaptive allocation
- independent replication of causal claims
- remote provider configuration, authenticated multi-user deployment, or a
  production distributed memory backend

### 3.4 Known gaps to correct before experimentation

- Current runtime configuration has no independent `cml.mode` safety boundary.
- The generic MCP transport does not authenticate outcome or task-state
  assertions.
- Outcome submission must be more tightly bound to committed scope and manifest
  identity for a causal study.
- The current four-plane harness reuses seeded runtime state and checks marker
  presence; it is not an independent-arm model-quality experiment.
- Exact procedure-source digests and all runtime dependencies must be frozen in
  each experimental manifest.
- Direct lesson promotion is an administrative operation and needs a trusted
  approval boundary before production use.
- Raw observations, derived hypotheses, causal estimates, alerts, and promoted
  lessons need explicit lifecycle separation.

## 4. Why AetnaMem is unusually ready

The repository already has most of the experimental spine:

- Contributions are collected and persisted before compilation in
  [orchestrator.py](aetnamem/runtime/orchestrator.py#L84).
- Context manifests are hashed in
  [compiler.py](aetnamem/runtime/compiler.py#L60).
- Outcomes and tool-receipt digests are joined to runs in
  [store.py](aetnamem/runtime/store.py#L379).

The missing insertion point is immediately before `compile_context()`:

```text
provider candidates are persisted
              │
              ▼
NEW: eligibility, pinning, and treatment assignment
              │
              ▼
compile_context() receives only pinned or admitted contributions
```

The minimal new intervention record contains:

- candidate contribution hash
- included or withheld assignment
- assignment probability
- experimental stratum
- random-seed commitment
- policy version
- eligibility status
- pinned or non-experimental reason

Safety, identity, policy, deletion, and authorization context must always be
pinned. Only explicitly eligible informational memory may be randomized.
Initial randomization is permitted only in controlled benchmark mode.

## 5. One new primitive: the Causal Memory Ledger

### 5.1 Governing rule

A memory contribution is beneficial only when controlled admission of that
contribution improves a downstream outcome distribution.

These observations are insufficient:

- it was retrieved;
- it was semantically similar;
- it appeared in a successful run;
- an LLM said it was useful;
- removing it changed a marker-coverage score.

Harder tasks naturally request more episodic and procedural context. Therefore,
observational logs can make helpful memory look harmful, or give irrelevant
memory credit for a successful run. CML addresses this confounding through
pre-outcome randomized assignment.

### 5.2 Turn lifecycle

For every experimental turn:

1. All enabled providers produce their normal candidate contributions.
2. AetnaMem persists every candidate before assignment.
3. Policy classifies each contribution as pinned, eligible, or ineligible.
4. The registered design assigns eligible contributions to admitted or
   withheld conditions.
5. AetnaMem persists the assignment, propensity, stratum, policy version, and
   seed commitment.
6. The compiler receives pinned contributions plus admitted eligible
   contributions.
7. The complete candidate and treatment manifest is hashed and audited before
   the agent acts.
8. The agent receives only the compiled context, not the hidden experimental
   seed.
9. The trusted host records outcome, tokens, monetary cost, latency, tool
   receipts, and policy violations.
10. An analyzer estimates main effects and interactions with uncertainty.
11. Experimental evidence may later inform retrieval policy, but never grants
    action authority.

### 5.3 Initial unit of intervention

The first scientific unit is the **plane contribution per run**, not an
individual sentence or unique memory item.

The four binary factors are:

```text
W = working contribution admitted
S = semantic contribution admitted
E = episodic contribution admitted
P = procedural contribution admitted
```

The full benchmark therefore has `2^4 = 16` treatment cells.

System instructions, the current user request, safety controls, identity,
authorization, and the minimum state needed to execute the task are outside
these factors and always remain available.

Item-level effects may be investigated later. One observation cannot identify
the causal effect of a unique memory item, and the product must not claim that
it can.

### 5.4 Estimands

For plane `p`, the primary causal estimand is:

```text
τp = E[Y | do(Zp = 1)] - E[Y | do(Zp = 0)]
```

The factorial design must also estimate interactions such as:

```text
τsemantic×procedural
```

because a fact and a procedure may be valuable together even when neither is
sufficient alone.

The primary outcome `Y` is **host-verified task success under a fixed cost
budget**. Cost-adjusted utility may be reported as a secondary analysis:

```text
utility = success
        - λ × monetary_cost
        - μ × latency
        - ν × policy_violations
```

All weights and sensitivity analyses must be declared before examining final
results. The report should also show the quality/cost Pareto frontier so that an
arbitrary utility formula cannot hide a tradeoff.

## 6. Minimal implementation delta

### 6.1 Activation modes

CML requires an explicit trusted configuration:

```yaml
cml:
  mode: off  # off | shadow | experiment
```

- `off` is the default for new installations, upgrades, normal setup, legacy
  MCP, and ordinary runtime use. It performs no assignment or experimental
  write.
- `shadow` records eligibility and a would-have-been assignment, but compiles
  the same context as the deterministic runtime.
- `experiment` may alter context only for contributions explicitly marked
  experiment-eligible under a registered protocol.

Enabling four-plane orchestration does not enable CML. Installing or upgrading
pip/npm, loading a preset, or starting OpenClaw must never silently enable
randomization, promotion, network access, or external effects.

The benchmark runner uses a disposable clone of an immutable seed database and
a separate deployment, subject, agent, and experiment namespace. It must refuse
an ordinary production database unless an explicit dangerous override is
provided and recorded. Benchmark lessons and procedure proposals never promote
into production.

### 6.2 Storage

Add one additive sidecar table:

```sql
CREATE TABLE runtime_interventions (
  decision_id TEXT NOT NULL,
  experiment_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  plane TEXT NOT NULL,
  candidate_contribution_id TEXT NOT NULL,
  candidate_sha256 TEXT NOT NULL,
  assigned INTEGER NOT NULL,
  propensity REAL NOT NULL,
  arm_id TEXT NOT NULL,
  joint_propensity REAL NOT NULL,
  design TEXT NOT NULL,
  stratum TEXT NOT NULL,
  seed_commitment TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  policy_sha256 TEXT NOT NULL,
  eligibility TEXT NOT NULL,
  pinned_reason TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, plane),
  UNIQUE (decision_id),
  FOREIGN KEY (run_id) REFERENCES runtime_runs(id)
);
```

Pinned contributions use `assigned = 1`, `propensity = 1`, and a non-empty
`pinned_reason`. Disabled or absent planes are not misrepresented as randomized
zero assignments. The applied joint-arm probability is stored because context
budgets, ordering, and blocking can make plane assignments dependent; marginal
per-plane probabilities alone are then insufficient.

Outcome storage also needs versioned structured metrics for:

- verifier name and version
- success or bounded reward
- prompt and completion tokens
- monetary cost and currency
- wall-clock and model latency
- tool-call count
- policy or safety violations
- near-miss classification
- missing-outcome reason

This may be an additive `metrics_json` field or a sidecar outcome-metrics table.
It must not alter legacy outcome or receipt formats.

### 6.3 Runtime

Add an intervention policy between contribution persistence and
`compile_context()`:

```python
candidates = gather_and_persist_contributions(...)
assignment = intervention_policy.assign(candidates, scope, experiment)
admitted = assignment.pinned_or_admitted(candidates)
pack = compile_context(contributions=admitted, ...)
```

The intervention policy must:

- default to deterministic all-admitted behavior;
- require explicit experiment configuration;
- use a registered and versioned design;
- support reproducible block assignment;
- store the randomization algorithm and seed commitment;
- preserve the same decision on retries and idempotent replays;
- enforce configured propensity floors and ceilings;
- reject unknown planes or invalid propensities;
- fail closed for experimental assignment errors while preserving the
  non-experimental runtime path;
- never classify model-generated text as trusted outcome evidence.

If the decision cannot be committed atomically before an outcome is observable,
the run must degrade explicitly to non-experimental mode and must be excluded
from causal estimation.

### 6.4 Manifest and audit order

Experimental manifests must bind:

- the complete candidate set and hashes;
- eligibility and pinning decisions;
- assignments and propensities;
- compiled stable and dynamic context hashes;
- model, prompt, tool, procedure, policy, and verifier versions;
- experiment, block, task, and run identities.
- the joint treatment arm and probability actually applied after all filters
  and budget rules.

The audit order is:

```text
candidate commitment
→ assignment commitment
→ compiled-context commitment
→ agent execution
→ host outcome
→ effect analysis
```

CML-enabled output should use a negotiated
`aetnamem-runtime-pack-v2`. With CML disabled,
`aetnamem-runtime-pack-v1` remains unchanged.

For CML runs, `memory_record_outcome` must bind the submitted result to the
committed `run_id`, manifest digest, trusted scope, predeclared metric, and
verifiable host/action receipts. A retry cannot trigger re-randomization, and a
late correction is appended as a versioned correction event rather than
rewriting the original assignment or observation.

Observed assignments and outcomes remain separate from derived estimates,
causal hypotheses, alerts, lessons, and procedure proposals. Derived artifacts
cite their source decision/outcome IDs, estimator version, assumptions, and
uncertainty.

The governed derivation lifecycle is:

```text
observed → analyzed/hypothesis → alertable → promoted or rejected → superseded
```

No single failure, surprising result, agent-written summary, or positive effect
estimate automatically rewrites semantic or procedural memory.

### 6.5 Public interfaces

No new model-visible MCP operation is required. Continue to use:

- `memory_prepare_turn`
- `memory_record_outcome`

Experiment configuration belongs to the trusted runtime launch configuration,
not model-selected tool arguments.

An offline CLI may provide:

```text
aetnamem runtime experiment validate
aetnamem runtime experiment analyze
aetnamem runtime experiment export
```

These commands must not change the default MCP catalog or ordinary runtime
behavior.

## 7. Safety and governance contract

### 7.1 Context that is never randomized

- system and safety instructions
- action authorization or denial evidence
- authenticated subject, tenant, team, and agent scope
- deletion tombstones and revocations
- explicit user constraints
- mandatory current task inputs
- required tool schemas
- legal, medical, financial, or other high-stakes safeguards

Procedural memory may inform an action. It cannot authorize that action.
`informed_by` and `authorized_by` remain separate evidence relations.

### 7.2 Experiment eligibility

A contribution is experiment-eligible only when:

- omission cannot remove a safety or authorization control;
- the benchmark owner has declared the task suitable for randomization;
- the contribution and outcome can be tied to a stable run identity;
- the verifier does not depend on knowing the treatment assignment;
- the memory snapshot and carryover policy are controlled;
- privacy and deletion requirements allow the evidence to be retained for the
  declared period.

Live randomization is prohibited initially. High-stakes deployments remain
non-experimental unless a separately reviewed protocol authorizes them.

Raw context and outcome payloads are not copied into the ledger by default.
The durable experimental record should use contribution IDs, digests, minimal
metrics, and governed retention metadata. Raw payload retention requires
separate opt-in encryption, redaction, deletion, and expiry policy. Aggregation
across tenants or subjects requires explicit privacy review.

### 7.3 Outcome trust

Primary outcomes must come from deterministic or host-attested evidence such as:

- tests or validators;
- environment state;
- tool receipts;
- explicit user acceptance;
- policy engines;
- independently versioned scorers.

An agent's self-report and an uncalibrated LLM judge may be secondary signals,
but not the sole primary endpoint.

The Grok agent must not grade itself or call a promotion path. In the decisive
study, an independent controller runs the verifier after Grok exits, then binds
the result and receipt digest through the trusted outcome adapter. Caller-
asserted `task_state` and generic MCP outcome arguments retain that lower trust
classification.

## 8. Scientific questions and hypotheses

### Research question

Can propensity-logged randomized admission across four memory planes identify
which memory configurations improve tool-using agent outcomes, and can those
estimates produce a better held-out quality/cost policy than fixed or
relevance-only memory?

### Pre-registered hypotheses

- **H1 — identification:** CML recovers planted plane effects and interactions
  under deliberately confounded candidate availability.
- **H2 — outcome:** at least one CML-selected configuration improves
  host-verified success under a fixed cost budget over the strongest fixed
  baseline.
- **H3 — efficiency:** a policy learned from CML evidence improves held-out
  successful tasks per dollar over always-including all four planes.
- **H4 — interaction:** the design detects tasks where combinations of memory
  planes produce value that single-plane analysis misses.
- **H5 — safety:** randomization never removes pinned controls or increases
  unauthorized actions beyond the pre-registered non-inferiority margin.

Failure to reject the null hypothesis is a valid result. AetnaMem must not
rewrite the claim after seeing the data.

## 9. The decisive experimental program

Grok CLI is the first reference agent. It must be prominent in the artifact,
transcripts, reports, and demonstration. A second model or agent host is needed
before claiming model-independent generality.

### Phase A — protocol and frozen baseline

Before implementing adaptive behavior:

1. Define the treatment factors, eligible content, and pinned content.
2. Register the primary and secondary outcomes.
3. Version all task fixtures and host verifiers.
4. Define the randomization, blocking, missing-data, and stopping rules.
5. Perform a power analysis instead of choosing an arbitrary run count.
6. Freeze compatibility fixtures and the current deterministic runtime.
7. Register the analysis code against synthetic data before real results exist.

**Exit condition:** another engineer can reproduce the assignment and analysis
from the protocol without making additional methodological decisions.

### Phase B — synthetic causal benchmark

Build a controlled generator with known main effects and interactions.

The generator must deliberately introduce observational confounding:

- difficult tasks request episodic and procedural memory more often;
- irrelevant memories correlate with successful task classes;
- some memories are useful only in combination;
- some retrieved memories are neutral or harmful;
- plane availability varies independently of true usefulness.

Compare:

1. naive success correlation;
2. observational regression without assignment propensities;
3. deterministic leave-one-plane-out analysis;
4. propensity-aware CML estimation.

Report:

- effect mean absolute error;
- sign recovery;
- bias;
- 95% confidence-interval coverage;
- false-positive rate;
- interaction recovery;
- sensitivity to missing outcomes and treatment non-compliance.

**Exit condition:** CML recovers planted effects and interactions within
pre-registered tolerances, with calibrated uncertainty. Observational
attribution should exhibit the expected bias.

### Phase C — Grok CLI 16-condition factorial

Run a balanced `2^4` factorial experiment covering every subset of working,
semantic, episodic, and procedural contributions.

| Arm | Admitted supplemental planes |
|---|---|
| `0000` | none |
| `0001` | P |
| `0010` | E |
| `0011` | E + P |
| `0100` | S |
| `0101` | S + P |
| `0110` | S + E |
| `0111` | S + E + P |
| `1000` | W |
| `1001` | W + P |
| `1010` | W + E |
| `1011` | W + E + P |
| `1100` | W + S |
| `1101` | W + S + P |
| `1110` | W + S + E |
| `1111` | W + S + E + P |

Block randomization by:

- task family;
- task instance;
- Grok model and CLI version;
- execution period;
- memory snapshot;
- seed, when Grok exposes one.

If Grok does not expose deterministic seeds, repeat each condition sufficiently
and treat model stochasticity as part of the outcome distribution.

Prevent carryover by freezing or cloning the initial memory database for each
experimental trajectory. If the task itself studies learning across sessions,
randomize at the complete trajectory or cluster level rather than individual
turns.

Every arm begins with the same underlying four-plane data. Withholding changes
admission, not storage. In the primary analysis, budget removed with one plane
is not reallocated to another plane; otherwise a leave-one-plane contrast also
changes the capacity of the remaining planes.

Task families must include:

- a working-memory requirement involving unfinished explicit state;
- a semantic requirement involving a changed fact, preference, or policy;
- an episodic requirement involving a prior failed attempt or near miss;
- a procedural requirement involving the correct versioned skill;
- pairwise synergy where neither plane alone is sufficient;
- an all-four-plane task;
- relevant-looking distractors;
- stale, conflicting, and poisoned informational memory;
- a task where no supplemental memory is the best choice.

The current user request and required safety instructions are present in every
condition. A `0000` arm means no supplemental four-plane contribution, not an
agent with no instructions or safeguards.

The currently discovered reference binary is `grok 0.2.93
(f00f96316d4b)`. The actual study must record and freeze the installed binary,
model ID, reasoning effort, system instructions, tool permissions, maximum
turns, memory mode, web access, subagent setting, and output format at execution
time. Grok's independent cross-session memory, web search, subagents,
best-of-N, and self-check loops are disabled in the primary study.

The primary integration arm requires Grok to obtain the runtime pack through
the generic MCP path. A smaller controller-injected diagnostic arm may compile
the same pack outside Grok to distinguish memory-quality failure from
tool-selection or adapter failure, but only the direct MCP arm supports an
end-to-end Grok integration claim.

Across all 16 arms, Grok sees identical system instructions, task tools, and
MCP schemas. The experimental gateway must prevent direct legacy recall from
bypassing a withheld plane, and it must prevent Grok from submitting its own
outcome or promoting a lesson. After external validation, the controller calls
the same runtime outcome lifecycle with the verifier receipt.

### Phase D — held-out policy evaluation

Using only training tasks:

1. Estimate plane and interaction effects by task context.
2. Construct a selection policy that chooses an admissible memory subset under
   a cost budget.
3. Freeze the policy and its thresholds.
4. Evaluate it on unseen tasks and fresh memory snapshots.
5. Compare it with every fixed and heuristic baseline.

The primary analysis is intention-to-treat. Per-protocol analysis is secondary.
Confidence intervals must respect blocking and trajectory-level clustering.
Multiple comparisons and researcher degrees of freedom must be controlled in
the registered analysis.

For binary success, use a pre-registered factorial model containing
`W * S * E * P`, task-family and run-block effects, with scenario-level
clustering or random effects. Report absolute success-probability contrasts,
not odds ratios alone. Use scenario-clustered bootstrap or randomization-based
intervals, and adjust the primary family of contrasts for multiplicity. Cost
and latency use paired scenario-level differences or log ratios. “Synergy” is
reserved for a positive pre-registered interaction contrast; `1111` merely
being the best arm is insufficient.

**Exit condition:** the frozen policy improves held-out host-verified success
under the fixed budget or improves success per dollar without exceeding the
safety margin.

### Phase E — external validity and replication

- Repeat the decisive evaluation with at least one non-Grok model or agent host.
- Publish task fixtures, assignments, outcome records, estimator code, and
  environment hashes where licensing and privacy permit.
- Provide an independent verifier for intervention manifests.
- Invite an external reproduction before making a broad scientific claim.

## 10. Required baselines and ablations

Every decisive report compares:

1. no supplemental memory;
2. semantic-only memory;
3. all four planes always included;
4. relevance-based retrieval;
5. outcome weighting without randomization;
6. full CML randomized admission and propensity-aware analysis.

Additional useful comparisons are:

- host-native memory;
- long context, files, RAG, and host-owned skills;
- the current deterministic leave-one-plane-out harness;
- CML without provenance or pre-action commitment;
- CML without pairwise interaction terms;
- embedded versus separate-provider topology once remote providers exist.

The existing `33/33` MemoryStackBench-style result remains conformance
evidence. The existing four-plane marker harness remains integration evidence.
Neither is causal performance evidence.

## 11. Outcomes and reporting

### Primary endpoint

**Host-verified task success under a fixed cost budget.**

### Secondary endpoints

- successful tasks per dollar
- prompt and completion tokens
- wall-clock and model latency
- repeat-error and recovery rate
- stale-memory use
- false-warning rate
- procedure-selection accuracy
- tool calls
- policy and authorization violations
- provenance completeness
- deletion and supersession correctness

### Required report contents

- arm counts and assignment balance
- all exclusions and missing outcomes
- model, CLI, prompt, tool, policy, and verifier versions
- main effects and pairwise interactions
- confidence intervals and exact analysis method
- absolute outcomes, not only relative percentages
- cost/quality Pareto frontier
- all pre-registered failures and negative results
- comparison between observational and randomized conclusions

## 12. Falsification and claim gates

The CML thesis is supported only if all required gates pass:

| Gate | Required evidence | Failure interpretation |
|---|---|---|
| Identification | planted effects and interactions recovered with calibrated uncertainty | estimator or implementation is not trustworthy |
| Agent benefit | CML-selected configuration beats the strongest fixed baseline on the primary endpoint | CML is measurement infrastructure, not yet a performance advantage |
| Held-out value | frozen policy generalizes to unseen tasks | training effects do not support product adaptation |
| Efficiency | benefit remains after tokens, money, and latency are reported | improvement is purchased by unacceptable overhead |
| Safety | pinned controls are never withheld and violation margin is satisfied | production experimentation is blocked |
| Reproducibility | artifacts recreate assignments and headline results | scientific claim remains internal |
| External validity | effect is repeated outside the primary Grok setup | claim must remain Grok- and task-specific |

Specific falsifiers include:

- CML cannot distinguish planted benefit from confounded retrieval frequency.
- Confidence intervals systematically miss known synthetic effects.
- Always including all four planes matches or beats the learned policy at the
  same cost.
- Observational attribution performs equally well under planted confounding.
- Pairwise effects are not stable across tasks or replications.
- Outcome improvements disappear under host verification.
- Safety or authority context is ever assigned to a withheld condition.

If removing event order, provenance, pre-action commitment, or propensities does
not change results, those mechanisms must not be presented as necessary
scientific contributions.

## 13. Academic positioning and claim boundaries

The intended research contribution is not the invention of:

- four categories of memory;
- prediction error;
- contextual bandits;
- generic causal inference;
- replay-based failure attribution;
- memory retrieval or vector similarity.

Related work already studies surprise-gated memory, utility-aware selection,
candidate-memory interventions, and causal replay. A formal literature and
prior-art review is required before using words such as “first” or
“revolutionary.”

The research claim to attempt to earn is:

> **A pre-outcome, tamper-evident, propensity-logged factorial intervention
> ledger across four agent-memory planes, bound to host-verified outcomes and
> used to improve held-out outcome per cost.**

A suitable working paper title is:

> **AetnaMem CML: Causal Evaluation of Four-Plane Memory in Tool-Using Agents**

The current implementation may be described as cognitively inspired, but it
must not be marketed as reproducing human memory or brain mechanisms.

## 14. Compatibility and non-breaking requirements

### Python and CLI

Preserve:

- distribution name `aetnamem`;
- `from aetnamem import Memory`;
- Python 3.10–3.13 support;
- current constructor and method behavior;
- legacy return dictionaries and identifiers;
- existing console-script set;
- existing CLI verbs and JSON envelopes.

CML remains under the opt-in `aetnamem runtime` surface. Base dependencies stay
lightweight.

With CML absent or `mode: off`, legacy and runtime-v1 outputs remain
byte/shape-compatible with their frozen fixtures, and ordinary legacy
operations need not read or write CML tables.

### SQLite and audit history

- Add sidecar tables and columns only.
- Never remodel or reinterpret legacy records and episodes.
- Never rewrite existing audit events or hashes.
- Old databases must open without export/import.
- A v0.4.1 binary must still reopen an upgraded database and perform legacy
  remember, recall, and forget operations.
- Migrations must be idempotent, concurrency-safe, crash-tested, and reject a
  runtime schema newer than the running binary understands.
- Legacy deletion must immediately exclude runtime projections.
- Erased payloads must not be copied permanently into experiment metadata.
- Intervention audit rows contain hashes and governed metadata, not undeletable
  copies of private content.

### MCP

Preserve the default:

```text
aetnamem mcp --db ... --subject ...
```

It must continue to expose the same 15-tool catalog and
`aetnamem-context-pack-v1`.

CML is available only through explicit runtime configuration. Existing runtime
MCP operations are sufficient; do not expose provider- or experiment-specific
tools to the model.

### OpenClaw npm adapter

Preserve:

- npm package name `openclaw-memory-aetnamem`;
- plugin ID `memory-aetnamem`;
- existing hooks and model-visible search/forget tools;
- legacy prompt placement;
- fail-open behavior for unavailable memory;
- capability detection and fallback;
- setup behavior that preserves unknown configuration fields.

The OpenClaw adapter remains thin. Trusted experiment configuration belongs to
the Python runtime, not the agent or npm hook.

### Authority and identity

- Trusted host configuration supplies deployment, tenant, subject, team,
  agent, session, task, run, and turn identity.
- The model cannot select a privileged identity through tool arguments.
- Memory may provide information and procedure suggestions.
- Only the configured policy and host may authorize external effects.

## 15. Implementation phases

### Phase 0 — stabilize the four-plane release (completed in v0.5.0)

Deliver:

- commit-ready Python `v0.5.0` runtime;
- commit-ready OpenClaw npm `v0.3.0` orchestration;
- rerun Python, wheel, npm, OpenClaw, and compatibility checks;
- update the capability matrix with “implemented,” “experimental,” and
  “proven” as separate states;
- correct Node CI to the package's declared version;
- run `npm test` in CI;
- prepare npm trusted publishing.

Exit gate:

- legacy and runtime tests pass;
- package artifacts contain only intended files;
- existing v0.4.1 clients continue to work;
- the release notes do not claim causal benefit.

### Phase 1 — CML observe and assignment mode

Delivered in v0.5.0:

- `runtime_interventions`;
- versioned `off | shadow | experiment` configuration;
- eligibility and pinning policy;
- deterministic Bernoulli allocator;
- random seed commitment;
- joint-arm propensity logging;
- experimental runtime-pack v2;
- structured outcome metrics;
- run/scope/manifest binding;
- OpenClaw manifest forwarding;
- tests proving assignment is stored before outcome submission;
- tests proving configured pinned content cannot be withheld.

Still required to complete Phase 1:

- trusted outcome adapter;
- independent manifest verifier;
- balanced block allocator;
- disposable benchmark database and namespace enforcement.

Default behavior remains off and deterministic.

### Phase 2 — causal benchmark infrastructure

Deliver:

- `bench/causal_memory/`;
- planted-effect and confounding generator;
- factorial assignment runner;
- propensity-aware estimators;
- interaction analysis;
- confidence intervals and randomization checks;
- machine-readable and human-readable reports;
- pre-registered analysis fixtures.

### Phase 3 — Grok CLI reference study

Deliver:

- reproducible Grok CLI runner;
- versioned 16-cell task suite;
- frozen memory snapshots;
- host verifiers;
- token, cost, latency, and tool accounting;
- transcripts and visual evidence;
- complete baseline and ablation report.

No audio, video, or game result substitutes for the machine-verifiable report.
A visual game or demonstration may explain the experiment after the benchmark
is real.

### Phase 4 — held-out memory policy

Deliver:

- effect-aware subset selection;
- confidence-aware abstention;
- fixed cost and safety constraints;
- frozen held-out evaluation;
- rollback to deterministic all-admitted mode;
- explanation receipts showing why a plane was selected without claiming
  individual-item causality.

### Phase 5 — broader productization

Only after the scientific gates:

- add a production opt-in policy;
- display effect cards and uncertainty in diagnostics;
- repeat on a second model/host;
- support remote providers, deadlines, and circuit breakers;
- add authenticated multi-user deployment;
- add a production storage backend and cross-provider deletion proof.

## 16. Release sequence

### Python `v0.5.0` and OpenClaw npm `v0.3.0`

Release the already implemented four-plane foundation:

- embedded runtime;
- presets and setup;
- runtime CLI/MCP;
- outcome loop;
- OpenClaw opt-in orchestration;
- deterministic integration benchmark.

Describe it as an orchestration foundation, not proof of causal improvement.

### Python `v0.5.0` experimental CML foundation

- CML schema and policies;
- runtime-pack v2 negotiation;
- benchmark-only randomized admission;
- structured outcome metrics and exact manifest binding.

### Python `v0.6.0` causal evaluation

- offline propensity-aware analysis;
- synthetic causal validation;
- balanced assignment and independent verification.

### Scientific release candidate

- Grok CLI 16-cell factorial;
- registered analysis;
- full artifacts;
- held-out policy evaluation;
- independent verifier.

### `v0.7+`

- production opt-in adaptation after gates pass;
- second-host validation;
- remote providers;
- authenticated gateway;
- distributed storage and cross-provider governance.

## 17. Documentation and positioning sequence

### Before causal evidence

Use:

> **Four memories. One agent connection.**

Explain that the runtime coordinates all four planes and records their
contributions. Label CML as planned or experimental.

### After synthetic validation

Use:

> **AetnaMem runs controlled experiments over agent memory contributions.**

Do not yet claim improved production outcomes.

### After the held-out Grok gate

If supported by the data, use:

> **AetnaMem measures which memories improve Grok's verified task outcomes and
> selects a lower-cost memory configuration on unseen tasks.**

Keep the scope tied to the tested task distribution.

### After external replication

The broader target positioning becomes:

> **AetnaMem is the evidence-based memory control plane. It measures which
> memories actually improve an agent, preserves the proof, and spends context
> only where memory earns its place.**

The `33/33` conformance result stays in technical compatibility documentation,
not in the primary scientific headline.

## 18. Definition of done

CML is complete only when:

- [x] candidate contributions are committed before assignment;
- [x] assignments and propensities are committed before agent execution;
- [ ] safety, identity, policy, deletion, and authorization context is provably
      pinned;
- [ ] outcomes are host-attested and versioned;
- [ ] synthetic planted effects and interactions are recovered;
- [ ] confidence intervals meet registered calibration criteria;
- [ ] all 16 four-plane conditions run through Grok CLI;
- [ ] required baselines and ablations are reported;
- [ ] the held-out selection policy improves the primary endpoint or
      outcome-per-cost without crossing the safety margin;
- [ ] results reproduce from exported artifacts;
- [ ] a second model or host establishes external validity;
- [ ] pip, CLI, default MCP, SQLite, npm, and OpenClaw compatibility gates pass;
- [ ] README and marketing claims match the measured scope;
- [ ] failures and negative results remain visible.

Until those conditions are satisfied, AetnaMem may claim a governed four-plane
runtime and an experimental causal-measurement architecture—not a
scientifically proven memory advantage.
