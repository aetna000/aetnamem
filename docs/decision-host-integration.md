# Hosting collaborative decisions

Status: **implemented SDK contract; host server not included**  
Stores: SQLite for one server; PostgreSQL 14+ for multi-instance hosts

This guide describes how a hospital, policy body, or business embeds
`aetnamem.decisions` after `pip install aetnamem`. It does not require
AetnaMem's desktop UI, MCP, or any model provider.

## Host responsibilities

The host supplies authentication, sessions, organization membership, TLS,
CSRF/CORS controls, rate limiting, UI, notifications, file/object storage,
secrets, database operations, backup/recovery, and regulatory policy. AetnaMem
supplies decision validation, case membership, recusal, concurrency,
idempotency, persistence, optional signed identity/receipts, retention purge,
audit events, and exports.

Construct `ActorContext` only from authenticated server state:

```python
context = ActorContext(
    namespace_id=request.authenticated_organization_id,
    principal_id=request.authenticated_principal_id,
    correlation_id=request.request_id,
)
```

Never copy namespace, principal, or assurance from request JSON. Never expose
`cast_vote`, `close_ballot`, `adopt_recommendation`, or `grant_authorization`
directly as model-callable tools.

## Request and concurrency model

The synchronous Python API returns JSON-safe dictionaries and can sit behind
FastAPI, Django, Flask, or another host. Use one repository connection per
request/unit of work. Every mutation requires a durable idempotency key;
versioned transitions also require the last observed version. Map
`DecisionConflict` to HTTP 409. `list_events(..., after_sequence=N)` supplies a
monotonic polling/WebSocket cursor without making networking part of the SDK.

SQLite WAL plus `BEGIN IMMEDIATE` supports a small or moderate panel on one
server. Do not put SQLite on a network filesystem, use it across horizontal
workers, or share an engine connection across arbitrary threads.

## PostgreSQL deployment

Install AetnaMem and keep the DSN in the host secret manager:

```bash
pip install aetnamem
export DECISION_DATABASE_URL='postgresql://...'
```

```python
import os
from aetnamem.decisions import DecisionEngine

engine = DecisionEngine.postgres(os.environ["DECISION_DATABASE_URL"])
try:
    ...  # one request / unit of work
finally:
    engine.close()
```

For a host-managed psycopg pool, check out a clean connection, construct
`PostgresDecisionStore(connection=connection)`, and pass it to
`DecisionEngine`. The repository does not close injected connections; the host
returns them to its pool. Schema migration uses an advisory lock, so concurrent
worker startup is idempotent. Ballot row locks and per-key/per-audit-stream
advisory locks preserve the decision contract across processes. The package
does not create databases, roles, TLS policy, replicas, backups, failover, or
connection pools.

Exercise a real PostgreSQL server without putting its DSN in argv:

```bash
DECISION_DATABASE_URL='postgresql://...' \
  aetnamem-etd-playground --postgres-dsn-env DECISION_DATABASE_URL
```

## Signed identity and decision receipts

Unsigned `ActorContext` is the backward-compatible default. In a strict host,
issue a short-lived `PrincipalAttestation` after login and configure
`attestation_verifier=...` plus `require_attestations=True`. The signature binds
namespace, principal, assurance, issue/expiry times, and a nonce. Clients must
not select those fields before the host signs them.

`Ed25519Signer` is the included local/reference asymmetric implementation.
`AwsKmsSigner` and `AwsKmsVerifier` accept a standard
boto3-compatible KMS client and use KMS `DIGEST` mode. The KMS key must be an
asymmetric signing key supporting the selected algorithm. IAM, key policies,
rotation, disablement, deletion, public-key distribution, and KMS API auditing
remain host controls.

With `receipt_signer` configured, ballot outcomes, adoptions, approvals,
authorizations, and purges receive digest-bound signatures. Verify an export
fail-closed with:

```bash
aetnamem-etd-verify decision-bundle.json \
  --public-key governance-2026=/secure/governance-public.pem \
  --require-signatures
```

## Retention and logical purge

Only a member with `manage_retention` can configure and execute retention:

```python
engine.set_retention_policy(
    chair, case_id, payload_days=365, coi_days=90,
    idempotency_key=request_id,
)
receipt = engine.purge_due_payloads(
    chair, case_id, idempotency_key=purge_job_id,
)
```

`None` disables eligibility for a category; `0` makes existing rows immediately
eligible. Purge retains IDs, immutable digests, lineage, audit events, and a
verifiable receipt while replacing sensitive live fields. It is logical
deletion, not physical sanitization. Apply corresponding expiry to WAL archives,
snapshots, replicas, object storage, logs, reports, and exported bundles.

## Approved-change bridge and provider neutrality

The decision package imports no Claude, Grok/xAI, OpenAI, Ollama, MCP, or web
framework. `DecisionAuthorityResolver` emits adoption as `informed_by` and the
institutional grant as `authorized_by`. `ActionEngine` rechecks grant scope,
digest, status, expiry, and revocation at staging and immediately before commit.
Guarded Actions still requires its separate exact-`WorldPatch` approval.

## Security and rollout boundary

Hash chaining detects mutation relative to a trusted checkpoint. Signed mode
proves possession of configured keys; it does not prove the host's key-to-person
enrollment or protect an unanchored database from wholesale replacement.
Hidden ballots restrict normal API reads but do not hide choices from database
administrators. Cryptographic ballot secrecy requires a separate protocol.

Before deployment, follow the [pilot and methodology-review
runbook](etd-pilot-methodology-review.md). A real institution and independent
reviewer must generate the actual pilot observations and review findings.
