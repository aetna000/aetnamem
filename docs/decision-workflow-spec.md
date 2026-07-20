# AetnaMem collaborative decision workflow specification

Status: **experimental**  
Protocol version: `aetnamem-decision-*-v1`  
Implemented surface: Python SDK, SQLite/PostgreSQL stores, signed receipts, retention purge, export verifier  
Server, UI, and identity: host responsibility

This document defines the generic, provider-neutral decision workflow shipped
in `aetnamem.decisions`. EtD is one profile of this protocol; the kernel does
not contain clinical vocabulary or make clinical judgments.

## Trust boundary

The host authenticates a person and constructs `ActorContext(namespace_id,
principal_id, ...)` server-side. By default, AetnaMem records those opaque
identifiers and enforces case membership and capabilities. A host that needs
cryptographic binding can configure `require_attestations=True` with an
Ed25519 or KMS-backed verifier; every mutation then requires a valid,
unexpired `aetnamem-principal-attestation-v1` binding namespace, principal,
assurance, validity window, and nonce. An unsigned actor label remains host
attribution, not proof of identity.

`namespace_id` is the tenant boundary for decision objects. Every lookup is
scoped by namespace and object ID. It is distinct from Memory's `subject_id`,
which remains a caller-selected memory partition.

## Objects and immutable revisions

- A `DecisionTemplate` defines versioned criteria, choices, sections, and a
  canonical digest. A case pins the complete template version and digest.
- A `DecisionCase` supplies the collaborative scope and an opaque audit stream.
- A `DecisionArtifact` is a stable identity for evidence, an assessment, a
  recommendation, an implementation plan, or another decision object.
- An artifact revision is immutable. Its digest binds artifact ID, revision,
  kind, content, and author under `aetnamem-decision-artifact-v1`.
- `ArtifactLink` binds an exact source revision and digest to an exact target
  revision with a semantic role. Formal lineage never depends on graph search.

Trust tier, methodological certainty, and extraction confidence are separate:

| concept | question answered |
|---|---|
| trust tier | Where did this information come from, and may it authorize? |
| certainty rating | How certain is the relevant body of evidence? |
| extraction confidence | How confident was an extraction or algorithm? |

## Membership, conflicts, and recusal

Case roles map to explicit capabilities. The engine, not the UI, checks the
capability on every mutation. Conflict declarations retain their full details
in decision data while `decision.conflict.*` audit events contain only IDs,
scope, state, and digests. A `recused` ruling may cover the whole case or an
artifact/revision. Ballot eligibility freezes the applicable ruling.

## Ballots

Opening a ballot freezes:

- target revision and digest;
- eligible and excluded roster;
- membership versions;
- choices and visibility;
- consensus policy and digest;
- optional deadline.

Votes are immutable revisions. Replacing a vote requires the current vote ID;
the old vote becomes `superseded`. Each vote commitment is salted and binds
the voter, ballot, revision, choice, rationale, and salt. For
`hidden_until_close`, normal reads omit votes until closure. This is workflow
privacy, not a cryptographic secret-ballot guarantee against the database
administrator.

Supported v1 outcome methods are `threshold`, `unanimity`, and host-attested
`manual`. Quorum, denominator (`eligible`, `participating`, or
`non_abstain`), passing choices, and threshold are explicit policy data.
Closing and outcome creation occur in one transaction.

## Adoption, approval, and authorization

These are intentionally different transitions:

1. A ballot outcome records panel judgment about one revision.
2. Adoption binds a passed outcome to one recommendation revision.
3. Approval records an institutional approver's decision on one implementation
   plan revision.
4. An authorization grant binds the adopted recommendation, exact plan,
   required approval records, operational scope, and optional expiry.
5. Guarded Actions still requires a separate exact-`WorldPatch` approval.

Consensus alone is never emitted as `authorized_by` evidence.

## Concurrency and idempotency

Mutable aggregates have integer versions and compare-and-swap transitions.
Every mutation requires an idempotency key, scoped by namespace and principal.
Repeating the same request returns its prior response; reusing a key for a
different request fails.

SQLite uses short `BEGIN IMMEDIATE` transactions. In a vote-versus-close race,
either the vote commits and is counted or closure commits and the vote fails.
One `DecisionEngine`/SQLite connection must not be shared across arbitrary
request threads.

PostgreSQL is available through `pip install aetnamem[postgres]` and
`DecisionEngine.postgres(dsn)`. Each engine owns one connection; horizontally
deployed hosts should obtain one engine/store per request from their normal
pool. PostgreSQL row locks serialize ballot mutation with closure, advisory
transaction locks serialize idempotency keys and per-case audit heads, and a
schema advisory lock makes concurrent process startup safe. Contract tests run
independent OS processes for simultaneous votes and vote-versus-close races.

## Audit and privacy

Decision changes and their `decision.*` audit events share one transaction.
Audit payloads contain structural metadata and digests, not questions,
rationales, COI details, vote choices, or recommendation text. Each case uses
its own derived audit scope so decision retention is not coupled to personal
memory erasure. External checkpoints remain necessary to detect suffix
deletion or database replacement.

`set_retention_policy()` independently configures decision-payload and COI
retention. `purge_due_payloads()` logically replaces due case questions,
titles, artifact content, vote choices/rationales/salts, approval rationales,
and COI detail with non-sensitive placeholders. Immutable digests, structural
lineage, and a `aetnamem-decision-purge-receipt-v1` listing prior digests are
retained. Logical purge does not sanitize database pages, WAL, backups,
replicas, object stores, or previously exported bundles; hosts must apply the
same lifecycle to those systems. Due idempotency response bodies are also
purged; reusing such a key raises `DecisionStateError` because the original
response can no longer be replayed safely.

## Canonical exports

`DecisionEngine.export_case()` emits `aetnamem-decision-bundle-v1`. The
installed `aetnamem-etd-verify` command checks template, artifact, lineage,
vote, outcome, adoption, approval, authorization, and bundle digests without
instantiating the engine. Outcome, adoption, approval, authorization, and purge
receipts are signed when a `DecisionSigner` is configured. The verifier checks
Ed25519 signatures with repeatable `--public-key KEY_ID=PEM_PATH` arguments and
can fail closed with `--require-signatures`. `AwsKmsSigner`/`AwsKmsVerifier`
accept boto3-compatible clients and use KMS `DIGEST` mode, so the core package
does not own cloud credentials or import boto3.

## Non-guarantees

The protocol does not provide a public server, connection pooling, automatic
key provisioning/rotation, HA orchestration, methodological correctness,
GRADE compliance, clinical validation, regulatory compliance, database-
administrator-resistant secret ballots, or non-repudiation when unsigned host
identity mode is used. Asymmetric signatures prove possession of a configured
key; the host remains responsible for key-to-person binding, revocation,
trusted time, and external anchoring.
