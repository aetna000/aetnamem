# OpenClaw memory control plane

AetnaMem uses two customer-visible modes.

| Mode | Memory provider | What changes |
| --- | --- | --- |
| Shadow | OpenClaw | AetnaMem copies, mirrors, verifies, indexes and audits native memory. It does not inject model context. |
| Active | AetnaMem | Native supplemental memory is frozen; OpenClaw uses AetnaMem search, get, semantic capture and bounded recall. |

## Guarantees

Before activation, AetnaMem:

1. discovers the OpenClaw workspace;
2. copies `MEMORY.md` and every `memory/*.md` file, including history created before AetnaMem was installed;
3. records source path, line range, content digest and snapshot digest;
4. imports the material into an isolated SQLite mirror;
5. verifies the audit chain and complete source manifest;
6. synchronizes files that change during shadow mode;
7. snapshots the plugin configuration needed for restore.

Activation runs a final synchronization, checks the loaded plugin and required tools, protects the frozen native-memory paths, and changes the provider only if every check succeeds. Interrupted activation is detected and must be recovered or restored; it is not silently treated as complete.

Restore exports active-period AetnaMem memories, preserves unexpected divergent native files as evidence, restores the saved native paths and plugin configuration, restarts OpenClaw, and verifies the gateway. Past responses and provider logs cannot be undone. Control-plane evidence is intentionally preserved.

## Commands

```bash
aetnamem openclaw install
aetnamem control status
aetnamem control activate
aetnamem control restore
aetnamem openclaw memory status
aetnamem openclaw memory sync
aetnamem openclaw memory search "preferred editor"
aetnamem openclaw memory trace "preferred editor"
```

Use `--json` where offered for automation. Human-readable output is the default.

## Honest boundary

The engine and MCP protocol are model-agnostic. The filesystem discovery, native-memory snapshot, OpenClaw plugin configuration, gateway checks, path guard, and restore adapter are OpenClaw-specific. Other agent hosts need an adapter with equivalent capture, injection, proof, and restore hooks before AetnaMem can claim a complete switch for them.
