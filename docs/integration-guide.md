# Integration guide

AetnaMem separates the model-agnostic memory engine from host-specific control adapters.

## Python

```python
from aetnamem import Memory

memory = Memory("memories.db")
memory.remember("user-1", "My preferred editor is Vim.", session_id="s1")
records = memory.recall("user-1", "preferred editor", limit=5)
report = memory.audit("user-1")
memory.close()
```

The embedding provider is optional. The canonical database remains usable without it.

## MCP

```bash
aetnamem mcp --db ~/.aetnamem/memories.db --subject user-1
```

| Tool | Purpose |
| --- | --- |
| `memory_remember` | Admit authenticated text through policy and provenance checks. |
| `memory_observe` | Admit a typed, quarantined text observation of host-controlled media. |
| `memory_recall` | Return bounded active memories for a query. |
| `memory_get_record` | Read one canonical record by ID. |
| `memory_get_source` | Read the source episode associated with a record. |
| `memory_recall_block` | Render bounded recall for direct context injection. |
| `memory_persona` | Render a bounded subject persona. |
| `memory_context_pack` | Render a cache-aware persona and recall context pack. |
| `memory_capture` | Record an interpreted memory and bind it to source evidence. |
| `memory_list` | List canonical memories and lifecycle status. |
| `memory_forget` | Delete matching memory and return a receipt. |
| `memory_forget_artifact` | Delete all memory derived from one exact media byte-stream digest. |
| `memory_promote` | Approve a quarantined memory for recall. |
| `memory_audit` | Read the evidence timeline for a subject. |
| `memory_verify` | Verify audit and storage integrity. |
| `memory_graph_status` | Inspect the derived graph index. |
| `memory_graph_merges` | List reviewer-gated graph merge proposals. |
| `memory_graph_history` | Inspect graph entity and merge history. |
| `memory_log_action` | Bind a host action or response digest to the audit timeline. |

An MCP connection alone does not authenticate the user or prove that returned context reached the model. The host must supply authenticated identity and bind actual context delivery and response evidence.

## OpenClaw control adapter

```bash
aetnamem openclaw install
aetnamem control status
aetnamem control activate
aetnamem control restore
```

The OpenClaw adapter provides the host-specific parts that generic MCP cannot: complete native-memory discovery, historical copy, ongoing shadow synchronization, prompt and response binding, semantic model interpretation, native-path protection, gateway verification, and exact restore.

## Building another host adapter

A complete adapter must implement:

1. authenticated user and session identity;
2. enumeration and verified copy of all existing host memory;
3. shadow synchronization without changing model context;
4. model-semantic capture of user intent rather than transcript keyword scraping;
5. bounded recall and proof of actual context injection;
6. response/tool receipt binding;
7. atomic activation with capability checks;
8. restore material captured before mutation;
9. verified restore, including handling divergent files or state;
10. honest reporting of any evidence the host cannot expose.

Until an adapter meets those requirements, describe the integration as use of the model-agnostic engine—not as a complete reversible memory switch.
