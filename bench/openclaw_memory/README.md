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
