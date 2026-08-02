# AetnaMem

[![Version 1.0.0a2](https://img.shields.io/badge/version-1.0.0a2--experimental-orange)](./docs/releases/v1.0.0a2.md)
[![CI](https://github.com/aetna000/aetnamem/actions/workflows/ci.yml/badge.svg)](https://github.com/aetna000/aetnamem/actions/workflows/ci.yml)

**AetnaMem is a model-agnostic memory control plane for agents. Its complete reversible memory switch is currently OpenClaw-specific.**

Install AetnaMem beside OpenClaw, let it copy and shadow the complete native memory, inspect the result, then activate it when you are ready. Shadow mode does not change the context sent to the model. Activation freezes the verified OpenClaw memory state and replaces native supplemental-memory access with bounded AetnaMem recall. Restore puts the saved OpenClaw configuration and memory paths back.

This is **Version 1.0.0a2**, an experimental prerelease. The memory engine and MCP interface are model-agnostic. The automated copy, shadow, activation, and restore workflow supports OpenClaw first.

## Install and migrate OpenClaw

```bash
# 1. Install the engine. Do not install the npm bridge separately.
python -m pip install --pre aetnamem==1.0.0a2
aetnamem --version

# 2. Install the matching bridge and copy all existing OpenClaw memory.
aetnamem openclaw install

# 3. Inspect the shadow copy. OpenClaw is still the memory provider.
aetnamem control status
aetnamem dashboard daemon start

# 4. Switch only after the dashboard reports that the copy is verified.
aetnamem control activate

# 5. Restore OpenClaw memory at any time.
aetnamem control restore
```

`aetnamem openclaw install` owns both packages: it installs the matching npm bridge, binds the exact Python executable, copies `MEMORY.md` and `memory/*.md` from the beginning of the OpenClaw workspace history, starts change mirroring, restarts the gateway, and verifies the loaded integration. Progress is shown for every stage. If verification fails, it restores the prior plugin configuration.

Read the [OpenClaw setup](docs/openclaw-setup.md) and [control-plane guarantees](docs/control-plane.md) before customer deployment.

## What the dashboard provides

The loopback-only dashboard is the operating and investigation surface:

- current provider: OpenClaw in shadow mode or AetnaMem in active mode;
- copy progress, source manifest, hashes, and verification failures;
- memory search, record history, source and interpretation evidence;
- recall scores, context-injection receipts, and agent-response bindings;
- approval or purge of quarantined external observations;
- filtered audit exploration with time, event, actor, session, record, and status facets;
- JSON, NDJSON, CSV, text investigation reports, and deletion receipts;
- one activation control and one restore control.

```bash
aetnamem dashboard daemon start   # background service at http://127.0.0.1:8766/
aetnamem dashboard daemon open    # open the direct loopback URL
aetnamem dashboard daemon status
aetnamem dashboard daemon restart
aetnamem dashboard daemon stop
aetnamem dashboard daemon remove  # removes service metadata, not memory/evidence
```

## Model-agnostic engine

Any host that can launch a stdio MCP server can use the engine directly:

```bash
aetnamem mcp --db ~/.aetnamem/memories.db --subject local-user
```

MCP tools: `memory_remember`, `memory_observe`, `memory_recall`, `memory_get_record`, `memory_get_source`, `memory_recall_block`, `memory_persona`, `memory_context_pack`, `memory_capture`, `memory_list`, `memory_forget`, `memory_forget_artifact`, `memory_promote`, `memory_audit`, `memory_verify`, `memory_graph_status`, `memory_graph_merges`, `memory_graph_history`, and `memory_log_action`.

The protocol does not depend on OpenAI, Anthropic, Google, Meta, xAI, DeepSeek, or another model provider. A host integration is still responsible for authenticated user identity, deciding when model-interpreted statements become memory, and proving which context reached which response.

See the [integration guide](docs/integration-guide.md), [audit search](docs/audit-search.md), [semantic search](docs/semantic-search.md), and [multimodal observations](docs/multimodal-observations.md).

## Data and trust boundaries

- Canonical memory, provenance, lifecycle state, and audit evidence are stored in SQLite.
- Semantic search is optional. Vectors are a derived index and are verified against canonical records before results are returned.
- External media bytes remain host-controlled. AetnaMem stores a typed text observation, exact byte-stream SHA-256, model identity, and host reference.
- External observations are quarantined until approved. Confidence is evidence, never an automatic promotion rule.
- Forget operations cascade through canonical, graph, media, and vector-derived state and return a receipt.
- The dashboard binds only to loopback and opens without a login. Mutations retain CSRF and origin checks.

See [data storage and backup](docs/data-storage-and-backup.md) and the [auditing guide](docs/auditing-guide.md).

## Scope

AetnaMem 1.0 contains one product: the memory control plane. Unrelated legacy experiments remain in Git history and on the unchanged `develop` branch; they are not shipped as part of the 1.0 product.

Licensed under [AGPL-3.0-only](LICENSE).
