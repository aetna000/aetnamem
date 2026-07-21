# Technical evaluation protocol: selective memory in OpenClaw

## Scope and research questions

This document records the protocol and evidence needed to turn the OpenClaw
integration benchmark into a paper-quality evaluation. The current experiment
asks three narrow questions:

1. Does moving a mature durable-memory file behind bounded retrieval reduce
   the complete prompt seen by the model?
2. Does the reduction preserve factual task success and retrieve the intended
   evidence?
3. Do fewer prompt tokens translate into lower provider cost or latency when
   provider caching and integration overhead are included?

It does not test clinical outcomes, multi-user isolation, automatic fact
capture, long-conversation compaction, procedural skill selection, or every
model/provider. The workload is synthetic and must not be described as a
hospital pilot.

## Pre-registered design

The definitive run used commit
`0a4d1352f3812f8d55a9a8e99903ee8d10796465`; the runner also stored its own
SHA-256 digest in the result. The task file contains 10 questions and answer
fragments fixed before the definitive run. Each task ran twice in each arm,
giving 20 paired observations and 40 model calls. No trial was excluded.

The workload contains 10 target facts and 84 operational distractors. The
control arm places all 94 facts in a 19,489-character `MEMORY.md`. The treatment
stores the identical facts in AetnaMem, keeps a 163-character bootstrap
`MEMORY.md`, and enables the production plugin defaults: a 600-character
persona budget, at most three recalled records, and a 1,200-character recall
budget. Automatic capture is disabled so answers cannot contaminate later
trials. The AetnaMem tool schemas remain enabled and therefore count against
the treatment.

Both arms use OpenClaw 2026.7.1-2, the official DeepSeek provider 2026.7.1,
`deepseek/deepseek-v4-flash`, and thinking disabled. Every observation starts a
fresh OpenClaw session. Pair order alternates by case and repetition to reduce
simple order bias. Profile installation and seeding are outside trial latency;
each timed trial includes the one-shot local OpenClaw process, plugin startup,
provider request, persisted response, and clean shutdown.

The exact cases, runner, and reproduction instructions are in
[`bench/openclaw_memory`](../bench/openclaw_memory/). The API credential is
read only from `DEEPSEEK_API_KEY` and is never included in an artifact.

## Outcomes and estimands

DeepSeek/OpenClaw separates uncached input and cache-read tokens. We therefore
define prompt tokens for trial *i* as:

```text
P_i = uncached_input_i + cache_read_i
```

The primary paired estimand is `P_native - P_aetnamem`; positive values favor
AetnaMem. Reporting only uncached input would incorrectly call a cache hit
removed context. Secondary outcomes are exact-fragment task success,
target-record retrieval, provider-reported cost, cache mix, and complete local
wall latency.

The scorer normalizes case, whitespace, and `%`/`percent`, then requires every
pre-registered fragment. It does not use another language model. Retrieval
success requires the record ID returned by AetnaMem to map to the target label
registered during seeding. The runner verifies the AetnaMem hash chain after
all trials.

Means, medians, totals, and paired differences are retained. The reported 95%
interval is a deterministic 10,000-resample paired bootstrap interval. Because
the two repetitions of a case are not independent and the task set is small,
this interval describes stability within this workload; it is not a population
confidence claim. Accuracy is reported descriptively rather than as proof of
equivalence.

## Definitive result

Run completion: 2026-07-20 16:31:41 UTC.

| Outcome | Native `MEMORY.md` | AetnaMem | Paired/result |
|---|---:|---:|---:|
| prompt tokens, total | 596,296 | 520,837 | **75,459 fewer (12.655%)** |
| prompt tokens, median/trial | 29,808 | 26,028 | **3,801 paired median fewer** |
| paired mean prompt-token saving | — | — | 3,772.95; bootstrap interval [3,749.6, 3,796.8] |
| uncached input tokens | 352,072 | 374,405 | AetnaMem +22,333 |
| cache-read tokens | 244,224 | 146,432 | native cache fraction 41.0%; AetnaMem 28.1% |
| correct answers | 20/20 | 20/20 | no observed loss |
| target record retrieved | not applicable | 20/20 | all treatment trials |
| provider-reported cost | $0.056273 | $0.056652 | **AetnaMem +0.674%** |
| median wall latency | 12.421 s | 12.215 s | descriptive |
| paired mean latency difference | — | — | native − AetnaMem 0.578 s; bootstrap interval [0.224, 0.989] |

The post-run AetnaMem evidence contained 94 seeded records, 20 retrieval events,
and 248 audit events; its hash chain verified. The complete per-trial answers,
token fields, costs, latencies, retrieved IDs/labels, software metadata, input
hashes, and session-log hashes are in
[`deepseek-v4-flash-2026-07-20.json`](../bench/openclaw_memory/results/deepseek-v4-flash-2026-07-20.json).

## Interpretation

The primary result supports the narrow claim that selective AetnaMem recall
reduced complete prompt context by 12.655% for this mature-memory workload
without an observed task-success loss. It does not support the stronger claim
that AetnaMem always reduces the bill. DeepSeek served the repeated native file
from its inexpensive cache more often; the treatment sent fewer total prompt
tokens but more uncached tokens, producing a 0.674% higher measured cost.

This distinction is operationally important. Prompt caching lowers the price
of repeated context, while selective memory removes irrelevant context. They
can be complementary, but pricing, prefix stability, cache lifetime, and
retrieval variability determine the economic result.

## Cache-aware follow-up

On 2026-07-21 UTC, commit
`efc1b0bed127859171cf5a93f290847a015fdfe5` ran a pre-registered three-arm
follow-up: native `MEMORY.md`, the pre-0.2.4 AetnaMem layout, and the 0.2.4
cache-aware candidate. The candidate placed its stable persona through
OpenClaw `appendSystemContext`, placed query-specific recall through
`appendContext`, used compact model-visible references while auditing full
IDs, and omitted optional explicit search/forget schemas. The other task,
model, memory, scoring, and fresh-session controls remained the same. A
rotating three-arm order replaced the two-arm counterbalance.

| Outcome | Native | Current AetnaMem | Cache-aware AetnaMem |
|---|---:|---:|---:|
| prompt tokens | 596,581 | 521,858 | **517,118** |
| median prompt tokens / task | 29,829 | 26,076.5 | **25,844.5** |
| uncached input tokens | 353,381 | 363,138 | **358,398** |
| cache-read tokens | 243,200 | 158,720 | **158,720** |
| cache-hit fraction | 40.8% | 30.4% | 30.7% |
| provider cost | $0.056427 | $0.055411 | **$0.054752** |
| correct answers | 20/20 | 20/20 | 20/20 |
| target retrieved | not applicable | 20/20 | 20/20 |

Relative to native memory, the cache-aware arm saved 79,463 prompt tokens
(13.320%) and cost 2.968% less. Relative to current AetnaMem, it saved 4,740
prompt tokens (0.908%) and cost 1.190% less. The paired mean cache-aware saving
over native was 3,973.15 tokens per task; its deterministic paired bootstrap
interval was [3,958.5, 3,987.25]. No trial was excluded. Both AetnaMem evidence
chains verified with 94 seeded records, 22 retrieval events, and 252 audit
events each. Raw evidence is in
[`deepseek-v4-flash-cache-aware-2026-07-21.json`](../bench/openclaw_memory/results/deepseek-v4-flash-cache-aware-2026-07-21.json).

The prompt-placement hypothesis was **not supported as an additional cache-hit
mechanism** in this run: current and cache-aware AetnaMem both received exactly
158,720 cache-read tokens. The cache-aware hit fraction is slightly larger only
because its denominator is smaller. Two immediate-repeat probes likewise gave
both AetnaMem layouts 2,176 cached tokens on the repeat. The optimized bundle
still improved context and cost by removing uncached model-visible overhead,
but this design cannot attribute that 0.908% improvement separately to compact
references, tool omission, or placement.

The earlier run's +0.674% cost result and this run's −2.968% result are not a
discrepancy: DeepSeek cache state is best-effort and differed across runs. They
jointly demonstrate that selective memory reliably reduced prompt size in this
workload, while dollar savings depended on the observed hit/miss mix. A
stronger causal study should add one arm per optimization and use a provider or
test fixture with controllable cache state.

## Threats to validity

- **External validity:** one synthetic English workload, one memory size, one
  model, one host release, and 20 pairs cannot represent all agents or users.
- **Construct validity:** fragment containment measures factual recall, not
  answer usefulness, reasoning quality, safety, or clinical correctness.
- **Caching:** provider cache state is not fully controllable. Alternating pair
  order reduces simple bias but does not make cache observations independent.
- **Repeated tasks:** the second repetition may receive provider-side cache
  benefit. Both arms repeat equally, but case-level clustering limits
  inferential claims.
- **Sampling:** provider default sampling settings were used apart from
  disabling thinking. Model output is therefore not guaranteed deterministic.
- **Latency:** local process startup, network variation, and provider queueing
  are included. The run was on one macOS host and was not an isolated systems
  performance experiment.
- **Evidence retention:** machine-readable trial evidence and session hashes
  are committed, but full OpenClaw system prompts and temporary runtime
  profiles are not. A replication intended for forensic review should use
  `--keep-runtime`, archive the synthetic session logs and database securely,
  and publish a manifest without credentials or local paths.
- **Treatment scope:** capture was intentionally disabled. A separate study is
  required for extraction accuracy, corrections, forgetting, and memory drift.

## Minimum extension before a paper-level general claim

Run the same pre-registered protocol across multiple model families and at
several memory sizes; add unrelated-query negative controls, paraphrased
queries, conflicting/stale facts, multi-turn tasks, and automatic-capture
trials. Use at least three independent run days, cluster inference by task,
publish all failures, retain raw sanitized session evidence, and obtain an
external methods review. For hospital-facing claims, add an approved real-user
pilot under the relevant privacy, safety, and governance processes; do not
substitute this synthetic benchmark for that approval.
