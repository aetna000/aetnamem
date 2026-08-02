# Audit log format

AetnaMem appends canonical events to a per-subject SHA-256 chain. Every row binds the event identity, subject, type, actor, timestamp, canonical payload, previous hash and current hash.

Representative event families are `episode.*`, `memory.*`, `media.*`, `graph.*`, `retrieval.*`, `context.*`, and `agent.*`. The payload is event-specific but always canonicalized before hashing.

Chain verification proves internal ordering and detects mutation or deletion inside the retained chain. It does not prove authorship, trustworthy wall-clock time, or that an external system performed an action. Those claims require authenticated host receipts or an external timestamp/transparency system.

The independent verifier can check a copied database without importing AetnaMem:

```bash
python tools/verify_audit.py memories.db --subject user-1
```

Deletion receipts identify the requested boundary, affected objects, verification result and anything explicitly outside AetnaMem control.
