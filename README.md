<p align="center">
  <img src="./docs/assets/aetnamem-header.png" width="1536" alt="aetnamem control plane: provenance-aware memory, guarded actions, and independently verifiable evidence">
</p>

<h1 align="center">aetnamem</h1>

<p align="center">
  <strong>AetnaMem remembers whether remembering actually helped.</strong><br>
  Four governed memory planes, one agent connection, and an experimental evidence loop.
</p>

<p align="center">
  <a href="https://github.com/aetna000/aetnamem/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/aetna000/aetnamem/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Version 0.5.0" src="https://img.shields.io/badge/version-0.5.0-315A7D?style=flat-square">
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-%E2%89%A53.10-2A6F73?style=flat-square&logo=python&logoColor=white">
  <img alt="AGPL 3.0" src="https://img.shields.io/badge/license-AGPL--3.0-B23A48?style=flat-square">
  <a href="https://aetna000.github.io/MemoryStackBench/"><img alt="MemoryStackBench 33 out of 33" src="https://img.shields.io/badge/MemoryStackBench-33%2F33-D49A2A?style=flat-square"></a>
</p>

<p align="center">
  <a href="#give-openclaw-four-kinds-of-memory">OpenClaw quick start</a> &middot;
  <a href="./docs/current-status.md">Current status</a> &middot;
  <a href="#the-four-memories-in-plain-language">Four memories</a> &middot;
  <a href="#ready-made-configurations">Presets</a> &middot;
  <a href="./docs/macos-desktop.md">macOS desktop</a> &middot;
  <a href="./examples/flagship-demo/">Flagship demo</a> &middot;
  <a href="./examples/grok-memory-game/">Grok memory game</a> &middot;
  <a href="./paper/aetnamem-control-plane.pdf">Scientific report</a> &middot;
  <a href="./docs/guarded-actions.md">Guarded actions</a> &middot;
  <a href="./TODO.md">Roadmap</a>
</p>

AetnaMem is a local-first memory runtime and evidence layer for agents. Instead of making an
OpenClaw user configure four databases or four tools, AetnaMem coordinates all
four kinds of memory behind one connection and gives the agent one bounded
context pack. Its experimental Causal Memory Ledger (CML) records which
eligible memory contributions were assigned, which were actually shown, and
which outcome was later reported. That is the foundation for testing whether
memory earned its context cost rather than assuming that retrieval was useful.

The current public release is **Python v0.5.0** with
**OpenClaw plugin v0.3.0**. It includes the opt-in four-memory runtime and the
first default-off CML foundation. CML does not yet prove a causal benefit;
the synthetic causal benchmark, estimators, held-out policy evaluation, and
trusted host adapters remain roadmap work. See
[current capability status](./docs/current-status.md) before relying on a
development feature.

## Give OpenClaw four kinds of memory

You do not need to understand memory databases. Install AetnaMem and its
OpenClaw plugin, run the wizard, and enable the configuration it creates:

```bash
python3 -m pip install --upgrade aetnamem
openclaw plugins install npm:openclaw-memory-aetnamem@latest --pin
aetnamem setup
openclaw aetnamem setup --single-user --subject you \
  --orchestrated --runtime-config ~/.aetnamem/runtime.json
```

The wizard walks through exactly ten short steps:

1. Explain what AetnaMem will add.
2. Choose a ready-made setup.
3. Name the person whose memories these are.
4. Name the agent.
5. Choose the private SQLite location.
6. Optionally point to OpenClaw `SKILL.md` files.
7. Choose where the configuration is saved.
8. Confirm the safety model.
9. Write and validate the configuration.
10. Print the exact OpenClaw and generic MCP commands.

For a scripted install with safe single-user defaults:

```bash
aetnamem setup --yes --preset starter --subject you \
  --agent openclaw-primary
```

Check the result before connecting an agent:

```bash
aetnamem runtime status --config ~/.aetnamem/runtime.json
```

Existing `aetnamem mcp`, Python `Memory`, and non-orchestrated OpenClaw setups
continue to use the original semantic recall path. Four-memory orchestration is
opt-in and falls back to legacy recall if the connected Python package does not
offer the runtime tools.

## The four memories in plain language

Imagine an agent completing a task:

```text
What am I doing now?      → Working memory
What facts do I know?     → Semantic memory
What happened last time?  → Episodic memory
How should I do this?      → Procedural memory
                                  │
                                  ▼
                         One bounded context pack
                                  │
                                  ▼
                         OpenClaw or another agent
```

| Memory | What it gives the agent | A simple example |
|---|---|---|
| **Working** | The current goal, constraints, progress, and unresolved items | “The report is drafted; upload is still pending.” |
| **Semantic** | Governed facts and preferences with provenance, correction, and deletion | “Production reports must be PDF.” |
| **Episodic** | Relevant prior attempts, successes, failures, and reviewed lessons | “The previous upload timed out after using the old endpoint.” |
| **Procedural** | The best versioned skill or procedure for the task | “Use the report-upload skill and verify its receipt.” |

After the agent acts, AetnaMem can record the outcome reported by the caller.
The generic CLI and MCP paths label this evidence `caller_asserted`; a trusted
host integration must separately authenticate evidence before labeling it
`host_attested`. Failed
outcomes may create a **quarantined lesson proposal** for review. A skill can
inform an action, but it never authorizes an action; optional Guarded Actions
remain the approval boundary.

## Ready-made configurations

The wizard creates normal JSON, but most users should start from a preset:

| Preset | Best for | Behavior |
|---|---|---|
| `starter` | One person and one OpenClaw agent | Balanced local defaults |
| `private` | Minimal local context and conservative retrieval | Smaller budgets and stricter matching |
| `team` | Several cooperating agents behind a trusted host | Larger budgets and team-ready policy fields |
| `benchmark` | Reproducible comparisons | Generous deterministic budgets |

List or generate presets without the wizard:

```bash
aetnamem runtime presets
aetnamem runtime init --preset private --subject you \
  --agent openclaw-primary --output ~/.aetnamem/runtime.json
```

The same runtime works with Grok, Claude, DeepSeek, OpenAI, Ollama, or another
model because coordination happens through generic MCP:

```bash
aetnamem runtime mcp --config ~/.aetnamem/runtime.json
```

See the [four-memory runtime guide](./docs/four-memory-runtime.md) for the
configuration, lifecycle, lesson review, and generic MCP tools. The
[four-memory ablation benchmark](./bench/four_memory/) shows the complete
runtime beside semantic-only and each leave-one-plane-out variant without
making a model-quality claim.

## What can you do with this repository?

Think of AetnaMem as a governed continuity layer for AI systems. It helps an
agent remember useful context, helps people understand where that context came
from, and can carry evidence forward into reviewed decisions and approved
changes. You can adopt one part without adopting the rest.

### AI and agent use cases

| What you want | What AetnaMem provides | Read more |
|---|---|---|
| Give an assistant durable memory | Remember, recall, correct, supersede, inspect, and forget user facts across sessions | [Integration guide](./docs/integration-guide.md) |
| Reduce repeated prompt context | A cache-aware context pack separates a stable persona from selective turn recall, applies hard budgets, and avoids repeating the same record in both blocks | [0.4.1 release and measured result](./docs/releases/v0.4.1.md) |
| Add memory to different agent frameworks | One Python, CLI, and MCP contract works independently of the model provider; build thin host adapters only when automatic lifecycle hooks are useful | [Agent/MCP integration](#use-from-agents-mcp) |
| Add automatic memory to OpenClaw | The npm plugin injects bounded recall before a prompt and captures trusted user facts after a turn | [OpenClaw setup](./docs/openclaw-setup.md) |
| Add memory tools to Hermes | Hermes can discover AetnaMem over MCP; a context-engine wrapper can consume the same cache-aware context pack | [Hermes guide](./docs/hermes-agent.md) |
| Use Claude, Grok, DeepSeek, OpenAI, Ollama, or another model | Memory policy and storage remain outside the model; swap the inference provider without replacing the memory engine | [Grok/xAI guide](./docs/grok-xai.md) and [integration guide](./docs/integration-guide.md) |
| See how AetnaMem helps Grok in a game | The Grok Memory Challenge demonstrates selective recall, correction, poisoned-context quarantine, deletion receipts, and audit verification in a short playable vault adventure | [Play or watch the Grok memory game](./examples/grok-memory-game/) |
| Run a private local assistant | A desktop-style dashboard combines local chat, searchable memory, approvals, files, and live audit verification | [Desktop guide](./docs/macos-desktop.md) |
| Stop webpages or tool output from silently becoming trusted memory | Classified untrusted content is quarantined and needs an explicit promotion step | [Audit and trust model](./docs/auditing-guide.md) |
| Recall relationships, not only matching text | An optional governed graph adds bounded multi-hop retrieval with visible path evidence and direct-record fallback | [Graph memory design](./docs/graph-memory-design.md) |
| Investigate what an agent knew and did | Retrievals, memory transitions, agent actions, approvals, and receipts can share a hash-chained timeline with independent verification | [Audit-log specification](./docs/audit-log-spec.md) |
| Honor correction and deletion requests | New values supersede recognized old facts; forgetting purges live content and produces a deletion receipt | [Auditing guide](./docs/auditing-guide.md) |
| Compare memory systems reproducibly | The repository includes unit gates, MemoryStackBench integration, and raw OpenClaw/DeepSeek token, cost, accuracy, and latency trials | [Benchmark evidence](./docs/openclaw-memory-evaluation.md) |

### Agent governance and operational use cases

| What you want | What AetnaMem provides | Read more |
|---|---|---|
| Require human approval before an agent changes something | Stage the exact operation, bind approval to its hash, recheck the target, execute, verify, and issue a receipt | [Guarded actions](./docs/guarded-actions.md) |
| Prevent “approved one thing, executed another” failures | Plan mutation, expired approval, changed world state, or adapter drift stops execution | [Flagship demo](./examples/flagship-demo/) |
| Handle crashes around external effects honestly | Interrupted calls are fenced as uncertain or recovery-required instead of being blindly retried | [Guarded actions](./docs/guarded-actions.md) |
| Join another agent runtime to the audit timeline | Import compatible operational journals as digest-only, explicitly unverified evidence without copying sensitive payloads | [Integration guide](./docs/integration-guide.md) |
| Build a governed tool gateway | Use the fail-closed MCP filter gate as a foundation for separating reads from direct writes | [Guarantees and roadmap](./TODO.md) |

### Evidence-to-Decision and organizational use cases

| What you want | What AetnaMem provides | Read more |
|---|---|---|
| Run a structured evidence-to-decision process | Versioned clinical and generic EtD templates turn evidence and contextual judgments into a recommendation | [EtD profile](./docs/etd-profile.md) |
| Let a panel collaborate and vote | Namespace-scoped cases, roles, conflicts of interest, recusal, frozen voter eligibility, hidden-until-close ballots, and deterministic outcomes | [Decision workflow](./docs/decision-workflow-spec.md) |
| Keep recommendation, approval, and authorization distinct | Panel adoption, institutional approval, resource sign-off, and change authorization are separate auditable transitions | [Decision workflow](./docs/decision-workflow-spec.md) |
| Connect an approved decision to implementation | A scoped authorization can be revalidated when an exact guarded action is staged and again before execution | [Decision host integration](./docs/decision-host-integration.md) |
| Host the workflow for many users | Embed the SDK behind your own authenticated application using SQLite for local/single-server work or PostgreSQL for multi-process deployment | [Host integration and deployment](./docs/decision-host-integration.md) |
| Produce verifiable governance evidence | Ed25519 or host-supplied KMS attestations sign identities and decision receipts; an offline verifier checks exported bundles | [Decision host integration](./docs/decision-host-integration.md) |
| Apply retention to sensitive decisions and conflicts | Decision and conflict-of-interest payloads can be logically purged under separate policies with signed purge receipts | [Decision workflow](./docs/decision-workflow-spec.md) |
| Prepare a hospital, policy team, or business unit pilot | A complete playground, acceptance protocol, evidence checklist, and independent methodology-review package are included | [Pilot and review runbook](./docs/etd-pilot-methodology-review.md) |

### Why this is more than another memory cache

Most agent-memory integrations are discussed primarily as chat history,
retrieval, or prompt caching. AetnaMem includes those practical concerns, but
its distinctive value is the chain around them: source provenance, trust and
quarantine, correction, deletion receipts, bounded context, independent audit
verification, human approval, and an optional evidence-to-approved-change
workflow. The same record can help an agent answer a question without being
mistaken for authority to take an action.

That combination is useful when “the model remembered something” is not a
sufficient operational explanation. It gives engineering teams a small local
starting point, while giving managers, reviewers, and regulated organizations
a path to inspect what informed a result and what was actually authorized.
The measured OpenClaw/DeepSeek experiment also shows the practical side:
cache-aware AetnaMem used **13.32% fewer prompt tokens and had 2.97% lower
provider-reported cost** than native `MEMORY.md`, with 20/20 answers in both
arms. This is one controlled benchmark, not a universal saving; the
[raw trials and limitations](./docs/openclaw-memory-evaluation.md) are
published for review.

The memory engine is usable today. The collaborative decision and EtD SDKs are
experimental and need a real organizational pilot and external methodology
review before clinical or regulatory claims. Multi-user products must also
supply authentication, authorization, UI, networking, and deployment controls.
See [guarantee boundaries](#guarantee-boundaries) for the exact division of
responsibility.

## Try the local assistant today

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
slice; the filter-only MCP gate is implemented, while automatic staging of
arbitrary upstream MCP writes, Telegram review, additional execution providers,
Firestore, and X adapters are tracked explicitly in the [roadmap](https://github.com/aetna000/aetnamem/blob/main/TODO.md).
Protocol and security details are in
[guarded-actions guide](https://github.com/aetna000/aetnamem/blob/main/docs/guarded-actions.md).

## Collaborative decisions and EtD

The optional `aetnamem.decisions` Python SDK adds namespace-scoped,
multi-principal decision cases, immutable evidence links, conflict/recusal
handling, ballots, deterministic outcomes, recommendation adoption,
institutional approvals, and scoped change authorization. `aetnamem.etd`
provides versioned clinical and generic Evidence-to-Decision templates plus
deterministic reporting.

```python
from aetnamem.decisions import ActorContext, DecisionEngine
from aetnamem.etd import clinical_etd_template

engine = DecisionEngine("organization.db")
chair = ActorContext("hospital-7", "principal-42")  # host-authenticated values
case = engine.create_case(
    chair,
    title="Medication reconciliation",
    template=clinical_etd_template(),
    content={"question": "Should we introduce pharmacist reconciliation?"},
    idempotency_key="request-001",
)
```

The host supplies authentication, users, UI, HTTP/TLS, notifications, and
organization-level authorization. The SDK enforces case membership, recusal,
idempotency, concurrency, exact revision binding, and audit transitions.
The standard installation includes both the SQLite and PostgreSQL backends plus
Ed25519 identity/receipt verification; the provider-neutral KMS adapter accepts
a host-supplied AWS KMS client. Decision and COI
payloads have independently configurable logical retention and signed purge
receipts. These features do not claim GRADE, clinical, or regulatory
compliance. Run `aetnamem-etd-playground` against SQLite or PostgreSQL and
verify its export with `aetnamem-etd-verify`.

See the [decision workflow specification](./docs/decision-workflow-spec.md),
[EtD profile](./docs/etd-profile.md), and
[host integration guide](./docs/decision-host-integration.md). Organizations
preparing real users should also use the [pilot and methodology-review
runbook](./docs/etd-pilot-methodology-review.md).

## Use from agents (MCP)

`aetnamem mcp` currently serves **memory verbs only** as MCP tools over stdio:
newline-delimited JSON-RPC implemented with the standard library only and does
not require an additional MCP framework. Defaults: database at
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
(bounded prompt-injection block), `memory_persona`, `memory_context_pack`
(host-neutral stable/dynamic context), `memory_capture`
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

Install the native four-memory integration:

```bash
python3 -m pip install --upgrade aetnamem
openclaw plugins install npm:openclaw-memory-aetnamem@latest --pin
aetnamem setup
openclaw aetnamem setup --single-user --subject you \
  --orchestrated --runtime-config ~/.aetnamem/runtime.json
```

The setup applies conservative context budgets and enables the required
conversation hooks. It does not rewrite `MEMORY.md`; verify recall before
removing duplicated native memory. One plugin instance currently has one fixed
subject and must not be shared between authenticated users.

By default, each prompt receives no more than three matching memories within a
1,200-character recall block plus a 600-character persona block, and unrelated
queries receive no recall block.

In the checked-in three-arm OpenClaw 2026.7.1-2 + DeepSeek V4 Flash follow-up,
20 fresh-session tasks per arm used **596,581 prompt tokens** with a
19,489-character native `MEMORY.md`, **521,858** with the current AetnaMem
layout, and **517,118** with cache-aware AetnaMem. The optimized arm therefore
used **79,463 fewer prompt tokens (13.320%)** and cost **2.968% less** than
native, with 20/20 correct answers in every arm and 20/20 target retrieval in
both AetnaMem arms. It did not increase absolute cache reads over current
AetnaMem; its additional 0.908% token and 1.190% cost improvement came from the
optimized bundle's smaller model-visible surface. An earlier run produced a
0.674% cost increase under a different cache mix, so neither bill is a
universal claim. The [raw trials, protocol, limitations, and reproduction command](./bench/openclaw_memory/)
are checked in; the plugin README also includes the two-minute recall demo.

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
first path for Hermes, Claude Desktop, Claude Code, and any framework that
can launch a stdio MCP server. The dedicated [Hermes guide](./docs/hermes-agent.md)
includes the exact commands and explains the boundary between tool-based
memory and automatic prompt injection.

For an automatic adapter, call one provider-neutral operation before the
model invocation:

```python
pack = memory.build_context_pack("user-42", current_query)
system_prefix += "\n" + pack["stable_context"]
current_turn += "\n" + pack["dynamic_context"]
```

The same contract is available as CLI `aetnamem context-pack` and MCP tool
`memory_context_pack`. The stable block is deterministic and suitable for a
stable system-prefix position; the dynamic block is selective and belongs
near the current turn. Records already present in the stable block are not
repeated in the dynamic block. This layout can preserve provider prefix-cache reuse
while keeping the total prompt bounded, but it cannot guarantee cache hits:
cache boundaries, minimum cacheable lengths, TTLs, and billing remain provider
and host behavior.

Build a native adapter only when the framework gives useful hooks:

| hook point | aetnamem call | purpose |
|---|---|---|
| before prompt/context build | `memory_prepare_turn` or legacy `memory_context_pack` | inject bounded, audited stable + dynamic context |
| after user/agent turn | `memory_record_outcome` plus `memory_capture` | close the learning loop and capture user facts |
| before history write | strip injected memory blocks | prevent recall feedback loops |
| explicit agent tools | `memory_recall`, `memory_forget`, `memory_audit`, `memory_verify` | search, request logical purge, and verify recorded behavior |

Native adapters should pass the host's `session_id` and `turn_id` whenever
available, so memory reads, writes, tool calls, forgets, and user-visible
responses line up in one audit timeline.

Priority targets:

| framework / host | first integration | native adapter shape |
|---|---|---|
| OpenClaw | implemented [native plugin](https://github.com/aetna000/aetnamem/tree/main/integrations/openclaw) | hook-based auto-recall/capture |
| Hermes | implemented [MCP setup guide](./docs/hermes-agent.md) | context-engine/plugin wrapper consuming `memory_context_pack` |
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

## Current semantic-memory storage pipeline

These L0–L3 labels describe the internal pipeline used by the semantic
provider. They are not alternatives to the four runtime memory types above.

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
count, score inputs, and a bounded ledger (the first 50 plus every returned
result). A versioned digest binds the selected retrieval fields to the audit
chain. Pass `min_score=` to drop weak matches.

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

## What v0.5 is and is not

Semantic extraction is deterministic (generic sentence patterns: "my X is Y",
"use Y as my X", "remember that …", "I avoid …") so that policy failures are
debuggable, not probabilistic. The embedded four-memory runtime, setup
presets, local Python API, CLI, MCP server,
deterministic consolidation, persona snapshots, scenes, checkpoints, and
independent memory verifier are implemented. An optional, deterministic graph
index provides bounded multi-hop recall with path evidence and direct-record
fallback. Guarded Actions additionally
ships an action ledger, exact-plan shared-key approvals, filesystem reference
adapter, recovery fencing, external journal import, and independent action
verifier. A fail-closed, filter-only MCP gate is implemented; automatic
conversion of arbitrary upstream writes into staged actions, authenticated
host identity, encrypted payloads, LLM-backed graph extraction, public HTTP
deployments, remote memory-plane transport, and additional
storage backends remain roadmap work — see the [roadmap](https://github.com/aetna000/aetnamem/blob/main/TODO.md).
The policy gates in [aetnamem/core/policy.py](https://github.com/aetna000/aetnamem/blob/main/aetnamem/core/policy.py) are
the product; nothing in the engine may reference the vocabulary of a
benchmark scenario.

## Documentation

- **[Current capability status](./docs/current-status.md)** — canonical
  implemented, experimental, public, and planned boundary.
- **[0.5.0 release notes](./docs/releases/v0.5.0.md)** — four-memory runtime,
  ten-step setup, presets, runtime MCP, OpenClaw 0.3.0, deletion, and benchmark.
- **[0.4.1 release notes](https://github.com/aetna000/aetnamem/blob/main/docs/releases/v0.4.1.md)** — provider-neutral
  cache-aware context packs, OpenClaw npm release, Hermes integration, measured
  token/cost results, and claims boundaries.
- **[0.4.0 release notes](https://github.com/aetna000/aetnamem/blob/main/docs/releases/v0.4.0.md)** — evidence-to-approved-change capabilities,
  installation, validation, and claims boundary.
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
- **[Hermes Agent guide](https://github.com/aetna000/aetnamem/blob/main/docs/hermes-agent.md)** — MCP setup,
  tool-based memory, automatic context-pack integration, caching expectations,
  and multi-user boundaries.
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
- **[Collaborative decision workflow](https://github.com/aetna000/aetnamem/blob/main/docs/decision-workflow-spec.md)** — generic
  cases, revisions, evidence lineage, ballots, adoption, authorization,
  concurrency, receipts, and trust boundaries.
- **[Evidence-to-Decision profile](https://github.com/aetna000/aetnamem/blob/main/docs/etd-profile.md)** — versioned EtD criteria,
  artifact chain, report surface, and methodology boundary.
- **[Decision host integration](https://github.com/aetna000/aetnamem/blob/main/docs/decision-host-integration.md)** — authenticated-host contract,
  namespace derivation, SQLite/PostgreSQL deployment, signed identity,
  retention, and approved-change bridge.
- **[EtD pilot and methodology review](https://github.com/aetna000/aetnamem/blob/main/docs/etd-pilot-methodology-review.md)** — production entry criteria,
  multi-user test protocol, acceptance evidence, and independent-review package.
- **[Channels and governed outbound proposal](https://github.com/aetna000/aetnamem/blob/main/docs/channels-outbound-spec.md)** — provider-neutral
  intake, optional business review, and evidence-bound external adapters;
  proposed, not implemented.
- **[Inference engineering memory proposal](https://github.com/aetna000/aetnamem/blob/main/docs/inference-engineering-spec.md)** — provider-neutral local and
  Hugging Face inference, governed run evidence, strict comparison, engineering
  decisions, deployment receipts, and incident reconstruction; proposed, not
  implemented.
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
