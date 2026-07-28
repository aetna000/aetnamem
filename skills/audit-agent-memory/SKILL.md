---
name: audit-agent-memory
description: Search agent memory by ordinary language, reconstruct chronological provenance, verify AetnaMem audit chains, and export investigation results as JSON. Use when a user or auditor asks what the agent remembers, why a memory exists, where it came from, whether it was recalled or changed, who searched it, whether deletion occurred, or requests a portable evidence report without knowing an internal memory ID.
---

# Audit agent memory

Begin with a clue, not an internal ID. Verify the subject's audit chain before
presenting a search or trace, and label the difference between stored evidence
and an inference.

## Required workflow

1. Resolve the database, authenticated subject, and investigator identity.
2. Use `scripts/audit_memory.py`; it verifies before searching and records a
   digest-only investigator-access event.
3. Start with `search` to find likely memories, episodes, events, or runs.
4. Use `trace` on the best clue or record ID to reconstruct the chronological
   story.
5. Report chain validity, exact event types, record status, source type, and
   relevant IDs. Do not convert temporal proximity into a causal claim.
6. When an export is requested, use `--output report.json` and return its path.

## Common operations

```bash
python scripts/audit_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 --actor auditor@example.com \
  search "production deployment"

python scripts/audit_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 --actor auditor@example.com \
  trace --record rec_123 --output trace.json

python scripts/audit_memory.py \
  --db ~/.aetnamem/memories.db --subject user-1 --actor auditor@example.com \
  verify
```

Use lexical search by default. Use semantic or hybrid search only when a
compatible, verified semantic index already exists. Read
`references/evidence-interpretation.md` before making conclusions about
retrieval influence, deletion, or semantic similarity.

## Non-negotiables

- Never bypass subject scoping.
- Never suppress an invalid verification result.
- Never state that a retrieved memory caused an outcome merely because both
  appear in the same trace.
- Never claim that a semantic match is an exact textual match.
- Never claim deletion outside the scope printed in the deletion receipt.
- Audit queries reveal sensitive information; return only what the requester is
  authorized to inspect.
