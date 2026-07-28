# Hermes Safe Switch adapter

This is a Hermes **general plugin**, not a memory-provider replacement. That
distinction lets AetnaMem observe beside the user's current Hermes memory in
`capture` and `preview` modes.

The plugin registers two turn hooks plus one subprocess-cleanup hook:

- `pre_llm_call` builds a preview and returns context only in `canary` or
  `active` mode.
- `post_llm_call` confirms any exposure and captures candidate facts from the
  authenticated user message.
- `on_session_finalize` closes the private AetnaMem subprocess.

It registers no agent-callable tool. Approval and mode changes remain in the
local `aetnamem trial` CLI or dashboard.

The supported installer is:

```bash
aetnamem trial start --host hermes
```

It installs a self-contained standard-library loader that starts the private
`aetnamem trial mcp` subprocess. This works when Hermes and AetnaMem are in
different Python environments. Restart Hermes after first installation.

The hook shape follows Hermes' documented `pre_llm_call` `{"context": str}`
contract. A missing or corrupt AetnaMem state returns no context.
