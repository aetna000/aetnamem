# Memory Impact Lab

> **AetnaMem remembers whether remembering actually helped.**

AetnaMem 0.6.0 can run a registered experiment over all 16 combinations of
working, semantic, episodic and procedural memory. The experiment is
default-off and cannot alter an ordinary `starter`, `private` or `team`
deployment.

## The five gates

```bash
aetnamem impact init ./memory-impact-lab
cd ./memory-impact-lab

aetnamem impact run --protocol protocol.yaml --stage synthetic
aetnamem impact run --protocol protocol.yaml --stage grok-smoke \
  --confirm-paid-run
aetnamem impact run --protocol protocol.yaml --stage grok-train \
  --confirm-paid-run
aetnamem impact run --protocol protocol.yaml --stage grok-held-out \
  --confirm-paid-run
aetnamem impact verify results/ --public-key host-public-key.pem
aetnamem impact report results/ --public-key host-public-key.pem \
  --output reports/memory-impact.html
```

After the experiment is closed, place the revealed randomization seed in a
host-controlled text file and add `--seed-file PATH` to `impact verify`. This
recomputes every assignment token as well as the public schedule digest.
Without the reveal, signatures, artifacts, arm balance and the committed
schedule remain verifiable, while HMAC token verification is reported as
`null` rather than silently assumed.

`impact init` creates three task splits with frozen SQLite snapshots, isolated
workspaces, hidden executable verifiers, a JSON-compatible YAML
protocol and a local Ed25519 key pair. The generated starter suite contains 24
tasks across working-only, semantic-only, episodic-only, procedural-only,
semantic×procedural, all-four, null-memory and harmful-memory families. The
private key is mode `0600`, ignored by Git, never copied into a run workspace
and must remain host-controlled.

The starter tasks prove plumbing and exercise all required task shapes. Eight
held-out blocks are deliberately insufficient for `claim_ready`; a
confirmatory protocol must add enough independently authored task templates to
meet its simulation-based power calculation. `claim_ready` additionally
requires at least 20 paired held-out blocks, zero selected-policy unsafe
actions, and a positive lower 95% bound against every registered baseline.

The synthetic stage spends no model tokens. It repeatedly plants known
working, semantic, episodic, procedural and semantic×procedural effects. It
fails unless registered error, direction, interval coverage, null false
positive and confounding-comparison gates pass. It also reports empirical
detection power at the configured number of blocks; use that result to enlarge
the confirmatory protocol before registration rather than choosing a run count
after seeing Grok outcomes.

All three Grok stages require `--confirm-paid-run`. The one-call smoke stage
must prove that the registered CLI invocation can edit its isolated workspace
before training is allowed to spend a full block. Training and validation then
run first. Before a held-out outcome exists, AetnaMem selects a pessimistic
within-budget arm and writes a hash-frozen policy. Only then can the held-out
stage start.

For a deliberately capped pilot, add `--max-new-runs N`. The runner stops only
after complete signed receipts and can later resume the unchanged schedule.
Such a partial run will correctly fail complete-study verification and cannot
support a held-out or causal claim.

The headless Grok invocation uses `bypassPermissions` because Grok's CLI does
not activate `acceptEdits` from that flag. This does not give the experiment a
general shell: the registered tool allowlist is limited to `read_file`, `grep`,
`list_dir` and `search_replace`, and the process remains inside Grok's
`strict` filesystem sandbox.

## Integrity model

For each task and repetition, the allocator produces a random permutation of
`0000` through `1111`. The schedule commits:

- experiment, block, task and immutable run IDs;
- arm and its `1/16` block probability;
- schedule and seed commitments;
- an HMAC assignment token bound to the run ID;
- protocol, model, policy, candidate and context digests.

Each run receives a fresh SQLite backup and workspace clone. All four candidate
contributions must exist before assignment. The registered benchmark uses
content-envelope candidate identities so random row IDs cannot make equivalent
clones appear different. If an assigned contribution is missing or the final
compiler truncates it, the run becomes `invalid` and Grok is not started.

The prompt is compiled by the host. In an experiment, Grok receives no AetnaMem
MCP memory or outcome tools. After Grok exits, a verifier outside the agent
workspace examines files, stdout and exit status. Its signed receipt binds the
assignment, final context, output, workspace, verifier digest and metrics.
Generic CLI/MCP outcomes remain `caller_asserted`; they cannot label themselves
`host_attested`.

## Statistical meaning

The primary estimand is intention-to-treat: the effect of **offering** a
registered memory-plane contribution. It includes content, length, placement
and policy. Whether the model appeared to read the contribution is exploratory
and does not redefine treatment.

Reports include:

- absolute success for every arm;
- average ITT risk difference for each plane;
- pairwise difference-in-differences;
- 95% intervals over complete task blocks;
- successes per total dollar, tokens and latency;
- missing, extra, unbalanced, unsigned or digest-mismatched runs.

In the registered balanced design every arm has probability `1/16` and every
plane has marginal probability `1/2`. Horvitz–Thompson propensity weights are
therefore constant, so the complete-block factorial contrast is the
propensity-aware estimator rather than a separate weighted implementation.
The report does not silently apply that estimator to arbitrary Bernoulli or
observational data.

Success under a common hard budget is primary. Successes divided by total
actual cost is secondary. Cost or token figures remain explicitly
`unavailable` or `estimated` until the host verifier supplies trusted provider
telemetry.

The controller hard-enforces AetnaMem context characters, maximum Grok turns
and wall time. The frozen policy compares host-verified compiled context
characters with that context budget; it does not confuse Grok's provider total
tokens (which can include system prompts and cache reads) with memory context.
Grok CLI does not currently expose a controller-enforced dollar cutoff, so
`max_cost_usd` is checked against provider-reported telemetry after the run; an
over-budget run is an ITT failure. If cost telemetry is unavailable, the
receipt records `cost_budget_compliant: null` and the report must not claim a
verified dollar result.

## Claims boundary

The shipped synthetic gate can validate identification. It cannot prove Grok
benefits from memory. A Grok result applies only to the registered model,
plane bundles, task families and population. It does not establish that an
individual memory caused an outcome.

A deployment claim requires:

1. successful integrity verification;
2. passing synthetic calibration;
3. a pre-registered randomized Grok trial;
4. a policy frozen before held-out execution;
5. held-out benefit under the same budget and safety margin;
6. replication with another model, host or independent implementation.

For replication, copy the closed protocol, set a new `experiment_id`, set
`replication_of` to the original protocol digest, change only the registered
model/host field being replicated, and generate a new seed and signing key.
The second study remains a separate schedule and result directory.

The reference layout and compatibility scripts are in
[`bench/causal_memory/`](../bench/causal_memory/).
