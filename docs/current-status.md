# Current product status

Version 1.0.0a5 is an experimental prerelease of the AetnaMem Agent Black Box and memory control plane.

| Capability | Status |
| --- | --- |
| SQLite memory engine, provenance and hash-chained audit | Implemented |
| Lexical, graph and optional semantic search | Implemented |
| Typed text observations of host-controlled media | Implemented |
| MCP interface | Model-agnostic |
| Dashboard search, review, audit exploration and exports | Implemented, loopback only |
| Content-minimizing Agent Black Box flight records | Experimental, OpenClaw hooks |
| Timeline integrity and observed tool-hook closure verification | Experimental |
| Semantic claim validation or external outcome proof | Not implemented |
| Complete native-memory copy and ongoing shadow for OpenClaw | Experimental |
| Verified activation and restore for OpenClaw | Experimental |
| Complete reversible switch for other agent hosts | Not yet implemented |

The exact product boundary is: **AetnaMem’s memory engine is model-agnostic, but Agent Black Box capture and the complete reversible memory switch are currently OpenClaw-specific.**
