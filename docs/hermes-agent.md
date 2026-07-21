# Hermes Agent integration

AetnaMem integrates with Hermes through MCP today and through one
provider-neutral context-pack contract when automatic pre-prompt injection is
available. The memory engine does not import Hermes, OpenClaw, DeepSeek,
Claude, Grok, or any model SDK.

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

