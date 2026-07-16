<p align="center">
  <img src="./docs/assets/aetnamem-header.png" width="1536" alt="aetnamem control plane: provenance-aware memory, guarded actions, and independently verifiable evidence">
</p>

<h1 align="center">aetnamem</h1>

<p align="center">
  <strong>Evidence before effect.</strong><br>
  Auditable memory and exact-plan guarded actions for stateful AI agents.
</p>

<p align="center">
  <a href="https://github.com/aetna000/aetnamem/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/aetna000/aetnamem/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Version 0.3.0" src="https://img.shields.io/badge/version-0.3.0-315A7D?style=flat-square">
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-%E2%89%A53.10-2A6F73?style=flat-square&logo=python&logoColor=white">
  <img alt="AGPL 3.0" src="https://img.shields.io/badge/license-AGPL--3.0-B23A48?style=flat-square">
  <a href="https://aetna000.github.io/MemoryStackBench/"><img alt="MemoryStackBench 33 out of 33" src="https://img.shields.io/badge/MemoryStackBench-33%2F33-D49A2A?style=flat-square"></a>
</p>

<p align="center">
  <a href="#install--use">Quick start</a> &middot;
  <a href="./docs/macos-desktop.md">macOS desktop</a> &middot;
  <a href="./examples/flagship-demo/">Flagship demo</a> &middot;
  <a href="./paper/aetnamem-control-plane.pdf">Scientific report</a> &middot;
  <a href="./docs/guarded-actions.md">Guarded actions</a> &middot;
  <a href="./TODO.md">Roadmap</a>
</p>

A local-first, zero-dependency Python engine for provenance-aware agent memory
and optional guarded actions. The reference store is one SQLite file. Its
security claims are deterministic and testable, but deliberately narrower
than “the database is trusted” or “every external action is reversible.”

## What can I use today?

A local assistant desktop app: governed chat backed by a lightweight local
Ollama model, visible/searchable memory, approval-gated file writes in a safe
workspace, an in-browser file viewer/editor, and a live-verified audit chain.
One launcher does everything — installs Ollama if missing, pulls the
`qwen3:1.7b` model on first run, starts the service, and opens the dashboard
in your browser **already signed in** (tokens ride in the URL fragment and
never leave the browser).

### macOS

```bash
git clone https://github.com/aetna000/aetnamem.git && cd aetnamem
chmod +x scripts/macos/aetnamem-desktop.command
open scripts/macos/aetnamem-desktop.command
```

macOS additionally seals the memory database encrypted at rest on quit, keyed
through the Keychain. Details: **[aetnamem Desktop for macOS](./docs/macos-desktop.md)**.

### Linux (Ubuntu/Debian and RHEL/Fedora/CentOS)

```bash
git clone https://github.com/aetna000/aetnamem.git && cd aetnamem
chmod +x scripts/linux/aetnamem-desktop.sh
./scripts/linux/aetnamem-desktop.sh
```

Needs `python3` ≥ 3.10 (`sudo apt-get install python3` /
`sudo dnf install python3`) and `curl`. Ollama is installed via its official
installer if missing. The database lives at
`~/.local/share/aetnamem/memories.db` (no at-rest sealing on Linux yet).

### Windows 10/11

Double-click `scripts\windows\aetnamem-desktop.bat`, or run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\aetnamem-desktop.ps1
```

Needs Python 3.10+ (`winget install Python.Python.3.12`). Ollama is installed
via `winget` if missing. The database lives at `%LOCALAPPDATA%\aetnamem`
(no at-rest sealing on Windows yet).

### Using the app

1. **Chat** — the assistant runs fully on your machine with the local model.
   Tell it things worth remembering; ask it to draft files.
2. **Approvals tab** — when the assistant wants to write a file, the action is
   staged, never executed. Review the plan and click *Approve & run* or *Deny*.
3. **Files tab** — everything in your workspace (`~/Aetnamem Workspace` on
   macOS/Windows, `~/aetnamem-workspace` on Linux). Markdown renders in the
   browser; any text file can be edited and saved in place.
4. **Memory tab** — every remembered fact with status, provenance, and trust
   tier; search and filter, including quarantined and forgotten records.
5. **Settings** — switch provider (local Ollama, OpenAI, DeepSeek, or any
   OpenAI-compatible endpoint), run the system check, and review the
   *Data & security* panel showing exactly where your data lives.

### Data location and backup

The desktop launchers use platform-native data locations: macOS stores a
Keychain-protected sealed database under `~/Library/Application Support`,
Linux uses `$XDG_DATA_HOME` when set and otherwise `~/.local/share`, and
Windows uses `%LOCALAPPDATA%`. Workspace files are stored separately. Quit
the service before copying SQLite data, and on macOS back up the encrypted
database, its HMAC sidecar, and a recoverable copy of the Keychain key. See
**[Data storage, backup, and restore](./docs/data-storage-and-backup.md)** for
exact paths and restore instructions.

- **Provenance is required.** Extracted records link to their source episode;
  derived proposals instead cite existing episode or record IDs. Records also
  carry source, session, turn, time, confidence, status, and trust metadata.
- **Classified untrusted content is quarantined.** Records classified as
  webpage or tool output land `quarantined` until `promote()`. Correct origin
  classification is a host responsibility: an untrusted caller that may lie
  about `source_type` is outside this local API's trust boundary. `promote()`
  records a trust transition but does not authenticate human confirmation;
  protect or withhold that capability when the agent itself is untrusted.
- **Recognized corrections supersede.** When extraction assigns the same
  `fact_key`, the new trusted record supersedes the previous active record;
  the old record remains inspectable. Unrecognized or unkeyed contradictions
  are not automatically resolved.
- **Memory content is logically purged.** `forget()` tombstones matching
  records, clears their content and fact key, clears matching source episode
  text, removes FTS entries, and returns a deletion receipt. SQLite free
  pages, WAL files, filesystem snapshots, replicas, and backups require their
  own secure-erasure and retention controls.
- **The audit log is independently checkable.** Engine-generated memory and
  guarded-action transitions join a per-subject SHA-256 chain specified in
  [audit-log specification](https://github.com/aetna000/aetnamem/blob/main/docs/audit-log-spec.md). The standard-library
  [independent verifier](https://github.com/aetna000/aetnamem/blob/main/tools/verify_audit.py) imports no aetnamem
  code. Hash chaining detects edits relative to a trusted head; externally
  anchored checkpoints are required to detect suffix deletion or replacement
  of the entire database.
- **Sensitive values are separated on guarded paths.** Core memory and
  guarded-action events use content digests and structural metadata. Raw
  action arguments and before-images live in an erasable payload table.
  `retain_query_text=True` stores raw recall queries, and the low-level
  `log_action()` method accepts caller-provided payloads, so callers must not
  place secrets or raw content there.

## Guarantee boundaries

| boundary | engine enforces | deployment must provide |
|---|---|---|
| memory origin | quarantine based on the supplied/classified source type | authentic source attribution when callers are not trusted |
| quarantine promotion | only quarantined records can be promoted; transition is audited | authenticated user confirmation and access control to `promote()` |
| audit history | canonical hashes, per-subject chaining, receipt binding | external checkpoint anchoring against database-owner rewriting |
| memory erasure | logical purge from live tables and indexes | backup/WAL/snapshot retention and forensic secure deletion |
| action authority | exact-plan HMAC signed by a reviewer-key holder | protecting that key and the staging boundary from the agent |
| approver identity | records the supplied approver label | identity authentication; the shared HMAC does not prove that label |
| external effects | adapter preconditions, receipts, postcondition checks, explicit uncertainty | provider-specific idempotency and authoritative recovery where needed |

## Install & use

```bash
pip install aetnamem
# or, from a checkout:
pip install -e .
```

The package installs two console commands:

- `aetnamem` provides the memory CLI, the MCP server through `aetnamem mcp`,
  and guarded actions through `aetnamem actions …`.
- `aetnamem-service` starts the local assistant dashboard. Run
  `aetnamem-service --help` for workspace, database, network, and browser
  options. The cross-platform desktop launchers above additionally bootstrap
  Ollama and the recommended lightweight model.

`aetna000` is the organization namespace only; it is not installed as a
product command.

```python
from aetnamem import Memory

m = Memory("./memories.db")          # or ":memory:"

m.remember("user-1", "My preferred airport is SFO.", session_id="s1")
m.remember("user-1", "Actually, use OAK as my preferred airport going forward.",
           session_id="s2")

m.recall("user-1", "Which airport should I fly from?")
# -> [{'content': "User's preferred airport is OAK.", 'status': 'active', ...}]

# Optional graph recall adds bounded multi-hop retrieval while preserving
# direct record fallback and the same governance rules.
m.recall("user-1", "What airport does my boss prefer?", use_graph=True)

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

The standalone `tools/verify_*.py` commands are included in Git checkouts and
source distributions. Wheel-only installs should use `aetnamem verify` and
`aetnamem actions verify`, which cover the same integrity rules.

## Guarded actions

Guarded-actions mode turns a proposed tool mutation into a canonical hash-bound
`WorldPatch`: exact operation digests, resource preconditions, adapter
fingerprints, causal evidence, authority, approval, execution attempts,
verification, compensation, and a receipt all share the subject's audit
chain. Evidence that merely `informed_by` an operation is distinct from the
host-attested `authorized_by` evidence that permits it.

The first reference adapter performs root-confined UTF-8 file writes and
deletes. It is classified as **verified compensatable**, not transactionally
reversible: `aetnamem` rechecks the before-state, executes only an exact approved
plan, observes the after-state, and verifies any compensation against the
captured before-state.

```bash
mkdir -p ./workspace

# Agent/host staging boundary: no reviewer key is needed here.
aetnamem actions stage ./memories.db user-1 filesystem write_text \
  --root ./workspace \
  --args '{"path":"report.md","content":"reviewed content"}' \
  --actor researcher-agent \
  --authority-id task-42 \
  --authority-digest 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

aetnamem actions show    ./memories.db act_...

# Separate trusted reviewer/executor shell. Persist this key securely.
export AETNAMEM_APPROVAL_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
aetnamem actions approve ./memories.db act_... --approver-label user-1
aetnamem actions commit  ./memories.db act_... --root ./workspace
aetnamem actions verify  ./memories.db act_...
python tools/verify_actions.py ./memories.db act_...  # no aetnamem import
```

Changing the persisted plan, adapter manifest, approval binding, expiry, or
guarded file precondition prevents execution. Raw arguments, before-images, and provider
receipts live in the erasable action payload plane; audit events contain only
structural metadata and digests. Erase those payloads after their retention
period with `aetnamem actions purge-payloads ./memories.db act_...`.
If a process dies across an external execution boundary, use
`aetnamem actions recover ./memories.db act_...`; it fences in-flight effects
as uncertain and emits a `recovery_required` receipt instead of retrying.

Compatible external transaction journals can join the same forensic timeline
without copying their raw arguments, snapshots, results, claimed actors, or
client IDs into the audit plane:

```bash
aetnamem actions import-journal ./memories.db user-1 ./source-journal.db \
  --source-id production-agent
```

Imports are idempotent per source/transaction and are explicitly labeled
`unverified_operational_journal`: importing external evidence does not upgrade
its mutable status rows or claimed identities into `aetnamem` proof.

The HMAC approval key belongs in the human/reviewer process, not the
agent-facing process. The `--approver-label` value is attribution; the shared key
authenticates key possession, not that label. Likewise, CLI
`--authority-id/--authority-digest` flags are only host-attested when a trusted
host controls the staging command. The filesystem CLI is a reference vertical
slice; the MCP gate, Telegram reviewer, additional execution providers,
Firestore, and X adapters are tracked explicitly in the [roadmap](https://github.com/aetna000/aetnamem/blob/main/TODO.md).
Protocol and security details are in
[guarded-actions guide](https://github.com/aetna000/aetnamem/blob/main/docs/guarded-actions.md).

## Use from agents (MCP)

`aetnamem mcp` currently serves **memory verbs only** as MCP tools over stdio:
newline-delimited JSON-RPC implemented with the standard library only, so the
zero-dependency promise holds. Defaults: database at
`~/.aetnamem/memories.db` (override
with `--db` or `$AETNAMEM_DB`) and subject `default` (`--subject`), so
single-user personal agents need no per-call subject wiring. It is not yet an
action interception gateway and does not prevent an agent from calling other
write tools directly.

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
(bounded prompt-injection block), `memory_persona`, `memory_capture`
(auto-capture with digest-only assistant/tool logging), `memory_list`,
`memory_forget`, `memory_promote`, `memory_audit`, `memory_verify`, and
`memory_graph_status`, `memory_graph_merges`, `memory_graph_history`, and
`memory_log_action`. Graph merge decisions are deliberately absent from MCP;
they require the reviewer-authenticated dashboard/HTTP surface or explicit
CLI use.

`subject_id` is a storage scope chosen by the caller, not an authenticated
tenant identity. Likewise, exposing `memory_promote` lets the agent request a
promotion; use a trusted approval layer or omit that tool when promotion must
be human-only.

**Grok/xAI users**: the [Grok/xAI guide](https://github.com/aetna000/aetnamem/blob/main/docs/grok-xai.md) shows how to expose
`aetnamem` as xAI function-calling tools today, with a local playground that
lets Grok search, capture, forget, and audit memory while the engine keeps
provenance and deletion receipts. xAI Remote MCP is the deployment path once
the local stdio MCP server is exposed behind an HTTP/SSE gateway.

**OpenClaw users**: the [native integration](https://github.com/aetna000/aetnamem/tree/main/integrations/openclaw) is a
native plugin that adds automatic memory — auto-recall injection before
every prompt and auto-capture after every turn — on top of the same engine
and audit chain. The policy gates run server-side, so a hostile webpage
summarized by the agent still cannot plant durable memory, deletion still
returns receipts, and you can independently audit the same SQLite file with
`aetnamem verify` or `tools/verify_audit.py` while the agent uses it.
Full tool catalog, host configs, and troubleshooting:
[integration guide](https://github.com/aetna000/aetnamem/blob/main/docs/integration-guide.md).

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
| explicit agent tools | `memory_recall`, `memory_forget`, `memory_audit`, `memory_verify` | search, request logical purge, and verify recorded behavior |

Native adapters should pass the host's `session_id` and `turn_id` whenever
available, so memory reads, writes, tool calls, forgets, and user-visible
responses line up in one audit timeline.

Priority targets:

| framework / host | first integration | native adapter shape |
|---|---|---|
| OpenClaw | implemented [native plugin](https://github.com/aetna000/aetnamem/tree/main/integrations/openclaw) | hook-based auto-recall/capture |
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

The architecture separates mutable content tables from an engine-append-only,
hash-chained audit table. This can support accountability, access,
rectification, and deletion workflows, but it is not compliance certification
or legal advice. `forget()` performs a logical purge in the live database; it
does not by itself sanitize SQLite free pages, WAL files, backups, exports, or
external replicas. Checkpoint placement, retention, secure erasure, access
control, identity, lawful basis, and jurisdiction-specific requirements remain
deployment responsibilities. See the [audit-log specification](https://github.com/aetna000/aetnamem/blob/main/docs/audit-log-spec.md)
for the precise integrity threat model.

## Memory layers

- **L0 — episodes**: raw turns, append-only, purged by deletion.
- **L1 — records**: extracted facts with provenance.
- **L2 — scenes**: deterministic per-session view (`aetnamem scenes`).
- **L3 — persona**: live-derived snapshot of active facts
  (`aetnamem persona`, MCP `memory_persona`) — no cached persona is stored;
  each generated snapshot carries its source record IDs.
- **Derived proposals**: external LLM/batch jobs submit candidates via
  `aetnamem propose` / `Memory.propose_facts()`; they land *quarantined*
  with mandatory evidence links and only activate through `promote()`.

## How recall works

Recall has top-k semantics. SQLite FTS5 selects a bounded
candidate set (200 by default), trust and recency priors rank it, and the best
`limit` records are returned. Quarantined, superseded, and tombstoned records
are never candidates. Retrieval events record the algorithm, cap, candidate
count, and a bounded score sample so audit payloads do not grow with the whole
database. Pass `min_score=` to drop weak matches.

Graph recall is opt-in with `use_graph=True`, CLI `--graph`, or service
`AETNAMEM_GRAPH_RECALL=1`. It extracts a conservative entity/edge index from
governed records, seeds it with FTS5, spreads through at most two bounded
hops, and blends the result with direct record recall. Returned graph hits
include their path evidence. The index inherits quarantine, promotion,
supersession, and forgetting; it can be recreated at any time:

```bash
aetnamem graph-backfill ./memories.db user-1
aetnamem recall ./memories.db user-1 "What airport does my boss prefer?" --graph
aetnamem graph-consolidate ./memories.db user-1
aetnamem graph-merges ./memories.db user-1 --status pending
aetnamem graph-inspect ./memories.db user-1
```

## What v0 is and is not

v0 extraction is deterministic (generic sentence patterns: "my X is Y",
"use Y as my X", "remember that …", "I avoid …") so that policy failures are
debuggable, not probabilistic. The local Python API, CLI, MCP server,
deterministic consolidation, persona snapshots, scenes, checkpoints, and
independent memory verifier are implemented. An optional, deterministic graph
index provides bounded multi-hop recall with path evidence and direct-record
fallback. Guarded Actions additionally
ships an action ledger, exact-plan shared-key approvals, filesystem reference
adapter, recovery fencing, external journal import, and independent action
verifier. The MCP action gate, authenticated host identity, encrypted payloads,
LLM-backed graph extraction, HTTP deployments, and additional
storage backends remain roadmap work — see the [roadmap](https://github.com/aetna000/aetnamem/blob/main/TODO.md).
The policy gates in [aetnamem/core/policy.py](https://github.com/aetna000/aetnamem/blob/main/aetnamem/core/policy.py) are
the product; nothing in the engine may reference the vocabulary of a
benchmark scenario.

## Documentation

- **[macOS desktop guide](https://github.com/aetna000/aetnamem/blob/main/docs/macos-desktop.md)** — local dashboard,
  onboarding checks, provider setup, approval UI, safe workspace, Keychain
  secrets, and encrypted at-rest database sealing.
- **[Data storage and backup](https://github.com/aetna000/aetnamem/blob/main/docs/data-storage-and-backup.md)** — default
  database/workspace paths on macOS, Linux, and Windows, plus safe backup,
  key recovery, restore steps, and encryption boundaries.
- **[Integration guide](https://github.com/aetna000/aetnamem/blob/main/docs/integration-guide.md)** — full CLI
  reference (every command, flags, output shapes, exit codes) and MCP
  server reference (transport, flags, tool catalog, host configs for
  Claude Code / Claude Desktop / OpenClaw-style bridges, security
  properties, troubleshooting).
- **[OpenClaw setup](https://github.com/aetna000/aetnamem/blob/main/docs/openclaw-setup.md)** — visual (Mermaid)
  walkthrough of wiring aetnamem into OpenClaw or any MCP host: setup flow,
  runtime sequence, the quarantine gate, and the external audit loop.
- **[Grok/xAI guide](https://github.com/aetna000/aetnamem/blob/main/docs/grok-xai.md)** — Grok/xAI function-calling
  quickstart, local playground, and Remote MCP deployment notes.
- **[Graph memory design](https://github.com/aetna000/aetnamem/blob/main/docs/graph-memory-design.md)** — implemented
  Phase 0–4 graph index: entities and typed edges over governed records,
  bounded seed+spread recall, reviewer-gated reversible merges, scheduled
  consolidation, cold history partitions, and incremental audit verification.
- **[Auditing guide](https://github.com/aetna000/aetnamem/blob/main/docs/auditing-guide.md)** — how to *use* the
  auditability: checkpoint cadence and anchoring recipes, verifying after an
  incident, handling erasure/access/rectification requests with receipts,
  reviewing quarantine, logging agent actions onto the same chain, and what
  to hand an external auditor.
- **[Audit-log specification](https://github.com/aetna000/aetnamem/blob/main/docs/audit-log-spec.md)** — the frozen wire
  format: canonical serialization, hash preimages, chain/checkpoint/receipt
  verification rules, and the threat-model table.
- **[Guarded actions](https://github.com/aetna000/aetnamem/blob/main/docs/guarded-actions.md)** — action modes,
  authority boundaries, state transitions, guarantees, and non-guarantees.
- **[Roadmap](https://github.com/aetna000/aetnamem/blob/main/TODO.md)** — completed foundation work and remaining product,
  provider, security, and interface tasks.
- **[Architecture plan](https://github.com/aetna000/aetnamem/blob/main/plan.md)** — architecture plan and roadmap.

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

AGPL-3.0 (see the [license](https://github.com/aetna000/aetnamem/blob/main/LICENSE)). Anyone may use aetnamem, including
commercially, but derivative works — including software that serves aetnamem
over a network — must be released under the same terms.
