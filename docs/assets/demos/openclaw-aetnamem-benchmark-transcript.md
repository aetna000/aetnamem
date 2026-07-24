# OpenClaw × AetnaMem side-by-side — narration transcript

## 1. Opening

OpenClaw can remember with a native memory file. AetnaMem adds a selective,
audited memory layer. The question is not whether both can remember. The
question is how much context they spend while staying correct.

## 2. Installation

On the left is native OpenClaw. On the right, AetnaMem remains one normal pip
install, plus the OpenClaw plugin and a ten-step setup wizard. No snapshot
package. No sudo. Existing memory tools remain compatible.

## 3. Four memory types

Agents use four kinds of memory. Working memory tracks the current task.
Semantic memory stores facts. Episodic memory carries useful past outcomes.
Procedural memory supplies the right skill. AetnaMem coordinates all four
behind one bounded connection.

## 4. Context behavior

Native memory can keep a durable file in every prompt. AetnaMem keeps durable
facts in memory dot D B and retrieves a small relevant block. The agent still
gets the fact it needs, while unrelated facts stay outside the context window.

## 5. Benchmark design

We tested a synthetic, pre-registered workload: ninety-four facts, nineteen
thousand four hundred eighty-nine characters of native memory, ten questions
run twice in fresh sessions, and DeepSeek V4 Flash with thinking disabled.

## 6. Prompt-token result

Native memory used five hundred ninety-six thousand five hundred eighty-one
prompt tokens. Cache-aware AetnaMem used five hundred seventeen thousand one
hundred eighteen. That is seventy-nine thousand four hundred sixty-three fewer
prompt tokens, a thirteen point three two percent reduction in this workload.

## 7. Correctness and cost

Both systems answered twenty out of twenty correctly. AetnaMem retrieved the
target on twenty out of twenty tasks. Provider-reported cost was two point
nine seven percent lower, and the AetnaMem audit chain verified.

## 8. Memory Impact

The next question is harder. Did a retrieved memory actually cause a better
outcome, or did it only consume context? AetnaMem now has a default-off
experimental Memory Impact ledger. It records what was eligible, what was
shown, and which outcome followed. The instrumentation is shipped. The causal
benefit is not yet claimed.

## 9. Close

Install the same public package with pip install AetnaMem. Connect OpenClaw,
choose a preset, and inspect the evidence. AetnaMem remembers whether
remembering actually helped. Read the protocol and source on GitHub dot com
slash aetna zero zero zero slash AetnaMem.
