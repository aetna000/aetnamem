# Current product status

Version 1.0.0a2 is an experimental prerelease of one product: the AetnaMem memory control plane.

| Capability | Status |
| --- | --- |
| SQLite memory engine, provenance and hash-chained audit | Implemented |
| Lexical, graph and optional semantic search | Implemented |
| Typed text observations of host-controlled media | Implemented |
| MCP interface | Model-agnostic |
| Dashboard search, review, audit exploration and exports | Implemented, loopback only |
| Complete native-memory copy and ongoing shadow for OpenClaw | Experimental |
| Verified activation and restore for OpenClaw | Experimental |
| Complete reversible switch for other agent hosts | Not yet implemented |

The exact product boundary is: **AetnaMem’s memory engine is model-agnostic, but its complete reversible memory switch is currently OpenClaw-specific.**
