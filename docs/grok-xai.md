# Grok/xAI integration

Status: **implemented tool-calling integration; corrected 100-run exploratory
Memory Impact pilot complete; no general causal claim**

`aetnamem` works with Grok through xAI tool calling today: Grok chooses a
memory tool, your app executes it locally against `aetnamem`, and the result
goes back to Grok. The core memory engine stays unchanged, so provenance,
quarantine, deletion receipts, and independent audit verification remain the
same.

Relevant xAI docs:

- [Function Calling](https://docs.x.ai/developers/tools/function-calling)
- [Remote MCP Tools](https://docs.x.ai/developers/tools/remote-mcp)

## What this integration demonstrates

The demo exposes four tools to Grok:

| Grok tool | aetnamem call | audit behavior |
|---|---|---|
| `aetnamem_capture` | `Memory.capture(..., role="user")` | user facts run the full write pipeline |
| `aetnamem_search` | `Memory.recall()` | retrieval event logs ranked candidates and returned IDs |
| `aetnamem_forget` | `Memory.forget()` | live memory content is logically purged and a deletion receipt is returned |
| `aetnamem_audit` | `Memory.audit()` | chain validity and event counts are visible |

This is intentionally not a separate Grok memory backend. It is Grok using
`aetnamem` as an auditable external tool layer.

The playground and memory game demonstrate integration behavior. They are not
evidence that memory causally improved Grok. Version 0.6.0 implements the
separate registered Memory Impact controller, balanced task suite, hidden host
verification and held-out policy gate. A corrected paid pilot completed 100
registered calls with 57 verified successes and six complete balanced blocks.
The all-four arm was 6/6 and no-memory was 1/6. The schedule was deliberately
capped, no held-out policy was tested, and this does not prove general agent
improvement. See the [Memory Impact guide](memory-impact.md),
[100-run pilot evidence summary](../bench/causal_memory/reports/grok-4.5-100-run-pilot-2026-07-26.md),
[current status](current-status.md), and [`plan.md`](../plan.md).

## Configure Grok CLI in four steps

Install AetnaMem and create a balanced local four-memory configuration:

```bash
python3 -m pip install --upgrade aetnamem
aetnamem setup --yes --preset starter --subject you \
  --agent grok-primary --skill-path ~/.grok/skills
```

Connect that runtime to Grok as a local MCP server:

```bash
grok mcp add --scope user aetnamem -- \
  aetnamem runtime mcp --config ~/.aetnamem/runtime.json
grok mcp doctor
```

The `starter` preset enables bounded working, semantic, episodic and procedural
contributions. It keeps experimental withholding off. Ask Grok to call
`memory_prepare_turn` before tasks that depend on preferences, prior attempts,
current progress or skills, and to call `memory_record_outcome` after the host
has determined success or failure. The outcome supplied through ordinary MCP
is honestly labeled `caller_asserted`; only a separately trusted verifier can
create `host_attested` evidence.

This setup can improve the context available to Grok; it is not a performance
guarantee. Use `private` for a smaller context budget, `team` for a trusted
multi-agent host, or the registered `aetnamem impact` workflow when you want
to measure improvement rather than assume it.

## xAI API playground

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
