# Cache-aware OpenClaw × AetnaMem benchmark

Run completed: `2026-07-21T02:30:07.266614+00:00`  
Harness commit: `efc1b0bed127859171cf5a93f290847a015fdfe5`  
Model: `deepseek/deepseek-v4-flash` with thinking off  
Measured task calls: 60; cache-probe calls: 6

## Task result

| Metric | Native `MEMORY.md` | Current AetnaMem | Cache-aware AetnaMem |
|---|---:|---:|---:|
| Prompt tokens, total | 596,581 | 521,858 | 517,118 |
| Prompt tokens, median/task | 29,829.0 | 26,076.5 | 25,844.5 |
| Cache-hit fraction | 40.8% | 30.4% | 30.7% |
| Provider cost | $0.056427 | $0.055411 | $0.054752 |
| Correct | 20/20 | 20/20 | 20/20 |
| Target retrieved | — | 20/20 | 20/20 |

Native → cache-aware saved **79,463 prompt tokens
(13.320%)**; provider cost changed
-2.968%. Current → cache-aware saved
**4,740 prompt tokens
(0.908%)**; provider cost changed
-1.190%.

## Cache probes

Two identical, unrelated fresh-session prompts ran consecutively per arm. The first is a first observation, not a guaranteed
cold cache (it already contained cache hits); the second is the immediate repeat. DeepSeek caching is best-effort, so these
six calls are descriptive rather than a controlled cache-disable experiment.

| Arm | First cache hit | Repeat cache hit | First cost | Repeat cost |
|---|---:|---:|---:|---:|
| Native | 4.7% | 21.5% | $0.004018 | $0.003459 |
| Current AetnaMem | 5.4% | 8.4% | $0.003481 | $0.003394 |
| Cache-aware AetnaMem | 5.5% | 8.4% | $0.003451 | $0.003365 |

## Evidence and limits

The cache-aware bundle changes three things together: stable persona placement (`appendSystemContext`), dynamic recall
placement (`appendContext`) with compact references, and omission of explicit search/forget schemas. This measures the
deployable optimized configuration, not the isolated causal effect of each change. The workload is synthetic, uses one
provider/model and one host, repeats 10 cases twice, and cannot establish a universal savings or clinical claim.

Current audit valid: `true`; cache-aware audit valid:
`true`. Raw per-call usage, answers, retrieval labels,
session hashes, input hashes, software versions, and paired bootstrap summaries are in the adjacent JSON artifact.
