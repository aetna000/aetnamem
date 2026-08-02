# Audit search and investigation

An investigator does not need a memory ID to begin.

```bash
aetnamem search memories.db "preferred airport" --subject user-1
aetnamem trace memories.db "preferred airport" --subject user-1
aetnamem trace memories.db --record rec_123 --subject user-1
```

Search covers canonical memories, media observations, source episodes, retrievals and audit events. Filters include status, session, event type, actor and time range. Semantic or hybrid mode can find paraphrases when a verified semantic index is configured.

```bash
aetnamem search memories.db "travel preference" --subject user-1 \
  --mode hybrid --since 2026-08-01 --format json --output investigation.json
```

The dashboard adds compound filters, histogram, pivots, cursor pagination, saved local views and JSON, NDJSON, CSV or text export. Clicking a record reconstructs the available chain:

```text
source → interpretation → admission → recall → context injection → response
```

Each step is shown only when evidence exists. Historic imports may say `not recorded`; the UI must not manufacture provenance.

Investigator access logging is optional. `--access-actor` is caller-supplied metadata, not authentication; a deployment must authenticate the investigator before passing it.
