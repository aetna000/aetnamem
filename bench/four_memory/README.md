# Four-memory ablation benchmark

Run:

```bash
python bench/four_memory/run_benchmark.py
```

The workload seeds:

- current report progress in working memory;
- a PDF requirement in semantic memory;
- a failed upload and reviewed lesson in episodic memory;
- a versioned report-upload `SKILL.md` in procedural memory.

It then compares the complete runtime, each leave-one-plane-out variant, and a
semantic-only baseline. The output reports evidence coverage, prepared context
size, and preparation latency.

This benchmark deliberately makes no model-quality or universal cost claim. It
tests the memory runtime and makes each plane's marginal contribution visible.
For an end-to-end product claim, feed each emitted pack to the same model and
agent harness, then compare task success, repeated failures, prompt tokens,
provider cost, tool calls, and latency under a pre-registered protocol.
