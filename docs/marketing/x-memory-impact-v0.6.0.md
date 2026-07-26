# X article — AetnaMem 0.6.0 Memory Impact

## AetnaMem gave Grok four ways to remember—and measured what changed

AI memory is usually evaluated by asking whether retrieval looks relevant.
That is not the same as asking whether the memory helped the agent succeed.

With AetnaMem 0.6.0, we tested the harder question.

We gave Grok benchmark tasks with different combinations of four memory types:

- **Working memory:** the current goal, state and unfinished work.
- **Semantic memory:** durable facts and preferences.
- **Episodic memory:** relevant past attempts and reviewed lessons.
- **Procedural memory:** the skill or procedure for doing the task.

Every complete task block tested all 16 possible combinations. Grok did not
grade itself. A separate host verifier checked the resulting file, and
AetnaMem preserved a signed receipt binding the assigned memory, compiled
context and verified outcome.

### What happened

In the corrected, deliberately capped 100-run pilot:

- Grok completed **57 of 100** calls successfully.
- The **no-memory** arm completed **1 of 6** balanced tasks.
- The **all-four-memory** arm completed **6 of 6**.
- Procedural memory showed the clearest exploratory improvement.
- All 100 outcome receipts passed signature and artifact verification.

The result is promising, but it is not a universal performance claim. Only six
balanced task blocks were completed, the registered schedule was intentionally
capped, and we did not run the frozen-policy held-out phase. The honest
conclusion is:

> AetnaMem can control which memory Grok receives, measure how the choice
> changes verified task outcomes, and preserve the evidence. This pilot
> supports a larger held-out study.

The public
[evidence summary](../../bench/causal_memory/reports/grok-4.5-100-run-pilot-2026-07-26.md)
records the protocol, schedule, model, executable, verifier and report hashes.

### Give your Grok the same four-memory foundation

Install AetnaMem:

```bash
python3 -m pip install --upgrade aetnamem
```

Create a local configuration for Grok:

```bash
aetnamem setup --yes --preset starter --subject you \
  --agent grok-primary --skill-path ~/.grok/skills
```

Connect it to Grok CLI through MCP:

```bash
grok mcp add --scope user aetnamem -- \
  aetnamem runtime mcp --config ~/.aetnamem/runtime.json
grok mcp doctor
```

The `starter` preset gives Grok bounded access to current state, governed
facts, prior outcomes and versioned skills through one AetnaMem runtime.
Experimental withholding remains off.

For a smaller context use `private`. For a trusted multi-agent deployment use
`team`. To test whether memory improves your own workload, use the registered
Memory Impact workflow instead of assuming that more context is always better.

Install: `pip install aetnamem`

Repository and complete evidence boundary:
https://github.com/aetna000/aetnamem

**AetnaMem remembers whether remembering actually helped.**
