# EtD pilot and external methodology-review runbook

Status: **pilot-ready package; execution requires an external organization**

This runbook turns the SDK playground into a controlled multi-user pilot. It
does not claim that a pilot or independent methodology review has occurred.
The named institution owns clinical governance and the external reviewer owns
their findings.

## 1. Entry criteria

Record evidence for every item before admitting real decision data:

- named executive sponsor, panel chair, methodologist, institutional approver,
  privacy/security owner, operations owner, and independent reviewer;
- a host application that derives `ActorContext` only from authenticated
  sessions and never exposes authority mutations to an agent;
- PostgreSQL with TLS, least-privilege roles, tested backup/restore, monitoring,
  and an external audit-head checkpoint destination;
- an asymmetric signing key, documented key-to-principal enrollment, rotation,
  revocation, recovery, and separation between signing and application roles;
- approved payload/COI retention periods covering primary storage, WAL,
  replicas, backups, logs, exports, and reports;
- a documented incident stop, authorization revocation, rollback, and adverse-
  event path;
- privacy, legal, clinical-safety, accessibility, and records-management review
  appropriate to the organization and jurisdiction.

Failure of any mandatory entry criterion is a no-go, not a deferred UI issue.

## 2. Dry-run protocol

Use synthetic data first. Run the installed playground against the intended
PostgreSQL environment and independently verify the bundle:

```bash
DECISION_DATABASE_URL='postgresql://...' \
  aetnamem-etd-playground \
    --postgres-dsn-env DECISION_DATABASE_URL \
    --namespace synthetic-pilot-001 \
    --output ./pilot-output

aetnamem-etd-verify ./pilot-output/decision-bundle.json \
  --public-key governance-key=/secure/governance-public.pem \
  --require-signatures
```

The host must additionally exercise: duplicate HTTP retries; two simultaneous
votes; vote-versus-close; stale version rejection; recusal exclusion; hidden-
ballot access; authorization expiry/revocation before action commit; database
restart; backup restore; signing-key disablement; and retention purge followed
by offline verification.

## 3. Real pilot protocol

Choose one bounded, reversible, non-emergency decision. Define the question,
decision owner, participants, conflict policy, consensus rule, approval rule,
implementation scope, monitoring measures, stop conditions, and retention
schedule before opening the case. Do not change those rules after seeing votes;
create a new revision or ballot when governance legitimately changes.

Capture these observations without placing sensitive content in support logs:

| measure | acceptance evidence |
|---|---|
| identity | every mutation has a valid principal attestation and mapped host session |
| eligibility | frozen roster matches membership and COI rulings at ballot opening |
| concurrency | no lost/late vote; retries return the original response |
| traceability | recommendation, adoption, plan, approvals, authorization, and action use exact digests |
| privacy | hidden votes and COI details are absent from unauthorized APIs and audit payloads |
| retention | due fields are replaced and signed purge receipt verifies after backup-cycle testing |
| operability | users complete assigned tasks; support incidents and recovery times are recorded |
| safety | revocation/expiry blocks execution and stop conditions reach the named owner |

An outcome is not a successful pilot merely because the panel reached
consensus. All mandatory controls and the verifier must pass.

## 4. Independent methodology review package

Give the reviewer the pinned template, case question, evidence-search and
appraisal methods, COI policy and rulings, roster/roles, consensus policy,
artifact-lineage diagram, complete redacted export, generated report, verifier
result, implementation/monitoring plan, deviations, incidents, and this
project's claims boundary.

Ask the reviewer to report independently on:

1. whether the selected criteria and judgments fit the stated EtD method;
2. whether evidence-to-judgment and judgment-to-recommendation links are
   understandable and sufficient;
3. whether panel composition, consumer input, COI handling, quorum, dissent,
   equity, feasibility, and implementation considerations were appropriate;
4. whether the generated report could mislead readers about certainty,
   consensus, approval, authorization, or compliance;
5. required corrections, severity, owner, due date, and re-review condition.

The reviewer signs and dates their own report. Store its digest as a new
artifact revision; do not rewrite the original case or represent reviewer
silence as approval.

## 5. Exit decision

The sponsor records go/no-go/conditional-go/stop, the evidence supporting it,
open corrective actions, approved production scope, and next review date. A
production go decision still does not create a GRADE, clinical-validation, or
regulatory-compliance claim. Those claims require the applicable independent
assessment and evidence.

Use the [pilot configuration example](../examples/etd-playground/pilot-config.example.json)
as a host-owned checklist. It is configuration documentation, not a secrets
file or a built-in user layer.
