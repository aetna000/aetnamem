# aetnamem

An agent memory engine built to pass the audit that most memory stacks fail.
Fully local, zero configuration, one SQLite file — and every guarantee it
makes is verifiable from the outside.

- **Provenance is mandatory.** Every record carries its source type, session,
  turn, timestamp, confidence, and a link back to the raw episode it was
  extracted from.
- **Untrusted content is quarantined.** Facts extracted from webpages or tool
  output never silently become durable memory — they land `quarantined` and
  only activate through an explicit `promote()`.
- **Updates supersede, never overwrite.** A correction replaces the old fact
  (keyed on the extracted fact slot), and the old record stays inspectable as
  `superseded`.
- **Deletion actually deletes.** `forget()` tombstones matching records,
  purges their content *and* the source episode text, and the result is
  verifiable via `inspect()`.
- **The audit log is tamper-evident.** Every mutation and every recall is an
  event in a per-subject SHA-256 hash chain; `audit()` re-verifies the chain
  on read. Agent actions (tool calls, decisions) can join the same chain via
  `log_action()`.

## Install & use

```bash
pip install -e .
```

```python
from aetnamem import Memory

m = Memory("./memories.db")          # or ":memory:"

m.remember("user-1", "My preferred airport is SFO.", session_id="s1")
m.remember("user-1", "Actually, use OAK as my preferred airport going forward.",
           session_id="s2")

m.recall("user-1", "Which airport should I fly from?")
# -> [{'content': "User's preferred airport is OAK.", 'status': 'active', ...}]

m.forget("user-1", utterance="Forget my preferred airport.")
m.inspect("user-1")                  # full evidence dump, incl. audit chain check
```

The six verbs — `remember`, `recall`, `list`, `forget`, `inspect`, `audit` —
plus `promote` (quarantine release) and `log_action` (agent audit events) are
the entire API. A minimal CLI ships with the package:

```bash
aetnamem inspect ./memories.db user-1
aetnamem audit   ./memories.db user-1
```

## How recall works

Recall has top-k semantics, like a vector store: every *active* record is
scored (SQLite FTS5 full-text relevance with porter stemming, plus trust and
recency priors) and the best `limit` are returned. Quarantined, superseded,
and tombstoned records are never candidates. Every recall writes a retrieval
event containing all candidate scores, so the ranking itself is auditable.
Pass `min_score=` to drop weak matches.

## What v0 is and is not

v0 extraction is deterministic (generic sentence patterns: "my X is Y",
"use Y as my X", "remember that …", "I avoid …") so that policy failures are
debuggable, not probabilistic. LLM-backed extraction, vector similarity,
consolidation, the HTTP server, and the MCP server are planned layers on top
of the same policy gates — see [plan.md](plan.md). The policy gates in
[aetnamem/core/policy.py](aetnamem/core/policy.py) are the product; nothing
in the engine may reference the vocabulary of a benchmark scenario.

## Benchmark

Development is gated on
[MemoryStackBench](https://aetna000.github.io/MemoryStackBench/)'s
`seven_sins_v0_1` suite (webpage poisoning, retention after deletion, missing
provenance, stale temporal updates, overgeneralization). Current score:
**33/33**, with unit tests covering the same gates on non-benchmark
vocabulary to keep the score honest.

```bash
git clone https://github.com/aetna000/MemoryStackBench.git
cd MemoryStackBench
python -m memorybench.cli run \
  --target targets/aetnamem.yaml \
  --suite suites/seven_sins_v0_1 \
  --out runs/aetnamem-local
```

## License

AGPL-3.0 (see [LICENSE](LICENSE)). Anyone may use aetnamem, including
commercially, but derivative works — including software that serves aetnamem
over a network — must be released under the same terms.
