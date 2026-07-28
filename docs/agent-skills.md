# AetnaMem agent skills

> Skills tell the agent how to use memory. AetnaMem proves what actually
> happened.

AetnaMem packages its user-facing memory workflows as three focused agent
skills. The skills make governed memory conversational, while the installed
Python engine remains the trusted execution and evidence boundary.

## Install

Install the released engine:

```bash
python3 -m pip install --upgrade aetnamem
```

Install all three skills with a compatible Skills CLI:

```bash
npx skills add aetna000/aetnamem
```

The repository also contains `.codex-plugin/plugin.json` and
`.claude-plugin/plugin.json` for provider-native packaging. The skill wrappers
require `aetnamem` on `PATH`; when it is unavailable they try the current
Python interpreter with `python -m aetnamem.cli`.

## Included skills

### `use-governed-memory`

Use it when the user asks to remember, find, correct, promote, or delete
memory.

```text
User: Remember that production reports must be Markdown.

Agent:
- submits the authenticated statement through AetnaMem;
- reports the created record ID and status;
- verifies the audit chain;
- does not claim success if no record was admitted.
```

External content must keep its actual source classification. Webpages and tool
outputs enter quarantine; a model confidence score must never promote them.

### `audit-agent-memory`

Use it when an auditor has a clue but no record ID:

```text
User: Why did the agent say production reports must be Markdown?

Agent:
- verifies the subject's audit chain;
- searches by ordinary language;
- follows the matching record's chronological trace;
- separates stored evidence from inference;
- optionally exports the complete JSON report.
```

Investigator searches append a digest-only access event with the supplied actor
identity. An authenticated host should supply verified identity instead of a
free-form actor.

### `trial-agent-memory`

Use it to evaluate AetnaMem beside OpenClaw or Hermes:

```text
capture → human review → preview → limited canary → active
                                      │
                                      └── off or rollback
```

Capture and preview do not change model context. Canary and active do.
Activation is not evidence that answers improved; measure outcomes and costs
separately.

## Deterministic wrappers

Each skill contains a small Python wrapper. Wrappers call only public
`aetnamem` commands and never edit SQLite, vector indexes, or audit files
directly.

Remember and verify:

```bash
python skills/use-governed-memory/scripts/governed_memory.py \
  --db ~/.aetnamem/memories.db \
  --subject user-1 \
  remember "My preferred report format is Markdown."
```

Search and export an audited trace:

```bash
python skills/audit-agent-memory/scripts/audit_memory.py \
  --db ~/.aetnamem/memories.db \
  --subject user-1 \
  --actor auditor@example.com \
  trace "report format" \
  --output report-format-trace.json
```

Start a reversible host trial:

```bash
python skills/trial-agent-memory/scripts/trial_memory.py start --host auto
```

Promotion, candidate review, canary, activation, rollback, and deletion require
an explicit `--confirm` in the wrappers.

## Security and evidence boundary

A skill is model-controlled procedural guidance. It may not trigger and cannot
intercept every turn. Therefore the skill does not own:

- automatic host capture or prompt injection;
- authenticated subject identity;
- admission, quarantine, or promotion policy;
- canonical records or indexes;
- hash-chained audit events;
- deletion coverage or receipts;
- Safe Switch state enforcement.

Those remain engine or authenticated-host responsibilities. Without an
OpenClaw, Hermes, or equivalent adapter, AetnaMem can prove only the operations
that actually passed through its CLI, Python API, or MCP tools.

## What an agent may claim

| Evidence | Supported statement |
|---|---|
| Created record plus valid chain | “AetnaMem admitted this record with this status.” |
| Quarantined record | “AetnaMem stored this for review; it is not trusted memory.” |
| Verified chronological trace | “These recorded events link the source, record, retrieval, and outcome.” |
| Deletion receipt | “AetnaMem purged the objects listed in this receipt.” |
| Safe Switch preview | “This is the context AetnaMem would supply.” |

None of these alone supports “this memory caused the answer to improve.”
Causal claims require a registered Memory Impact experiment with randomized
intervention and independently verified outcomes.

## Validate the packaged skills

From a source checkout:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/use-governed-memory
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/audit-agent-memory
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/trial-agent-memory
```

Run the repository test suite to exercise the wrappers against temporary
databases:

```bash
python3 -m pytest
```
