---
name: use-governed-memory
description: Remember, find, correct, promote, and verifiably delete agent memory through the local AetnaMem evidence engine. Use when a user asks an agent to remember a fact or preference, inspect stored memories, correct an existing fact, approve quarantined external content, forget information, or prove that a memory mutation was recorded. Do not use for passive capture of every conversation turn; that requires a host integration.
---

# Use governed memory

Use AetnaMem as the system of record. Never edit its SQLite database, semantic
index, or audit events directly. The skill is the workflow; the installed
`aetnamem` engine enforces policy and preserves evidence.

## Required workflow

1. Resolve the database path and the subject whose memories are being changed.
   Never invent a tenant or subject identity.
2. Classify the source:
   - authenticated user statement: `user_message`;
   - webpage or retrieved content: `webpage`;
   - tool or agent output: `tool_output`.
3. Run `scripts/governed_memory.py` from this skill. It calls only public
   AetnaMem CLI commands and verifies the audit chain after mutations.
4. Inspect the returned `status`, record IDs, and `verification.valid`.
5. Report what AetnaMem actually admitted. Do not say “remembered” when no
   record was created or when the record remains quarantined.

## Common operations

```bash
python scripts/governed_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 \
  remember "My preferred report format is Markdown."

python scripts/governed_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 \
  find "report format"

python scripts/governed_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 list
```

Treat correction as a new authenticated statement. AetnaMem decides whether it
supersedes an older fact and preserves both the new record and the history.

Promotion changes the trust state. Perform it only after explicit user or
authorized reviewer approval:

```bash
python scripts/governed_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 \
  promote rec_123 --confirm
```

Deletion is destructive and also requires explicit confirmation:

```bash
python scripts/governed_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 \
  forget --contains "backup email" --confirm
```

For typed media observations or advanced semantic-index configuration, read
`references/trust-boundaries.md` and use the public AetnaMem CLI rather than
adding unvalidated fields to this wrapper.

## Non-negotiables

- Never turn external content into `user_message`.
- Never promote based only on model confidence.
- Never claim that AetnaMem deleted a host-controlled file.
- Never expose a different subject's records.
- Never hide quarantined, superseded, or tombstoned status.
- Report record IDs and verification results for every mutation.
