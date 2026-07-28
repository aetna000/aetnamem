# Governed-memory trust boundaries

## Skill versus engine

The skill tells an agent which public operation to use. It is not an
authorization boundary and it is not an always-on monitor. AetnaMem's Python
engine owns admission policy, storage, provenance, audit events, correction,
and deletion receipts.

Complete passive capture requires an authenticated OpenClaw, Hermes, or other
host adapter. Without one, this skill governs only operations performed through
it.

## Source classification

| Source | CLI value | Expected initial treatment |
|---|---|---|
| Authenticated statement from the subject | `user_message` | Eligible for active semantic memory |
| Retrieved web content | `webpage` | Quarantined |
| Tool or agent output | `tool_output` | Quarantined |

Do not relabel content to obtain a more permissive policy result.

## Corrections

Submit the corrected user statement as new evidence. Do not overwrite a row.
AetnaMem can supersede the old active record while retaining its audit history.

## Media

AetnaMem stores a text observation envelope, an exact-byte SHA-256, and a
host-controlled reference—not the media bytes. `forget-artifact` covers
derivatives of that exact byte stream. Re-encodings, copies, backups, and the
host's original file remain outside that receipt.

## Identity

`--subject` is the person or entity the memory describes. It is not the agent
name, session name, or a friendly placeholder. A trusted multi-user host must
derive it from authenticated identity.
