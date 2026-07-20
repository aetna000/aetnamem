# aetnamem Guarded Actions

Guarded Actions is an optional causal transaction layer adjacent to
`Memory`. It does not change the existing memory API or execute anything when
its mode is `off`, `observe`, or `preview`.

Its policy rule is:

> Information labeled untrusted may inform an action, but it cannot satisfy an
> `authorized_by` policy check.

Labels are not identities. The current local API trusts its host to assign
`trust_tier` and `attested` correctly. HMAC approval separately proves that a
holder of the reviewer key approved the exact plan; it does not authenticate
the human-readable approver label.

## Modes

| mode | behavior |
|---|---|
| `off` | guarded-actions API rejects proposals |
| `observe` | persist a patch and causal evidence; execution is disabled |
| `preview` | prepare and persist a semantic patch; execution is disabled |
| `enforce` | require trusted authority and an exact-plan signed approval before execution |

## State model

```text
DRAFT → STAGED → AWAITING_APPROVAL → APPROVED → COMMITTING → COMMITTED

Pre-commit → ABORTED
Failure → COMPENSATING → COMPENSATED | PARTIAL
Ambiguous provider outcome → UNCERTAIN
```

`UNCERTAIN` is deliberate. If a provider call raises after request dispatch,
`aetnamem` does not know whether the external effect happened. It persists the
ambiguity and refuses a blind retry. Provider-specific recovery and
idempotency lookup are required before that operation can be resolved.

An interrupted process observed later follows
`COMMITTING | COMPENSATING → RECOVERY_REQUIRED`; recovery deliberately fences
the operation instead of guessing whether it should be retried.

## Trust boundaries

- The agent/model proposes operations and may cite `informed_by` evidence.
- `actor_id` and the approval's `approver` string are attribution labels, not
  identities authenticated by the current engine.
- A trusted host may label actual user-task evidence `authorized_by` and
  `attested`. The engine validates the label but does not authenticate the host.
- The reviewer process holds the shared approval key and signs the transaction,
  exact plan hash, attribution label, issuance time, expiry, and nonce.
- The execution process rechecks the signature, adapter manifest, approval
  expiry, and world preconditions.
- The adapter executes and independently observes its postcondition.
- The engine-append-only audit plane stores digests; the erasable payload plane
  stores arguments, previews, before-images, and operational receipts.

Do not expose the approval key or an approval command to the same MCP tools
available to the model. Do not leave a direct write tool available beside its
guarded version. The current memory MCP server is not an action gate, so
enforcement remains partly a deployment-topology property.

## Python API

The following is a compact local example. In a production topology, construct
the proposal in an agent-facing process that has no approval key, then perform
approval and commit in a separate trusted reviewer/executor service.

```python
from aetnamem import Memory
from aetnamem.actions import (
    ActionEngine,
    ApprovalAuthority,
    EvidenceRef,
    FilesystemAdapter,
    OperationProposal,
)

memory = Memory("./memories.db")
authority = ApprovalAuthority(open("approval.key", "rb").read())
engine = ActionEngine(
    memory,
    adapters=[FilesystemAdapter("./workspace")],
    approval_authority=authority,
)

patch = engine.propose(
    "user-1",
    [OperationProposal(
        key="write-report",
        adapter="filesystem",
        operation="write_text",
        arguments={"path": "report.md", "content": "..."},
        evidence=(EvidenceRef(
            kind="user_task",
            ref_id="task-42",
            digest="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            relation="authorized_by",
            trust_tier="trusted_user",
            attested=True,
        ),),
    )],
    actor_id="researcher-agent",
)

approval = authority.issue(
    transaction_id=patch.transaction_id,
    plan_hash=patch.plan_hash,
    approver="user-1",
)
engine.approve(approval)
result = engine.commit(patch.transaction_id)
```

## Current engine guarantees

- Memory operations and their audit events share one SQLite unit of work.
- Concurrent audit appenders serialize head selection and insertion.
- Every persisted action proposal has a canonical plan hash; commit recomputes
  it before execution.
- Enforced mutations require `authorized_by` evidence carrying a trusted tier
  and `attested=true`. The host is responsible for those labels' authenticity.
- Approvals authenticate possession of the shared reviewer key and bind the
  transaction, exact plan, attribution label, expiry, and nonce. They do not
  independently authenticate the attribution label.
- Adapter manifest drift or resource precondition drift prevents execution.
- Execution intent and an idempotency key are durable before an adapter call;
  provider-level idempotency exists only when the adapter/provider honors it.
- Provider exceptions become `UNCERTAIN`, never an unqualified rollback.
- Filesystem compensation refuses to overwrite a concurrent later change and
  verifies restoration of content, existence, type, and mode.
- Action receipts are bound to the existing per-subject hash chain.
- Engine-generated guarded-action events exclude raw action content. Raw action
  payload rows can be logically purged from the live database.

## Current non-guarantees

- HMAC is a local symmetric-key approval primitive, not KMS-backed asymmetric
  identity. Anyone holding the shared key can choose an approver label.
- The engine does not authenticate the caller that assigns evidence trust tiers
  or `attested=true`; protect the staging API/CLI at the deployment boundary.
- Action payloads are erasable but not encrypted at rest yet.
- Payload purge is not forensic secure deletion of SQLite free pages, WAL,
  backups, snapshots, exports, or replicas.
- A filesystem write can trigger watchers or hooks and is therefore not an
  exact transaction.
- A provider exception can be ambiguous; no generic runtime can prove that a
  remote service did or did not apply the request.
- The current CLI stages one operation at a time. The Python API supports a
  dependency graph of multiple operations.
- `memory_log_action` accepts caller-defined payloads and can contain raw data;
  its caller must enforce the digest-only convention.
- The fail-closed filter-only MCP gate is implemented. Automatic conversion of
  arbitrary blocked upstream writes into staged `WorldPatch` transactions,
  additional execution providers, external reviewer channels, database
  services, and social-network adapters remain in [TODO.md](../TODO.md).

## External journal import

`aetnamem actions import-journal` imports compatible transaction/effect
histories as digest-only `action.source_imported` events. The importer reduces raw
arguments, snapshots, results, client identities, and claimed actors to
digests before appending the event. Each import is labeled
`unverified_operational_journal`; it is useful for migration and forensic
correlation but does not claim that the source's
mutable status, rollback, identity, or compensator assertions were verified.

Direct external execution remains behind the provider boundary until it passes
the same crash, authority, idempotency, privacy, and compensation-verification
conformance tests as native adapters.

The importer currently expects a SQLite journal with `transactions` and
`effects` tables. Run `aetnamem actions import-journal --help` for the command
shape; incompatible or incomplete schemas fail before any audit event is
written.

## Formats

The current implementation uses:

- `aetna-world-patch-v1` for the hashed proposal body;
- `aetna-action-approval-v1` for signed approvals;
- `aetna-action-receipt-v1` for terminal receipts;
- existing audit-log v1 events named `action.*`.

Action IDs live in audit event payloads, so the frozen audit-v1 hash preimage
and standalone memory verifier remain compatible.

`tools/verify_actions.py` independently verifies the action plan, audit chain,
approval scope/signature, and receipt without importing the `aetnamem` package.
It verifies recorded structure and cryptographic bindings; it cannot prove a
remote system performed an effect beyond the evidence supplied by its adapter.

## Collaborative decision authorization

`aetnamem.decisions.DecisionAuthorityResolver` is an opt-in bridge from an
institutionally approved implementation plan to Guarded Actions. A panel vote
or recommendation adoption is evidence, not execution authority. The bridge
emits the adoption as `informed_by` and only a scoped, active institutional
grant as `authorized_by`.

Configure `decision_authorization` as a trusted tier only in the trusted host
that owns the resolver. The resolver dereferences and checks the grant at both
stage and commit, including digest, namespace, plan revision, expiry,
revocation, subject, adapter, operation, and optional resource. The ordinary
exact-plan HMAC approval remains required. The standalone action verifier
checks the recorded action binding; online grant status is checked by the
resolver and is not inferred from an untrusted copied `EvidenceRef`.
