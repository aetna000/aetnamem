## Verdict

Yes—this is a strong strategy and probably AetnaMem’s most defensible research direction.

## AetnaMem 0.6.0 implementation status

This plan is now the canonical Memory Impact program. Implementation and
scientific evidence are deliberately tracked separately:

| Phase | 0.6.0 implementation | Evidence gate |
|---|---|---|
| 0. Metrology | Grok executable/version/digest, model, isolation flags and telemetry trust are recorded | Confirm provider telemetry and authentication before a paid run |
| 1. Ledger hardening | Balanced 16-arm schedule, immutable run IDs, HMAC assignment tokens, exact exposure evidence, invalid-run state, learning isolation and restricted MCP profile | Runtime and tamper tests must pass |
| 2. Synthetic identification | Repeated planted-effect generator, registered contrasts, confidence intervals, null and confounding gates | `aetnamem impact run --stage synthetic` must exit successfully |
| 3. Trusted controller | Per-run SQLite/workspace clones, hidden verifier, signed receipt, manifest-bound `host_attested` outcome and one-call paid edit smoke gate | Fake-agent end-to-end test, paid smoke, then independent receipt verification |
| 4. Grok factorial | Registered task schema, paid-run confirmation, train/validation scheduling and 16-arm reports | A corrected 100-run pilot yielded six complete blocks and exploratory signals; the full schedule and confirmatory evidence remain incomplete |
| 5. Held-out policy | Pessimistic within-budget selector, hash-frozen policy and held-out comparator report | Policy must freeze before any held-out receipt and win under the registered rule |
| 6. Replication | Protocol and evidence export are model-neutral | A second model, host or independent implementation must reproduce the scoped result |

The user-facing name is **Memory Impact**. “Causal Memory Ledger” remains the
technical name for the intervention evidence. Normal deployments remain
default-off and no adaptive production selection is enabled in 0.6.0.

The implementation guide is [`docs/memory-impact.md`](docs/memory-impact.md);
the reference artifact layout is
[`bench/causal_memory/`](bench/causal_memory/). A passing synthetic gate proves
estimator calibration, not that Grok benefits from memory. The repository must
continue to state external Grok, held-out and replication results as pending
until signed result artifacts exist.

A randomized 16-arm factorial experiment is established causal methodology, not marketing theatre. AetnaMem’s potentially unique contribution is the surrounding control plane: committing the intervention before execution, proving what context was actually exposed, connecting it to an independently verified outcome, and preserving an auditable evidence chain. Full factorial and randomized-block designs are well-established experimental methods. [NIST factorial design guidance](https://www.itl.nist.gov/div898/handbook/pri/section3/pri3.htm), [NIST randomized blocking guidance](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm).

I would proceed, but tighten several parts before spending money on Grok.

## What the experiment can prove

Separate the project into three claims:

1. **Measurement validity:** the ledger and estimator recover known effects in synthetic experiments.
2. **Agent effect:** randomized memory-plane exposure changes Grok’s verified results on registered task families.
3. **Product value:** a frozen selection policy improves unseen tasks under the same budget.

Passing the first does not prove memory helps Grok. Passing the second does not prove the learned policy generalizes. All three are required for the strongest product claim.

The defensible final statement would be:

> Under a registered protocol, AetnaMem measured the causal effect of offering four memory-plane bundles to Grok, and a frozen memory-selection policy improved verified outcomes on held-out tasks under a fixed budget.

Do not claim that AetnaMem identified the causal value of an individual memory or that the result applies universally to all agents.

## Five important corrections

### 1. Define the treatment precisely

The treatment is not an abstract “semantic memory” concept. It is:

> Offering a particular compiled semantic-memory contribution, with its content, length, position and policy, to the agent.

That distinction matters because prompt length and placement can themselves affect performance.

For a deeper follow-up, add token-matched sham context. That separates the effect of useful information from merely adding prompt material.

### 2. Use intention-to-treat as the primary analysis

Measure the effect of assigning a plane to the context, regardless of whether Grok appears to use it.

Trying to determine whether Grok “read” a memory introduces a post-treatment variable and weakens the causal interpretation. Usage can be reported as exploratory evidence, but assignment must remain primary.

For working memory, for example:

\[
Effect_W = average\bigl(success(1,S,E,P)-success(0,S,E,P)\bigr)
\]

averaged across all eight combinations of the other planes.

### 3. Make verified success the primary endpoint

“Successful tasks per dollar” is excellent for product evaluation, but ratios can behave badly statistically.

Use:

> Host-verified task success under an identical hard token, cost and time cap.

Then report:

- Total successes ÷ total actual cost
- Tokens and latency
- Tool failures and repeated failures
- Unsafe actions and false warnings
- Cost of each plane and arm

This also follows the broader recommendation that agent evaluations account for cost rather than comparing accuracy alone. [AI Agents That Matter](https://arxiv.org/abs/2407.01502).

### 4. Prove what Grok actually received

AetnaMem records the contribution and manifest, while the 0.6.0 compiler adds
exact post-budget exposure evidence in
[`compiler.py`](aetnamem/runtime/compiler.py).

For benchmark mode, either:

- Fail the run if the complete assigned context cannot fit, or
- Record exact exposed spans and their final digests.

Otherwise `1111` might say all four planes were assigned while part of one plane never reached Grok.

### 5. Separate Grok from the verifier completely

Grok must not:

- Access hidden expected results
- Write its own verified outcome
- Call an unrestricted recall endpoint to bypass withholding
- Access the signing credential
- Reuse native Grok memory, web search or another conversation

The normal MCP catalog exposes memory and outcome tools in
[`server.py`](aetnamem/mcp/server.py). The 0.6.0 `impact-restricted` profile
exposes none of them to the experimental agent.

## Recommended implementation

AetnaMem already has much of the experimental spine:

- Contributions are persisted before compilation in
  [`orchestrator.py`](aetnamem/runtime/orchestrator.py).
- Candidate hashes, arm identifiers, policy hashes, propensities and seed commitments exist.
- Off, shadow and benchmark modes already separate normal production from intervention.
- Outcomes can be bound to a context manifest.

Build the lab in this order.

### Phase 0: Metrology spike

Before a paid experiment, establish exactly what Grok CLI exposes:

- Binary digest and version
- Model identity
- Token and cost telemetry
- Exit status and retry behaviour
- Conversation isolation
- Tool permissions
- Web, native memory and subagent disabling

If cost or tokens are estimated rather than provider-verified, label them as estimates.

### Phase 1: Harden the ledger

Implement:

- A balanced, randomized-without-replacement 16-arm schedule
- Precommitted run IDs so a controller cannot retry IDs until it gets a preferred arm
- A protocol registry and immutable schedule digest
- Exact exposure receipts
- Restricted benchmark MCP gateway
- Signed host-verifier receipts
- Explicit aborted, missing and invalid-run states
- Learning disabled during experiments
- Deterministic experimental candidate identities

The independent Bernoulli allocator in
[`interventions.py`](aetnamem/runtime/interventions.py) remains for
backward-compatible shadow experiments. Balanced allocation is restricted to
registered benchmarks.

### Phase 2: Synthetic identification benchmark

Run repeated complete simulated experiments using the real ledger, manifests and analysis exporter—not a separate CSV-only simulation.

Include:

- Planted main effects
- Semantic × procedural interaction
- Task difficulty
- Heterogeneous effects
- Null and harmful effects
- Difficult tasks retrieving more memories
- Missing outcomes
- Failed runs and noncompliance

Run roughly 1,000–2,000 simulated experiments at the intended sample size. Pre-register gates such as:

- Mean absolute effect error below 2 percentage points
- Correct direction in at least 90% of experiments for effects of 10 points or more
- 95% interval coverage near 95%
- Null false-positive rate near 5%
- Zero manifest/outcome binding failures
- Better error than the deliberately confounded observational estimator

Do not require observational attribution to fail in every dataset. Instead, demonstrate defined conditions under which it becomes biased while randomized estimation remains calibrated.

### Phase 3: Trusted controller

Each experimental block should run as:

```text
Registered task
    → frozen database/workspace clone
    → precommitted arm assignment
    → AetnaMem context compilation
    → restricted Grok process
    → output/workspace/tool-receipt hashing
    → hidden deterministic verifier
    → signed outcome receipt
    → AetnaMem audit export
```

The signed receipt should bind:

- Experiment, block, task and run IDs
- Arm and assignment probability
- Memory snapshot and candidate digests
- Final exposed-context digest
- Grok binary and model identities
- Output and workspace digests
- Verifier source/version digest
- Success, tokens, cost, latency and exit status
- Safety events
- Timestamp and signature

A signature proves who issued the receipt—not that the verifier was correct. Preserve the artifacts so a second verifier can independently reproduce the result.

### Phase 4: Grok factorial study

For every task instance:

1. Produce all four candidate bundles before assignment.
2. Verify those candidates are identical across arms.
3. Create 16 isolated clones.
4. Run every arm from `0000` through `1111` exactly once, in randomized order.
5. Start a new Grok process and conversation for every run.
6. Reveal the randomization seed only after the experiment closes.

Use task families for:

- Working-only
- Semantic-only
- Episodic-only
- Procedural-only
- Two-plane interactions
- All-four coordination
- Null/no-memory-best
- Plausible but harmful memory
- Conflicting or stale memory
- Recovery from a previous failure

Use nonce facts, fake local APIs and hidden executable validators so Grok cannot solve tasks from public knowledge.

The verifier and its fixtures must remain outside Grok’s visible workspace. This resembles the executable, artifact-based evaluation approach used in benchmarks such as [CORE-Bench](https://arxiv.org/abs/2409.11363).

### Phase 5: Frozen held-out policy

Split by task-template family, not merely by individual run:

- Train: estimate effects and build the selector
- Validation: choose thresholds and budget rules
- Held-out: completely unseen templates and fresh snapshots

Freeze and hash the policy before opening held-out results. Compare it against:

- No supplemental memory
- Semantic-only
- All-four-always
- Relevance-based retrieval
- Outcome weighting without randomization

The policy may use only information available before execution. It should abstain to a fixed baseline when evidence is uncertain.

## How much data is needed?

Do not choose 480 runs merely because it sounds substantial.

As a rough illustration, distinguishing 60% from 70% success can require about 700 independent observations before accounting for task clustering and multiple effects. A realistic confirmatory experiment could therefore require:

- 30–60 distinct task instances
- 16 arms per instance
- 2–3 model repetitions

That is approximately 960–2,880 Grok calls. A simulation-based power analysis should select the final number. More distinct tasks are usually more valuable than many repeated calls on one task.

## What counts as proof?

Use a staged proof ladder:

1. **Integrity:** assignment always precedes execution; exposure, outcomes and schedules replay; tampering and bypass attempts are detected.
2. **Statistical validity:** planted effects, nulls and confidence intervals meet pre-registered calibration thresholds.
3. **Internal agent validity:** randomized Grok results show a registered effect under identical budgets.
4. **Held-out value:** the frozen selector’s lower confidence bound clears the success target—or success is non-inferior while cost is materially lower.
5. **Safety:** the upper confidence bound for harmful actions remains below the registered margin.
6. **Replication:** repeat on a second model, host environment or independent research implementation.

A null Grok result would still validate the ledger and measurement machinery if stages 1–2 pass. It would simply falsify the product claim that the tested memory policy improves those tasks. That willingness to fail is precisely what gives the project scientific credibility.

My recommendation is to name the product surface **Memory Impact**, retain **Causal Memory Ledger** as the technical mechanism, and keep adaptive production behaviour disabled until the complete held-out test succeeds.
