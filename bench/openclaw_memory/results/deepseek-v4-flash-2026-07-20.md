# OpenClaw × AetnaMem DeepSeek benchmark

Run completed: `2026-07-20T16:31:41.580577+00:00`  
Git commit: `0a4d1352f3812f8d55a9a8e99903ee8d10796465`  
Model: `deepseek/deepseek-v4-flash` with thinking off  
OpenClaw: `2026.7.1-2`  
Trials: 20 paired fresh-session tasks (10 cases × 2 repetitions)

## Result

| Metric | Native `MEMORY.md` | AetnaMem | Change |
|---|---:|---:|---:|
| Prompt tokens, total | 596,296 | 520,837 | **-75,459 (12.655%)** |
| Prompt tokens, median/trial | 29,808.0 | 26,028.0 | 3,801.0 paired median saved |
| Uncached input tokens, total | 352,072 | 374,405 | +22,333 |
| Cache-read tokens, total | 244,224 | 146,432 | — |
| Correct answers | 20/20 | 20/20 | — |
| Provider-reported cost | $0.056273 | $0.056652 | **+0.674%** |
| Median wall latency | 12.421s | 12.215s | — |

The paired mean prompt-token saving was 3,772.9 tokens per turn; the deterministic
10,000-resample paired bootstrap 95% interval was [3,749.6,
3,796.8] tokens. Every treatment trial produced an audited
retrieval event with at least one returned record: `true`.
Every treatment trial retrieved its pre-registered target record: `true`.
The AetnaMem evidence chain verified after the run: `true`
(248 audit events, 20 retrieval events, 94 seeded records).

## Method

The control arm stored the complete 19,489-character synthetic hospital programme memory in
OpenClaw's always-loaded `MEMORY.md`. The treatment stored the identical facts in AetnaMem and used a
163-character bootstrap `MEMORY.md`. Both arms used the same OpenClaw release, DeepSeek V4
Flash model, non-thinking mode, workspace scaffold, prompt, scorer, and one fresh session per trial. Pair order alternated
by case and repetition. The scorer required every pre-registered answer fragment in `cases.json`; it was not changed after
responses were observed.

Provider token and cost fields came from each OpenClaw session JSONL. Prompt tokens are the sum of uncached input and
cache-read tokens; reporting only uncached input would incorrectly count a cache hit as removed context. Wall latency surrounds the complete local OpenClaw
process, so it includes plugin/process startup as well as model latency. AetnaMem record IDs and retrieval-event counts are
included in the machine-readable result; full session files remain hash-addressed rather than committed because they include
large OpenClaw system/tool prompts.

## Interpretation and limits

This is an integration benchmark, not a universal savings claim. It measures cross-session factual recall with one model,
one OpenClaw release, a synthetic mature memory, and 20 paired trials. Results will vary with native-memory size,
tool schemas, caching, language, prompt length, and retrieval selectivity. The AetnaMem arm still pays OpenClaw's system/tool
overhead plus bounded persona/recall context. Prompt caching was not credited (`cacheRead` is reported separately), and no
claim is made about long conversations, procedural skill selection, or clinical outcome quality. Independent replication,
additional models, larger task sets, and repeated runs on controlled hardware are required before inferential generalization.

DeepSeek served a larger fraction of the native arm from its inexpensive prompt cache (41.0%
versus 28.1%). Consequently, fewer prompt tokens did not reduce the bill in this run: the
AetnaMem arm cost +0.674% more. Selective memory and prompt caching optimize
different quantities and should be evaluated together.
