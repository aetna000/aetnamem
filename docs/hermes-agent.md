# Hermes Agent integration

AetnaMem stable 0.6.1 supports two distinct Hermes paths:

- generic MCP memory tools; and
- a Safe Switch beta general plugin for capture, preview, canary and active
  context.

The memory engine does not import a model SDK.

## Safe Switch beta

Safe Switch is the shortest path for a local user who wants to inspect
AetnaMem before it changes a Hermes prompt:

```bash
python3 -m pip install --upgrade aetnamem
aetnamem trial start --host hermes
# Restart Hermes once so it discovers the installed general plugin.
aetnamem dashboard
```

The installer writes `~/.hermes/plugins/aetnamem-safe-switch/` and saves any
existing directory to the private trial backup first. The installed loader is
standard-library-only and communicates with `aetnamem trial mcp` over stdio,
so Hermes and AetnaMem may live in different Python environments.

This is deliberately a **general plugin**, not a memory-provider plugin. It
can coexist with the current Hermes memory provider. `pre_llm_call` returns no
context in capture/preview and returns approved context only in canary/active;
`post_llm_call` confirms exposures and captures the authenticated user turn.
It registers no model-callable AetnaMem tool.

See [Safe Switch](safe-switch.md) for mode, evidence and rollback boundaries.

## Tool-based setup

Install AetnaMem in the environment Hermes can execute, register the local
stdio server, and test it:

```bash
python3 -m pip install --upgrade aetnamem
hermes mcp add aetnamem --command aetnamem --args mcp --db ~/.aetnamem/hermes.db --subject you
hermes mcp test aetnamem
```

Hermes also accepts MCP server configuration in `config.yaml`:

```yaml
mcp_servers:
  aetnamem:
    command: aetnamem
    args:
      - mcp
      - --db
      - /home/you/.aetnamem/hermes.db
      - --subject
      - you
```

Hermes discovers the `memory_*` tools and can remember, recall, forget, and
verify without a native dependency. This tool setup does **not** automatically
inject memory into every model call: the agent must choose to call the tools.
Hermes also has a built-in memory tool, so configure an explicit policy or
tool filter to avoid storing the same fact in two memory systems.

With Python `v0.5.2`, a multimodal Hermes workflow can also call
`memory_observe` after its model analyzes an image, audio clip, video, or
document. The tool stores the resulting text as quarantined memory with the
exact-byte SHA-256, host reference, segment, and extractor identity. It does
not store the media. `memory_forget_artifact` deletes every indexed AetnaMem
derivative of that digest but not the host's original file. See the
[multimodal observation guide](multimodal-observations.md).

Hermes MCP command and configuration shapes are documented in the official
[CLI reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/cli-commands.md),
[MCP guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md),
and [MCP configuration reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/mcp-config-reference.md).

## Automatic cache-aware integration

A Hermes context-engine or plugin wrapper should invoke MCP
`memory_context_pack` immediately before the model call. An embedded Python
host can call the same operation directly:

```python
from aetnamem import Memory

memory = Memory("hermes.db")
pack = memory.build_context_pack(
    "user-42",
    current_user_text,
    session_id=session_id,
    persona_max_chars=600,
    recall_max_records=3,
    recall_max_chars=1200,
)

# Host-owned prompt assembly:
system_prefix = base_system_prompt + "\n" + pack["stable_context"]
current_turn = current_user_text + "\n" + pack["dynamic_context"]
```

The wrapper must keep these roles distinct:

- `stable_context`: deterministic persona material in a stable system-prefix
  position; do not append timestamps or request IDs around it.
- `dynamic_context`: query-specific recall close to the current turn; do not
  allow it to move or invalidate the stable prefix.
- captured history: strip `<user_persona>` and `<relevant_memories>` before
  writing conversation history, preventing feedback loops.
- user turns: pass only trusted user statements to `memory_capture`; tool and
  assistant content is digest-only unless explicitly promoted through the
  trust flow.

The returned full record IDs and SHA-256 values bind both blocks to the audit
chain. Compact model-visible references save tokens without weakening the
audit evidence.

## What to expect

The contract reduces repeated prompt material only when the host actually
places stable and dynamic blocks as directed. Provider cache eligibility,
minimum prefix length, expiration, and pricing are outside AetnaMem's control.
The checked-in OpenClaw/DeepSeek experiment validates bounded prompt reduction,
not a universal Hermes saving: Hermes needs its own paired benchmark before a
percentage claim is made.

For a multi-user Hermes service, never let the model choose `subject_id`.
Authenticate the user in the host, derive the subject server-side, and apply
storage/database authorization there. `--subject` is convenient single-user
scoping, not authentication.
