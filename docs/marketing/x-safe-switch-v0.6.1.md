# X article — try AetnaMem without a blind switch

I gave a real OpenClaw agent a memory upgrade—without asking users to trust a
blind switch.

The flow:

1. Install AetnaMem beside OpenClaw.
2. Add the `trial-agent-memory` skill.
3. Capture candidate memories without changing model context.
4. Approve the useful fact and reject the noisy one.
5. Preview the exact context before it reaches the model.
6. Run a one-turn canary.
7. Activate when the evidence looks good—or roll back.

In this reproducible DeepSeek/OpenClaw demonstration:

- Baseline: “I do not know yet.”
- AetnaMem canary: “Kyoto.”
- 12.9% fewer model tokens in this run.
- One approved and one rejected candidate.
- Exact 81-character context preview.
- Valid five-event transition chain.
- Rollback restored the host while preserving evidence.

This is not a claim that every workload improves by 12.9%. It is a safer
product promise:

Run AetnaMem beside the memory setup you already have. See what it captures.
Review what it would show. Test a limited canary. Switch only when your own
evidence says it helps.

Skills tell OpenClaw how to use governed memory. AetnaMem proves what was
captured, shown, changed, and restored.

<https://github.com/aetna000/aetnamem>
