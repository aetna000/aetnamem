The closest honest pitch for AetnaMem 6.0 is:

> Give OpenClaw memory without trusting it blindly.

1. Install AetnaMem and the OpenClaw plugin.

   ```bash
   pip install aetnamem
   openclaw plugins install npm:openclaw-memory-aetnamem@latest --pin
   ```

2. Keep your current model provider and existing `MEMORY.md`. AetnaMem does not require you to switch models or immediately remove your current memory.

3. Start AetnaMem in capture-only mode. It observes new trusted user facts and builds a private local memory database, but does not inject that memory into OpenClaw’s answers yet.

4. Review what it collected. Search in ordinary language, inspect where memories came from, and export an audit report:

   ```bash
   aetnamem list ~/.aetnamem/memories.db you

   aetnamem trace ~/.aetnamem/memories.db \
     "travel preferences" --subject you \
     --output travel-memory-report.html
   ```

5. When the captured memory looks correct, enable bounded recall. AetnaMem starts giving OpenClaw only a small set of relevant memories instead of loading every durable fact into every prompt. Your existing `MEMORY.md` can remain in place during this trial.

6. Run representative tasks both ways. AetnaMem records what memory was available, what was actually shown, and what happened afterward. For a controlled study, Memory Impact can compare memory combinations using an external verifier rather than letting the agent grade itself.

7. Once results look healthy, remove only the duplicated durable facts from the always-loaded `MEMORY.md`. Keep essential identity, safety, and operating instructions pinned.

8. Continue auditing:

   ```bash
   aetnamem verify ~/.aetnamem/memories.db
   ```

   If a memory should be removed, AetnaMem produces a deletion receipt and checks its local records and derived indexes.

> Congratulations. Your OpenClaw now has bounded, searchable and auditable memory—without changing its model provider or making an irreversible migration.

What this safely promises

- Your current provider does not change.
- `MEMORY.md` is not automatically overwritten.
- Memory is stored locally.
- You can inspect memories before relying on them.
- You can search without knowing an internal ID.
- You can trace memory admission and recall.
- You can logically delete memory with a verifiable receipt.
- You can enable recall gradually.

What it must not promise yet

We cannot currently say:

> “Run it for 24 hours and AetnaMem automatically tells you it is safe to switch.”

Version 6.0 contains the experimental machinery for controlled comparisons, but it does not yet turn arbitrary live OpenClaw traffic into automatic evaluations or send a production-readiness notification. Capture-only mode is supported through plugin settings, but it is not yet presented as one polished onboarding switch.

The stronger product to build

The excellent equivalent of the Inference Gateway pitch would be:

1. Run `aetnamem openclaw trial`.
2. Keep your provider, `MEMORY.md`, and production behaviour unchanged.
3. AetnaMem captures candidate memory in shadow mode without injecting it.
4. It creates verified replay tasks from approved interactions.
5. It runs isolated comparisons: native memory versus bounded AetnaMem memory.
6. It reports answer success, prompt tokens, cost, latency and unsafe regressions.
7. You receive: “AetnaMem recall is safe to enable,” or an honest explanation of why it is not.
8. Run `aetnamem openclaw enable`.

That is the missing product layer connecting the strongest pieces already in 6.0: governed memory, audit tracing, shadow interventions, host verification and Memory Impact.

The headline should therefore be:

> **Try better OpenClaw memory without risking your current setup. AetnaMem watches first, proves what it remembers, and only takes over when you decide.**

That is much more sellable than leading with “four memory planes” or “Causal Memory Ledger.” Those are mechanisms. The product promise is a safe, inspectable memory migration.


---

Yes—this is the first genuinely coherent product direction. I would call it **AetnaMem Safe Switch** and interpret “6.1” as repository version **v0.6.1**.

> Implementation update, 2026-07-28: phases 1–2 are implemented and tested;
> the OpenClaw/Hermes adapters, secured dashboard API, canary and rollback
> foundations are implemented in beta. Claude's visual dashboard, paid paired
> replay, final-input exposure proof, config-drift/health gates, post-switch
> value reporting and real-host clean-install tests remain release blockers.
> See [Safe Switch](docs/safe-switch.md) and
> [current status](docs/current-status.md) for shipped truth.

The release promise should be:

> Run AetnaMem beside your current OpenClaw or Hermes memory. See what it would remember and recall, test both configurations safely, then enable AetnaMem only when the evidence supports it—with one-command rollback.

## The user experience

These are proposed new commands:

```bash
pip install --upgrade aetnamem
aetnamem trial start --host auto --subject you
```

That single command would:

1. Detect OpenClaw or Hermes.
2. Record the host, model, current memory and configuration digests.
3. Save a rollback snapshot.
4. Install AetnaMem in capture-only mode.
5. Open `http://127.0.0.1:8766`.
6. Leave the current provider, model and native memory in control.

The dashboard initially says:

```text
OBSERVING — NOT INFLUENCING YOUR AGENT

AetnaMem is collecting quarantined memory candidates locally.
It is not injecting context, exposing memory tools, or making extra model calls.
Your current memory and provider remain in control.
```

The user journey then becomes:

1. **Observe** new memory candidates without changing answers.
2. **Explore** captured memories, provenance, conflicts and quarantine status.
3. **Preview** exactly what AetnaMem would have recalled for previous turns.
4. **Approve** the memories allowed into the evaluation.
5. **Compare** the current configuration against AetnaMem using isolated, paid replays.
6. Receive a quantitative readiness report.
7. Click **Start limited canary** or run:

   ```bash
   aetnamem trial enable --canary-turns 20
   ```

8. If the canary remains healthy, click **Make AetnaMem active**.
9. Roll back at any time:

   ```bash
   aetnamem trial rollback
   ```

## Modes must have exact meanings

| Mode | Stores trial data | Changes agent prompt | Makes extra model calls |
|---|---:|---:|---:|
| Off | No | No | No |
| Capture | Yes | No | No |
| Preview | Yes | No | No |
| Isolated comparison | Yes | No live effect | Yes, with approval |
| Canary | Yes | Selected fresh sessions | No |
| Active | Yes | Yes, bounded context | No |

We should use **preview**, not “shadow,” in this product. Memory Impact already uses “shadow” for an experimental concept with different semantics.

Capture also needs a new path. The current OpenClaw capture route can preserve complete user utterances and activate extracted user facts. The trial must instead:

- Use a separate trial database.
- Save minimized candidate evidence by default.
- Keep every candidate inactive until review.
- Exclude group chats, unauthenticated users, tool output and web content by default.
- Never let the agent promote trial candidates.

## How AetnaMem proves value

Passive observation can prove that capture and retrieval work. It cannot prove that an answer would have been better.

The defensible comparison is:

1. The user approves replayable tasks.
2. AetnaMem freezes the current model, tools, memory snapshots and budgets.
3. Each task runs in two isolated copies:

   - Current/native memory
   - Frozen AetnaMem configuration

4. Arm order is randomized.
5. External actions are disabled or sandboxed.
6. A host verifier or blinded user—not the agent—grades the result.
7. Existing Memory Impact code signs and verifies the receipts.

Version 6.0 already has most of this experimental infrastructure in [controller.py](aetnamem/impact/controller.py).

### The readiness card

```text
READY FOR LIMITED CANARY

Host: OpenClaw 2026.x
Model/config: 8f2…91c
Matched held-out tasks: 42

                         Current     AetnaMem
Verified success          35/42       37/42
Complete prompt tokens    112,480      91,940   −18.3%
Provider cost               $0.54       $0.49   −9.3%
Median latency               6.2s        6.0s

Target memories retrieved              18/19
Irrelevant recalls                      1/18
Known stale memories shown                 0
Critical unsafe actions                    0
Audit chain                         VERIFIED
Deletion drill                      VERIFIED
Rollback                            TESTED

Conclusion:
AetnaMem was non-inferior on verified success and used less
complete prompt context for this model, memory snapshot and task sample.
```

Every metric should carry one of three labels:

- **Verified:** provider telemetry or host-verifier evidence.
- **Estimated:** tokenizer or price-based projection.
- **Observed:** descriptive before/after data, not causal proof.

Possible conclusions:

- **Not ready**
- **More evidence needed**
- **Compatible; financial value unproven**
- **Ready for limited canary**
- **Ready to migrate duplicated native facts**

A reasonable default gate is:

- Zero critical unsafe actions.
- Zero unreviewed or known-stale memories recalled.
- Audit and deletion drill pass.
- Rollback test passes.
- At least 30 matched cases, including memory-dependent and negative-control tasks.
- One-sided 95% lower bound for AetnaMem success minus current success above −5 percentage points.
- At least 90% target-memory retrieval.
- No more than 5% irrelevant recall on negative controls.
- Either verified token/cost reduction or verified quality improvement within a registered cost tolerance.

Twenty-four hours can be a collection milestone, but it cannot by itself prove readiness.

## Dashboard

The local dashboard should have six focused sections:

1. **Overview**

   Host, model, current mode, captured turns, data location and readiness state.

2. **Memory**

   Active, candidate, quarantined, conflicting, superseded and forgotten memories with provenance.

3. **Recall Preview**

   For each observed query: memories AetnaMem would have selected, ranking reason, context size and manifest digest. It must clearly say “not shown to the agent.”

4. **Comparison**

   Baseline versus AetnaMem success, complete prompt tokens, cache reads, cost, latency, retrieval accuracy and safety.

5. **Switch**

   Exact configuration diff, snapshot digest, backup location, canary controls, activation and rollback.

6. **Value**

   After activation: actual exposed memories, context supplied, verified evaluation advantage, live token/cost trends, corrections, quarantines, deletion receipts and audit health.

## Implementation architecture

Add a host-neutral trial package:

```text
aetnamem/trial/
├── models.py
├── store.py
├── manager.py
├── state.py
├── capture.py
├── preview.py
├── replay.py
├── readiness.py
├── report.py
└── hosts/
    ├── base.py
    ├── openclaw.py
    └── hermes.py
```

Use:

```text
~/.aetnamem/trials/<trial-id>/
├── state.json
├── trial.db
├── registration.json
├── rollback.json
├── approved-memory.json
├── replays/
└── report.html
```

This avoids changing the primary memory schema and keeps trial removal reversible.

### OpenClaw

Extend the existing plugin in [index.ts](integrations/openclaw/index.ts):

- One fail-closed mode gate covering recall, persona, orchestration and tools.
- Capture/preview modes return no prompt content.
- Use current OpenClaw observation hooks for model input, output, usage and run correlation. OpenClaw now exposes `llm_input`, `llm_output`, provider usage and run IDs through its plugin hooks. [OpenClaw hooks](https://docs.openclaw.ai/plugins/hooks)
- Verify actual AetnaMem exposure against the final model input.
- Preserve existing behaviour for upgraded configurations; only new trial installs default to capture mode.
- Replace the current sequential setup writes in [setup.ts](integrations/openclaw/src/setup.ts) with snapshot, validation, atomic application, health check and rollback.

### Hermes

Today the repository has only MCP-based Hermes integration. Version 6.1 needs a real general Hermes plugin:

```text
integrations/hermes/
├── plugin.yaml
├── __init__.py
├── README.md
└── tests/
```

Hermes supports `pre_llm_call` context injection and `post_llm_call` observation. A general plugin can coexist with built-in memory and an existing external provider, whereas a memory-provider plugin would occupy Hermes’s single external-provider slot. [Hermes plugin hooks](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/plugins.md), [Hermes memory providers](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory-providers.md)

In capture and preview modes, the Hermes pre-LLM hook returns nothing. In active mode, it returns the bounded AetnaMem context and fails open on timeout.

## Switching and rollback

Activation is a privileged operation and must:

1. Start on a fresh session.
2. Display the exact change.
3. Require reviewer confirmation.
4. Compare the current configuration digest with the snapshotted digest.
5. Apply only typed AetnaMem-owned settings.
6. Restart or reload the host.
7. Confirm the effective configuration.
8. Run a health probe.
9. Return immediately to `off` if verification fails.

The emergency `off` state should work through the state file even if a host restart fails. Full rollback then restores the validated configuration snapshot.

AetnaMem must not automatically erase `MEMORY.md` or `USER.md`. After a successful canary, the dashboard can identify duplicated durable facts and offer a separately reviewed migration patch. Identity, safety and authorization instructions remain pinned in the host.

## Implementation phases

| Phase | Deliverable | Gate before continuing |
|---|---|---|
| 1 | Mode contract, state machine, separate trial store | Missing/corrupt state always fails to off |
| 2 | Candidate-only capture and recall preview | No trial candidate can enter live recall |
| 3 | OpenClaw adapter | Capture/preview leave final prompt and tool schemas unchanged |
| 4 | Hermes adapter | Same non-interference test passes |
| 5 | Read-only dashboard | Memory, previews and audit evidence are correct |
| 6 | Matched two-arm replay using Memory Impact | Signed receipts reproduce every headline number |
| 7 | Readiness engine | Failed or inconclusive gates never recommend activation |
| 8 | Canary, activation and CLI rollback | Restart failure, config drift and disk/DB failures recover safely |
| 9 | Post-switch value dashboard | Verified, estimated and observed numbers never mix |
| 10 | Security, compatibility and release QA | Both claimed hosts pass end-to-end clean-install and rollback tests |

Before the dashboard can control host configuration, it also needs Host/Origin checks, CSP, CSRF protection, no-store headers, stored-XSS tests and stronger reviewer-session handling than the current localStorage tokens in [ui.py](aetnamem/service/ui.py).

## Release boundaries

Version 6.1 should remain:

- Local and single-user.
- Python package `aetnamem==0.6.1`.
- Normal installation remains `pip install aetnamem`.
- OpenClaw plugin becomes a feature release, likely `0.4.0`.
- Generic Python, CLI and MCP contracts remain compatible.
- No automatic live traffic duplication.
- No side-effecting replay.
- No automatic activation.
- No automatic deletion of native memory.
- No claim that all provider data remains local.

If the Hermes native adapter cannot pass the same end-to-end non-interference and rollback tests, the 6.1 release must say “OpenClaw Safe Switch; Hermes diagnostic preview,” rather than claiming false parity.

This plan is now being implemented incrementally. A checked item is not a
product-performance claim; the current-status document and tests define the
release boundary.
