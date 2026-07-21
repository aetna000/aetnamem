# OpenClaw durable-memory benchmark

This paired integration benchmark compares OpenClaw's always-loaded
`MEMORY.md` with the same durable facts stored behind AetnaMem's bounded,
audited recall. It runs real fresh-session turns through DeepSeek V4 Flash and
captures provider-reported tokens/cost, wall latency, exact-answer accuracy,
retrieved record IDs, and hashes of the OpenClaw session evidence.

```bash
export DEEPSEEK_API_KEY=...       # never persisted by the runner
python bench/openclaw_memory/run_benchmark.py --repetitions 2
```

The runner creates two isolated temporary OpenClaw profiles, installs the
official DeepSeek provider into both, installs the checkout's AetnaMem plugin
only in the treatment, alternates pair order, and removes the profiles after
the run. Pass `--keep-runtime` only when session-level inspection is required.

The workload and answer fragments are pre-registered in `cases.json`. Results
are written as JSON plus a generated Markdown methods/results report under
`results/`. Do not treat one run as a universal product claim: replicate it,
retain independent run files, report failures, and expand models/tasks before
using the data for a paper-level inference.

The definitive DeepSeek run is checked in under [`results/`](results/). Its
technical protocol, statistical interpretation, and threats to validity are in
[`docs/openclaw-memory-evaluation.md`](../../docs/openclaw-memory-evaluation.md).

The cache-aware follow-up compares native `MEMORY.md`, the legacy AetnaMem
prompt layout, and the optimized stable-system/dynamic-tail layout:

```bash
export DEEPSEEK_API_KEY=...
python bench/openclaw_memory/run_cache_benchmark.py --repetitions 2
```

The 2026-07-21 run found 13.320% fewer prompt tokens and 2.968% lower cost
against native memory, with 20/20 correct answers in every arm. Against the
current AetnaMem layout, the optimized bundle used 0.908% fewer prompt tokens
and cost 1.190% less. It did **not** increase absolute DeepSeek cache reads;
the improvement came from compact references and omitted optional tool-schema
overhead within the bundle. See the raw JSON before attributing the result to
any individual change.
