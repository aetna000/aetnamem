# AetnaMem OpenClaw dashboard contract

Status: **implemented two-state dashboard**

The [Safe Switch guide](safe-switch.md) and
[current capability status](current-status.md) define the implementation
boundary. This document defines the customer-facing interaction.

## Product rule

The customer sees only two states:

| State | Meaning |
|---|---|
| **OpenClaw active** | OpenClaw remains the memory provider. AetnaMem copies, indexes, searches, and audits the native memory without changing model context. |
| **AetnaMem active** | The verified native state is frozen. AetnaMem serves bounded governed memory through compatible OpenClaw tools. |

Preview, canary, candidate review, and emergency-off are not customer modes.
Internal observations, retrieval decisions, and exposures remain evidence, not
navigation or switches. Rollback is the only supported way from AetnaMem
active to OpenClaw active because it restores and verifies a usable native
state.

## Dashboard jobs

The dashboard has one page and four jobs:

1. Show which memory provider is active.
2. Search the mirrored AetnaMem memory using ordinary words.
3. List exactly which OpenClaw files were mirrored, including byte count,
   classified plane, and complete SHA-256 digest.
4. Activate AetnaMem or restore OpenClaw.

There are no charts, projected savings, experimental funnels, candidate
approval queues, section navigation, or mock comparison figures.

## OpenClaw-active state

The primary headline is `OpenClaw memory is still active`.

The page shows:

- mirrored file count;
- searchable record count;
- source bytes preserved;
- mirror audit verification;
- the exact source-file manifest;
- search results with source path and line provenance;
- readiness checks for mirror synchronization, audit verification, searchable
  records, and safe activation.

`Refresh mirror` synchronizes current native memory. `Activate AetnaMem` is
disabled until the backend reports `ready_for_active`. Activation requires the
user to type the detected host name. The backend then performs the full
snapshot, compatibility, restart, and rollback-on-failure ceremony.

## AetnaMem-active state

The primary headline is `AetnaMem is managing OpenClaw memory`.

The page keeps search and the source manifest visible. It replaces readiness
with verified takeover checks: native snapshot, gateway, compatibility tools,
and capture hooks. The only provider-changing action is `Restore OpenClaw`.

Restore asks for confirmation, restores and verifies the frozen native files
and prior host configuration, restarts the gateway, and preserves AetnaMem
trial evidence.

## CLI surface

```text
aetnamem openclaw install
aetnamem trial start --host openclaw
aetnamem trial status
aetnamem trial activate
aetnamem trial rollback
aetnamem dashboard
aetnamem dashboard daemon start --port 8766
```

The installer normally starts the mirror, so customers should not need to run
`trial start` separately. `status` prints the active memory provider, mirrored
file and record counts, mirror verification, whether agent context changes,
and audit-chain health. Machine-readable output remains available with
`--json`.

## Security and truthfulness

The dashboard binds only to loopback, uses a one-time login URL, an HttpOnly
same-site cookie, CSRF tokens, and Origin checks. It renders all memory text
with `textContent`, not HTML.

The dashboard reports local facts only. It does not claim improved answer
quality, token savings, or provider cost. Those require a separate controlled
evaluation. Searchability, source coverage, digests, audit verification, and
the active provider are directly backed by local state.
