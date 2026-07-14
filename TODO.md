# aetnamem Guarded Actions TODO

This is the implementation checklist for **aetnamem Guarded Actions**: a
causal transaction layer connecting evidence, memory, authority, tool effects,
verification, and recovery. `aetnamem` is the canonical CLI executable.

## Foundation

- [x] Preserve the existing `Memory` API and default behavior.
- [x] Add nested SQLite unit-of-work support.
- [x] Make audit head selection and append one `BEGIN IMMEDIATE` transaction.
- [x] Make semantic memory operations and their audit events atomic.
- [ ] Add a storage protocol before implementing Firestore/Postgres backends.
- [ ] Add signed external checkpoints and trusted timestamp integration.

## Guarded-actions kernel

- [x] Add typed action modes, states, effect classes, evidence, patches, and receipts.
- [x] Separate `informed_by` evidence from `authorized_by` authority.
- [x] Add a durable action ledger and erasable payload plane.
- [x] Bind every proposal to a canonical plan hash.
- [x] Add HMAC-signed, exact-plan approvals with expiry and nonce.
- [x] Revalidate adapter manifests and world-state preconditions before execution.
- [x] Persist execution intent before calling an external provider.
- [x] Record explicit `UNCERTAIN`, `PARTIAL`, and `RECOVERY_REQUIRED` outcomes.
- [x] Verify compensation instead of trusting a compensator return value.
- [x] Add independently verifiable action receipts.

## Adapters and providers

- [x] Add a rooted filesystem reference adapter and conformance tests.
- [x] Define the stable adapter/provider protocol.
- [x] Add digest-only, idempotent import of compatible operational journals.
- [ ] Add more execution providers behind the conformance-tested protocol.
- [ ] Add Firestore storage and transaction-ledger support.
- [ ] Add an X adapter with honest compensatable/irreversible classifications.
- [ ] Add a credential broker using opaque secret references.

## Interfaces

- [x] Make `aetnamem` the canonical installed executable and documentation command.
- [x] Add `aetnamem actions stage/show/list/approve/commit/abort/recover/verify/import-journal`.
- [x] Add an MCP gate that removes direct write tools when enforcement is enabled.
      (`aetnamem/mcp/gate.py`: spawn-and-forward proxy, read-only passthrough,
      default-block for unclassified writes. In-process equivalent for the
      built-in assistant loop is `aetnamem/broker/` + `aetnamem/service/`.)
- [x] Add a macOS local dashboard/assistant shell with onboarding checks,
      provider setup, chat, pending approvals, memory inspection, Keychain
      provider secrets, and encrypted at-rest DB sealing on clean shutdown.
- [ ] Add Telegram as a separate privileged approval client.
- [ ] Package a signed/notarized macOS `.app` wrapper around the local service.
- [ ] Expand the dashboard for full evidence, authority, patch, execution, and recovery history.

## Security and validation

- [x] Fault-injection tests for memory/audit atomicity.
- [x] Concurrent-writer tests for audit-chain integrity.
- [x] Approval replay and plan-mutation tests.
- [x] Tool-manifest drift and world-state TOCTOU tests.
- [x] Untrusted-memory-can-inform-but-not-authorize tests.
- [x] Fence interrupted external-call windows as `RECOVERY_REQUIRED` without blind retry.
- [ ] Provider-specific idempotency lookup and crash-resolution tests.
- [x] Fake/no-op compensation detection tests.
- [x] Secret-free audit-plane tests.
- [ ] Cross-subject isolation tests.
- [ ] Add a guarded-actions track to MemoryStackBench.

## Documentation and release

- [ ] Publish the WorldPatch and action-receipt specifications.
- [x] Publish an explicit guarantees/non-guarantees matrix.
- [x] Document deployment topology and gate-bypass prevention.
- [ ] Decide whether the SDK remains AGPL, becomes dual-licensed, or exposes a
      permissively licensed protocol/verifier package.
- [ ] Build the flagship aetnamem research → review → X action demonstration.
