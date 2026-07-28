# OpenClaw Safe Switch demo transcript

This is a real OpenClaw agent, running DeepSeek, with the AetnaMem trial skill
installed.

Install AetnaMem, then install the `trial-agent-memory` skill into your
OpenClaw agent. OpenClaw confirms that the skill is eligible and visible to
the model.

First, the baseline. We ask a fresh agent, “What city is assigned to my Atlas
demo?” It searches its normal workspace and answers, “I do not know yet.”

Now start a side-by-side trial. Capture mode observes candidate memories, but
changes no model context and makes no extra provider calls.

The candidate review is the safety gate. We rejected a noisy capture and
approved only the clean fact: “The Atlas demo city is Kyoto.”

Preview shows the exact 81 characters AetnaMem would add, plus a manifest
hash. Preview still sends nothing to the model.

Next, a one-turn canary. We ask the same question in a fresh OpenClaw session.
This time, the approved context is shown, and DeepSeek answers: “Kyoto.”

In this single demo run, the correct answer used 12.9% fewer model tokens. That
is evidence for this task, not a promise for every workload.

The trial is now ready. Activate to use AetnaMem normally, or roll back. We
tested both: activation succeeded, rollback restored the OpenClaw host, and the
five-event evidence chain still verifies.

Skills tell OpenClaw how to use governed memory. AetnaMem proves what was
captured, shown, changed, and restored. Try it without risking your current
setup.

## Evidence boundary

The isolated run used OpenClaw `2026.7.1-2`, DeepSeek
`deepseek-v4-flash`, AetnaMem `0.6.1`, and OpenClaw plugin `0.4.0`.
The baseline used 19,450 model tokens and the canary used 16,940. This is a
single demonstration task, not a representative benchmark or causal estimate.
