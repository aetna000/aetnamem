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
- **The audit log is tamper-evident — and independently verifiable.** Every
  mutation and every recall is an event in a per-subject SHA-256 hash chain.
  The format is frozen in [docs/audit-log-spec.md](docs/audit-log-spec.md),
  and [tools/verify_audit.py](tools/verify_audit.py) is a standalone,
  stdlib-only verifier that checks a database without importing aetnamem.
  Agent actions (tool calls, decisions) can join the same chain via
  `log_action()`.
- **The audit plane holds digests, not data.** Recall queries, forget
  selectors, and ingested messages appear in the log only as SHA-256 digests
  (opt in to raw queries with `retain_query_text=True`), so the immutable
  chain never blocks erasure: `forget()` purges content, fact keys, and
  source episodes, and returns a **deletion receipt** cryptographically bound
  to the chain.
- **Checkpoints defeat tail truncation.** A hash chain alone cannot prove
  events weren't deleted from its end. `checkpoint()` pins every chain head
  to a document you anchor externally (WORM storage, a transparency log, an
  RFC 3161 timestamp); `verify(checkpoints_path=...)` then detects
  truncation and database replacement, not just edits.

## Install & use

```bash
pip install aetnamem
# or, from a checkout:
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

The core verbs — `remember`, `recall`, `list`, `forget`, `inspect`, `audit` —
plus `promote` (quarantine release), `log_action` (agent audit events),
`consolidate`, `persona`, `scenes`, `propose`, `checkpoint`, and `verify`
are available from Python and the CLI, so any process that can run a shell
command is a client:

```bash
aetnamem remember   ./memories.db user-1 "My preferred airport is SFO." --session s1
aetnamem recall     ./memories.db user-1 "Which airport should I book from?"
aetnamem forget     ./memories.db user-1 --utterance "Forget my preferred airport."
aetnamem list       ./memories.db user-1 --all
aetnamem promote    ./memories.db user-1 rec_...
aetnamem log-action ./memories.db user-1 tool_call --payload '{"tool":"calendar"}'
aetnamem consolidate ./memories.db user-1
aetnamem persona    ./memories.db user-1
aetnamem scenes     ./memories.db user-1
aetnamem inspect    ./memories.db user-1
aetnamem audit      ./memories.db user-1
aetnamem checkpoint ./memories.db ./checkpoints.jsonl   # anchor this file externally
aetnamem verify     ./memories.db --checkpoints ./checkpoints.jsonl
python tools/verify_audit.py ./memories.db --checkpoints ./checkpoints.jsonl  # no aetnamem import
```

## Use from agents (MCP)

`aetnamem mcp` serves the verbs as MCP tools over stdio — newline-delimited
JSON-RPC implemented with the standard library only, so the zero-dependency
promise holds. Defaults: database at `~/.aetnamem/memories.db` (override
with `--db` or `$AETNAMEM_DB`) and subject `default` (`--subject`), so
single-user personal agents need no per-call subject wiring.

**Claude Code:**

```bash
claude mcp add aetnamem -- aetnamem mcp
```

**Claude Desktop / any host with JSON MCP config** (OpenClaw's MCP bridge
takes the same command + args shape):

```json
{
  "mcpServers": {
    "aetnamem": {
      "command": "aetnamem",
      "args": ["mcp", "--db", "/home/you/.aetnamem/memories.db"]
    }
  }
}
```

The agent gets `memory_remember`, `memory_recall`, `memory_recall_block`
(bounded prompt-injection block), `memory_capture` (auto-capture with
digest-only assistant/tool logging), `memory_list`, `memory_forget`,
`memory_promote`, `memory_audit`, `memory_verify`, and `memory_log_action`.

**OpenClaw users**: [integrations/openclaw](integrations/openclaw) is a
native plugin that adds automatic memory — auto-recall injection before
every prompt and auto-capture after every turn — on top of the same engine
and audit chain. The policy gates run server-side, so a hostile webpage
summarized by the agent still cannot plant durable memory, deletion still
returns receipts, and you can independently audit the same SQLite file with
`aetnamem verify` or `tools/verify_audit.py` while the agent uses it.
Full tool catalog, host configs, and troubleshooting:
[docs/integration-guide.md](docs/integration-guide.md).

## Integrating with other agent frameworks

The rule is: **MCP first, native adapter only when it adds lifecycle hooks.**
Do not fork the memory semantics per host. `aetnamem` should stay the
auditable engine; framework integrations should be thin wrappers that call
the same MCP/Python verbs and preserve the same audit trail.

For any MCP-capable host, start with:

```bash
aetnamem mcp --db ~/.aetnamem/memories.db --subject you
```

Then configure the host to expose the `memory_*` tools. This is the right
first path for Hermes-style agents, Claude Desktop, Claude Code, and any
framework that can launch a stdio MCP server.

Build a native adapter only when the framework gives useful hooks:

| hook point | aetnamem call | purpose |
|---|---|---|
| before prompt/context build | `memory_persona` + `memory_recall_block` | inject bounded, audited context |
| after user/agent turn | `memory_capture` | capture user facts; log assistant/tool output as digests |
| before history write | strip `<user_persona>` / `<relevant_memories>` | prevent recall feedback loops |
| explicit agent tools | `memory_recall`, `memory_forget`, `memory_audit`, `memory_verify` | search, erase, and prove memory behavior |

Native adapters should pass the host's `session_id` and `turn_id` whenever
available, so memory reads, writes, tool calls, forgets, and user-visible
responses line up in one audit timeline.

Priority targets:

| framework / host | first integration | native adapter shape |
|---|---|---|
| OpenClaw | implemented plugin in [integrations/openclaw](integrations/openclaw) | hook-based auto-recall/capture |
| Hermes | MCP setup guide first | memory-provider/plugin wrapper if its provider API is stable |
| LangGraph | Python helper node/store | recall node before model call, capture node after turn |
| OpenAI Agents SDK | tools + runner/session wrapper | pre-run context builder and post-run capture |
| CrewAI | external memory tools | memory adapter if its memory API can preserve receipts/audit IDs |
| Microsoft Agent Framework / Semantic Kernel | plugin/tools | context provider plus action logging |
| LlamaIndex / Haystack | tool/component wrapper | long-term memory component, not replacement for short-term chat state |

The adapter directory should stay organized by host:

```text
integrations/
  openclaw/
  hermes/
  langgraph/
  openai-agents/
  crewai/
  microsoft-agent-framework/
  llamaindex/
  haystack/
```

Each adapter should document the same guarantees: untrusted content stays
quarantined, deletion returns receipts, recall injection is bounded and
audited, and the SQLite database can still be verified externally with
`aetnamem verify` or `tools/verify_audit.py`.

## Compliance posture

The architecture separates the **erasable data plane** (`records`,
`episodes` — purged by `forget()`) from the **immutable audit plane**
(digests and structural metadata only). That split is what lets deletion be
real (GDPR Art. 17, CCPA, FTC deception standards for "we delete your data"
claims) while the audit trail stays append-only and hash-chained (GDPR
Art. 5(2) accountability; EU AI Act Art. 12/19 logging for high-risk
systems). Deletion receipts give controllers evidence to answer data-subject
requests. Still on the roadmap: crypto-shredding of content at rest,
retention policies, and special-category (Art. 9) flagging — see
[docs/audit-log-spec.md](docs/audit-log-spec.md) for the exact threat model
of what today's design does and does not detect.

## Memory layers

- **L0 — episodes**: raw turns, append-only, purged by deletion.
- **L1 — records**: extracted facts with provenance.
- **L2 — scenes**: deterministic per-session view (`aetnamem scenes`).
- **L3 — persona**: live-derived snapshot of active facts
  (`aetnamem persona`, MCP `memory_persona`) — never stored, so it can
  never go stale; every line carries its source record id.
- **Derived proposals**: external LLM/batch jobs submit candidates via
  `aetnamem propose` / `Memory.propose_facts()`; they land *quarantined*
  with mandatory evidence links and only activate through `promote()`.

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
debuggable, not probabilistic. The local Python API, CLI, MCP server,
deterministic consolidation, persona snapshots, scenes, checkpoints, and
independent verifier are implemented. LLM-backed extraction, vector
similarity, HTTP/server deployments, and additional storage backends remain
roadmap layers on top of the same policy gates — see [plan.md](plan.md).
The policy gates in [aetnamem/core/policy.py](aetnamem/core/policy.py) are
the product; nothing in the engine may reference the vocabulary of a
benchmark scenario.

## Documentation

- **[docs/integration-guide.md](docs/integration-guide.md)** — full CLI
  reference (every command, flags, output shapes, exit codes) and MCP
  server reference (transport, flags, tool catalog, host configs for
  Claude Code / Claude Desktop / OpenClaw-style bridges, security
  properties, troubleshooting).
- **[docs/openclaw-setup.md](docs/openclaw-setup.md)** — visual (Mermaid)
  walkthrough of wiring aetnamem into OpenClaw or any MCP host: setup flow,
  runtime sequence, the quarantine gate, and the external audit loop.
- **[docs/auditing-guide.md](docs/auditing-guide.md)** — how to *use* the
  auditability: checkpoint cadence and anchoring recipes, verifying after an
  incident, handling erasure/access/rectification requests with receipts,
  reviewing quarantine, logging agent actions onto the same chain, and what
  to hand an external auditor.
- **[docs/audit-log-spec.md](docs/audit-log-spec.md)** — the frozen wire
  format: canonical serialization, hash preimages, chain/checkpoint/receipt
  verification rules, and the threat-model table.
- **[plan.md](plan.md)** — architecture plan and roadmap.

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
cp /path/to/aetnamem/bench/adapters/aetnamem.py memorybench/adapters/aetnamem.py
cp /path/to/aetnamem/bench/targets/aetnamem.yaml targets/aetnamem.yaml
PYTHONPATH=/path/to/aetnamem:$PWD \
python -m memorybench.cli run \
  --target targets/aetnamem.yaml \
  --suite suites/seven_sins_v0_1 \
  --out runs/aetnamem-local
```

## License

AGPL-3.0 (see [LICENSE](LICENSE)). Anyone may use aetnamem, including
commercially, but derivative works — including software that serves aetnamem
over a network — must be released under the same terms.
