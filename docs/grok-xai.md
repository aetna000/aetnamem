# Grok/xAI integration

`aetnamem` works with Grok through xAI tool calling today: Grok chooses a
memory tool, your app executes it locally against `aetnamem`, and the result
goes back to Grok. The core memory engine stays unchanged, so provenance,
quarantine, deletion receipts, and independent audit verification remain the
same.

Relevant xAI docs:

- [Function Calling](https://docs.x.ai/developers/tools/function-calling)
- [Remote MCP Tools](https://docs.x.ai/developers/tools/remote-mcp)

## What this integration proves

The demo exposes four tools to Grok:

| Grok tool | aetnamem call | audit behavior |
|---|---|---|
| `aetnamem_capture` | `Memory.capture(..., role="user")` | user facts run the full write pipeline |
| `aetnamem_search` | `Memory.recall()` | retrieval event logs ranked candidates and returned IDs |
| `aetnamem_forget` | `Memory.forget()` | content is purged and a deletion receipt is returned |
| `aetnamem_audit` | `Memory.audit()` | chain validity and event counts are visible |

This is intentionally not a separate Grok memory backend. It is Grok using
`aetnamem` as an auditable external tool layer.

## Local playground

From a checkout:

```bash
pip install -e .
export XAI_API_KEY=...
python examples/grok_tool_playground.py
```

The default prompt asks Grok to:

1. remember a preference;
2. recall it;
3. forget it;
4. explain what the deletion receipt proves.

Use your own prompt:

```bash
python examples/grok_tool_playground.py \
  --prompt "Remember that I prefer morning meetings. What should you remember? Now forget my meeting preference."
```

Use an explicit database and subject:

```bash
python examples/grok_tool_playground.py \
  --db ~/.aetnamem/grok-demo.db \
  --subject you
```

Run the memory side without calling xAI:

```bash
python examples/grok_tool_playground.py --dry-run
```

Useful environment variables:

| variable | default |
|---|---|
| `XAI_API_KEY` | required unless `--dry-run` |
| `AETNAMEM_GROK_MODEL` | `grok-4.5` |
| `AETNAMEM_GROK_DB` | `~/.aetnamem/grok-playground.db` |
| `AETNAMEM_GROK_SUBJECT` | `grok-demo` |

## Remote MCP path

xAI also supports Remote MCP tools. That path is for a deployed MCP server
with a URL. `aetnamem mcp` is currently a local stdio MCP server, which is
ideal for local agents and desktop hosts. To use xAI Remote MCP, deploy an
HTTP/SSE MCP gateway in front of the same engine, then configure Grok with a
tool like:

```json
{
  "type": "mcp",
  "server_url": "https://your-domain.example/mcp",
  "server_label": "aetnamem",
  "allowed_tools": [
    "memory_recall",
    "memory_recall_block",
    "memory_capture",
    "memory_forget",
    "memory_audit",
    "memory_verify"
  ]
}
```

Use `allowed_tools` deliberately. For a first public demo, expose only
`memory_recall`, `memory_forget`, `memory_audit`, and `memory_verify`; add
write tools after auth, rate limits, and audit anchoring are in place.

## How to describe it on X

Short version:

> Grok-ready via xAI tool calling today: memory search, capture, forget, and
> audit are exposed as tools while `aetnamem` keeps provenance, quarantine,
> deletion receipts, and a verifiable audit chain.

Careful version:

> `aetnamem` integrates with Grok through xAI function calling today. Remote
> MCP is the deployment path once the local MCP server is exposed behind an
> HTTP/SSE gateway.

Do not claim native Grok app integration unless a dedicated Grok app/plugin
surface is built. The accurate claim is tool-calling integration now, Remote
MCP deployment next.
