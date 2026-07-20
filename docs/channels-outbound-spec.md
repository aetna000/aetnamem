# Specification: Aetnamem Channels and Governed Outbound

Status: **draft / platform proposal**
Author: **aetna000.com**
Scope: reusable intake, review, and outbound integration around
`aetnamem-core`

---

## 1. Purpose

This specification defines how organizations can connect existing
communication channels and business systems to Aetnamem without changing the
semantics of its governed memory engine.

The platform is divided into three products with explicit boundaries:

1. **`aetnamem-core`** stores and retrieves governed memory, applies trust and
   lifecycle policy, records evidence, and controls consequential actions.
2. **`aetnamem-channels`** captures authenticated inbound events from informal
   communication channels, structured forms, and APIs and converts them into
   a provider-neutral envelope.
3. **`aetnamem-outbound`** publishes approved information to files and
   external systems through guarded, independently auditable adapters.

Business applications may add their own forms, queues, fields, rankings, and
workflows above these layers. No particular industry or workflow is part of
the core specification. Channels and Outbound are optional extensions;
`aetnamem-core` remains independently usable as persistent governed memory for
AI assistants and agents.

## 2. Product boundary

```text
Agent frameworks / AI assistants       Informal inputs / forms / APIs
        | Python SDK / MCP                         |
        |                                          v
        |                                aetnamem-channels
        |                          authenticate, normalize, deduplicate
        |                                          |
        +---------------------+--------------------+
                              v
                       aetnamem-core
        provenance, trust, lifecycle, recall, audit, approval
                              |
                              v
                     aetnamem-outbound
          Jira / spreadsheet / PDF / webhook / business API
```

### 2.1 `aetnamem-core`

Core remains source-agnostic and domain-agnostic. It owns:

- canonical episodes and semantic records;
- trust tiers, quarantine, promotion, supersession, and deletion receipts;
- deterministic FTS and graph retrieval with evidence;
- confidence and ambiguity handling;
- per-scope audit chains and externally anchorable checkpoints;
- guarded-action staging, exact-plan approval, revalidation, execution,
  verification, compensation, and receipts;
- encrypted storage, backup, restore, and verification contracts.

Core must not contain provider SDKs, Jira project rules, spreadsheet column
definitions, report layouts, industry terminology, staff rosters, shift
logic, or business-specific statuses.

### 2.1.1 Direct agent-memory compatibility

Direct agent integration remains a first-class use of Core. An agent does not
need Channels or Outbound to use Aetnamem. Through the Python SDK, MCP server,
or a separately authenticated HTTP gateway, an AI host can continue to:

- remember user statements with source, session, and turn provenance;
- recall bounded records and graph paths with retrieval evidence;
- build audited context and persona blocks;
- capture conversation lifecycle events without memory feedback loops;
- correct, supersede, promote, forget, inspect, and verify memory;
- use a local model or a configured external model endpoint independently of
  the storage backend.

Model and framework names are integration details. Core exposes governed
memory verbs and evidence contracts rather than depending on a particular AI
provider. Existing Grok/xAI, OpenClaw, MCP, CLI, and embedded Python usage must
remain supported by compatibility tests.

### 2.2 `aetnamem-channels`

Channels is an inbound integration layer. It owns:

- provider webhook verification and API authentication;
- sender and conversation identity mapping;
- message, event, attachment, edit, and reply normalization;
- idempotent delivery and restart catch-up;
- content-addressed attachment storage;
- provider-specific acknowledgements;
- an audited mapping from provider identity to an organization principal.

Channels has ingest capability only. It cannot promote memory, approve a
proposal, publish an output, or hold reviewer authority.

### 2.3 `aetnamem-outbound`

Outbound is an effect-adapter layer. It owns:

- deterministic preparation of an external operation;
- provider authentication and secret references;
- precondition and policy checks;
- idempotency and duplicate detection;
- execution, provider acknowledgement, and postcondition verification;
- compensation where the destination supports it;
- evidence-bound receipts and explicit `uncertain` outcomes.

Outbound adapters do not decide what is true or what should be published.
They execute an approved plan supplied through the core guarded-action
engine.

## 3. Non-goals

This specification does not define:

- an industry-specific workflow or vertical product;
- a replacement for Jira, a CRM, an ERP, a document-management system, or a
  data warehouse;
- automatic trust based only on a sender being known;
- unrestricted model-generated publishing;
- direct public exposure of Aetnamem's loopback desktop service;
- a requirement to install or configure Channels or Outbound before an agent
  can use Core memory;
- a universal business object or workflow status model.

## 4. Canonical inbound envelope

Every channel adapter emits the same provider-neutral structure:

```json
{
  "schema_version": "aetnamem.channel-event.v1",
  "provider": "informal-channel",
  "scope_id": "org-acme/workspace-operations",
  "conversation_id": "conversation-123",
  "event_id": "event-456",
  "event_type": "message.created",
  "reply_to_event_id": null,
  "principal": {
    "provider_id": "channel-user-42",
    "directory_id": "employee-184",
    "display_name": "Example User",
    "identity_assurance": "provider_authenticated"
  },
  "occurred_at": "2026-07-19T06:42:13Z",
  "text": "Example business observation or request",
  "mentions": ["channel-user-43"],
  "attachments": [
    {
      "kind": "image",
      "sha256": "9f3c...",
      "bytes": 812345,
      "mime": "image/jpeg",
      "stored_path": "attachments/9f/9f3c....jpg"
    }
  ],
  "raw_provider_payload_sha256": "cc10..."
}
```

Rules:

- `scope_id` is derived by the authenticated host. An external caller cannot
  select another organization's scope by changing a request field.
- `(provider, conversation_id, event_id)` is an idempotency key.
- Attachments are downloaded, hashed, size-limited, malware-scanned where
  configured, and stored content-addressed.
- Provider edits and deletions become new lifecycle events; they do not
  silently rewrite previously captured evidence.
- Raw provider payloads need not enter the audit chain. Their digest, the
  normalized envelope, and retained attachments form the durable commitment.
- Provider-specific metadata may be retained in an extension object, but
  core behavior cannot depend on it.

## 5. Identity, trust, and authority

Transport identity, information trust, and action authority are separate:

1. **Identity assurance** answers who or what submitted an event.
2. **Information trust** answers how the content may enter memory.
3. **Action authority** answers whether the content may cause an external
   effect.

A correctly signed webhook can prove that a known employee sent a message.
It does not prove that every statement in the message is correct. The host
may retain the original event as authenticated evidence while extracted or
model-derived claims remain quarantined until policy or human review admits
them.

The directory or identity gateway maps provider identities to organization
principals. `subject_id` remains a storage scope inside core; it is not used
as an authentication mechanism. Multi-tenant deployments must derive it
server-side from the authenticated organization and workspace.

## 6. Channel adapter contract

```python
class ChannelAdapter(Protocol):
    provider: str

    def verify_request(self, request: InboundRequest) -> VerifiedRequest:
        """Authenticate the callback before parsing its content."""

    def normalize(self, request: VerifiedRequest) -> list[ChannelEvent]:
        """Convert provider input to canonical channel events."""

    def fetch_attachment(
        self, reference: AttachmentReference, destination: Path
    ) -> StoredAttachment:
        """Download, validate, hash, and store an attachment idempotently."""

    def acknowledge(self, event: ChannelEvent, result: IntakeResult) -> None:
        """Optionally send a provider-specific receipt or status response."""

    def catch_up(self, cursor: str | None) -> EventBatch:
        """Resume from a durable provider cursor where supported."""
```

The initial release supports one informal group-messaging input adapter. Its
provider identity is an implementation detail rather than part of the product
or canonical event contract. Future adapters may support other organizational
communication systems, authenticated mailboxes, signed web forms, and
customer-owned REST APIs without changing core memory semantics.

Each adapter is optional. Organizations install only the input mechanisms
allowed by their security and data-residency policy.

## 7. Proposals and business review

Applications may use a configured local or hosted model to propose summaries,
classifications, structured fields, duplicate candidates, priorities, or
document drafts. These outputs are derived information and cannot promote
themselves.

Every proposal records:

- source episode and attachment digests;
- model provider and model identifier;
- prompt or extractor version;
- generated output digest;
- confidence and abstention information;
- policy version that selected its initial lifecycle state.

Core provides quarantine, promotion, supersession, evidence, and action
approval. The application owns its business fields and review interface.
For example, one application may review customer cases while another reviews
research observations. Neither vocabulary belongs in core.

## 8. Governed automation

Large organizations need automation, but automation must not mean bypassing
authority controls.

An outbound operation may be authorized in either of two ways:

1. **Human approval:** a reviewer approves the exact prepared plan.
2. **Pre-authorized policy:** a signed, versioned organization policy permits
   a narrowly defined class of operations, destinations, fields, limits, and
   identities.

Both paths produce the same plan hash and execution receipt. Policy-driven
automation must fail closed when the policy, destination configuration,
source evidence, precondition, or adapter manifest changes. High-impact or
ambiguous operations can always require human review.

## 9. Outbound adapter contract

Outbound adapters implement the existing guarded-action lifecycle:

```python
class OutboundAdapter(Protocol):
    name: str

    def manifest(self) -> dict:
        """Return versioned capabilities and security-relevant configuration."""

    def prepare(
        self, operation: str, arguments: dict, context: ActionContext
    ) -> PreparedOperation:
        """Build a deterministic preview, preconditions, and idempotency key."""

    def revalidate(self, prepared: PreparedOperation) -> ValidationResult:
        """Confirm destination and policy preconditions immediately before use."""

    def execute(self, prepared: PreparedOperation) -> ExecutionReceipt:
        """Perform the approved effect."""

    def verify(
        self, prepared: PreparedOperation, receipt: ExecutionReceipt
    ) -> VerificationResult:
        """Read back or otherwise verify the postcondition."""

    def compensate(
        self, prepared: PreparedOperation, receipt: ExecutionReceipt
    ) -> CompensationReceipt:
        """Attempt a declared rollback when the provider supports it."""
```

Provider secrets are referenced from an operating-system vault or enterprise
secret manager and are never embedded in plans, audit payloads, or generated
reports.

## 10. Suggested outbound capabilities

### 10.1 Jira and work-management systems

Suggested operations:

- create an issue from approved content;
- update a defined set of fields;
- add a comment or attachment;
- link an Aetnamem evidence identifier;
- read back the resulting issue key and selected fields.

The adapter should use provider idempotency where available and otherwise
write an Aetnamem operation digest into a dedicated external field or label.
Creating or changing an issue is an external effect and always requires
human or pre-authorized policy approval.

The same contract can support systems such as Linear, ServiceNow, Azure
DevOps, or a customer-owned work-management platform without changing core.

### 10.2 Spreadsheet and tabular export

Suggested outputs:

- `.xlsx` workbooks for business users;
- `.csv` files for portable interchange;
- append or replace operations against a defined workbook/table;
- deterministic column mappings from an application-owned schema;
- a manifest sheet containing export time, scope, filter, source record
  digests, policy version, and audit checkpoint.

Spreadsheet generation should be deterministic from the approved records.
Formula injection must be prevented by escaping untrusted values beginning
with spreadsheet formula prefixes. Updates to an existing file use guarded
filesystem writes or a provider-specific API adapter.

### 10.3 PDF and document reports

Suggested outputs:

- deterministic PDF reports rendered from approved records;
- optional Markdown or HTML source retained beside the PDF;
- a visible report identifier and audit checkpoint;
- a machine-readable manifest containing included record and attachment
  digests;
- layout templates owned by the consuming application, not by core.

The PDF is an output artifact, not the canonical source of truth. Its digest
and publication receipt link it back to the records and approval that
created it.

### 10.4 Signed webhooks

Suggested behavior:

- HTTPS destinations from an administrator allowlist;
- HMAC or asymmetric request signing;
- timestamp, nonce, schema version, event identifier, and idempotency key;
- configurable retries with exponential backoff;
- a durable delivery ledger;
- explicit distinction between `failed`, `acknowledged`, and `uncertain`.

A timeout after dispatch is `uncertain`, not proof that nothing happened.
Blind retries are prohibited unless the destination honors the idempotency
key or a read-back check proves the operation absent.

### 10.5 Enterprise APIs

For higher-volume integration, Aetnamem Outbound may call a customer-owned
API or expose an authenticated event stream through a separate enterprise
gateway. The gateway should support:

- OIDC or mutually authenticated TLS;
- tenant and workspace derivation from authenticated identity;
- scoped service accounts and least-privilege permissions;
- asynchronous jobs and bounded batch operations;
- rate limits, backpressure, dead-letter handling, and replay controls;
- schema versioning and compatibility windows;
- per-operation evidence and audit correlation identifiers;
- regional deployment and customer-controlled data residency.

The local desktop service remains loopback-only. Public APIs and webhook
receivers run as separate hardened gateways and communicate with core over an
authenticated local or private-network boundary.

## 11. Why this matters for larger organizations

The three-layer design lets an organization:

- keep employee behavior in familiar channels while standardizing capture;
- connect multiple providers without forking memory semantics;
- distinguish authenticated origin from approved business truth;
- review ambiguous or high-impact proposals before publication;
- automate low-risk, policy-defined work without surrendering auditability;
- prove which source, model output, reviewer, policy, and external receipt
  contributed to an outcome;
- replace a channel, model, or destination without migrating canonical
  memory;
- keep the data plane local or in the organization's VPC;
- apply retention, deletion, backup, encryption, and incident-reconstruction
  policy consistently across applications.

This is the commercial boundary: Aetnamem is the governed state and effect
plane, while organizations retain their existing communication tools and
systems of record.

## 12. Storage, retention, and deletion

- Core stores canonical episodes, records, lifecycle state, and audit events.
- Channels stores provider cursors, identity mappings, normalized event
  metadata, and content-addressed attachments.
- Outbound stores prepared plans, approvals, receipts, verification results,
  and destination correlation identifiers.
- Application tables store business-specific fields and reference core record
  identifiers rather than duplicating canonical content unnecessarily.

Deletion receipts are scoped. Purging local Aetnamem content does not erase a
copy already published to Jira, a spreadsheet, a PDF archive, or another
system. External deletion must be a separate guarded operation with its own
authorization and receipt. Where a destination cannot verify deletion, the
result must state that limitation explicitly.

## 13. Reliability and scale

- Inbound adapters acknowledge only after durable intake or durable queueing.
- Work queues isolate capture, enrichment, review, and outbound delivery so a
  model or provider outage does not stop intake.
- Every queue consumer is idempotent.
- Large attachments are streamed and bounded rather than loaded wholly into
  process memory.
- Per-scope partitioning and quotas prevent one workspace from exhausting
  another.
- Outbound concurrency and rate limits are configured per destination.
- Checkpoints are anchored outside the primary database.
- Backup and restore cover the database, attachments, application tables,
  configuration manifests, and required key-recovery material.

Scaling the workers must not alter trust, approval, ranking, or receipt
semantics. The same input, policy version, and approved plan must retain the
same evidence identifiers regardless of deployment size.

## 14. Security requirements

Before an enterprise deployment, the platform requires:

- cross-platform encrypted database and attachment storage;
- operating-system or enterprise-vault key protection and key rotation;
- authenticated, server-derived tenant and scope boundaries;
- separate agent, reviewer, administrator, and service identities;
- least-privilege provider credentials;
- attachment size, type, and malware controls;
- TLS for every non-loopback connection;
- externally anchored audit checkpoints;
- tested backup, restore, key recovery, and deletion procedures;
- sandboxing or process separation where complete action mediation is
  required.

Encryption protects stored bytes; it does not make model output trustworthy
or replace authorization, lifecycle policy, or operating-system isolation.

## 15. Suggested package layout

```text
aetnamem/                         # existing core package
  memory.py
  graph/
  actions/
  audit/
  store/

packages/aetnamem_channels/       # optional inbound integration package
  base.py
  gateway.py
  identity.py
  attachments.py
  adapters/

packages/aetnamem_outbound/       # optional external-effect package
  base.py
  policy.py
  adapters/
    jira.py
    spreadsheet.py
    pdf_report.py
    webhook.py
    enterprise_api.py

applications/                     # separately versioned business products
  <application-name>/
```

The exact repository layout may change, but dependency direction may not:

```text
applications -> aetnamem-channels -> aetnamem-core
applications -> aetnamem-outbound -> aetnamem-core
agent integrations -> aetnamem-core
aetnamem-channels -X-> aetnamem-outbound
aetnamem-core -X-> providers or business applications
```

## 16. Delivery phases

| Phase | Scope | Gate |
|---|---|---|
| 1 | Provider-neutral inbound envelope, adapter protocol, attachment store, idempotent gateway | Replay and duplicate-delivery tests pass |
| 2 | One organizational channel adapter and one signed API/form adapter | Authenticated origin and catch-up demonstrated |
| 3 | Outbound adapter protocol, webhook and deterministic spreadsheet/PDF export | Exact-plan and receipt verification tests pass |
| 4 | Jira or equivalent work-management adapter, policy-authorized automation | Duplicate and uncertain-delivery cases pass |
| 5 | Enterprise identity, tenancy, secret management, queue scaling, retention, backup and recovery | Independent security and recovery review |

Additional providers should be added only in response to validated customer
requirements. A broad connector catalog is not a substitute for correct
identity, trust, and action boundaries.

## 17. Acceptance criteria

1. Two different inbound adapters produce equivalent canonical events for
   equivalent source material.
2. Duplicate or replayed provider deliveries create no duplicate canonical
   episode or external effect.
3. A verified sender is recorded as authenticated origin without automatically
   promoting model-derived claims.
4. An unavailable model does not prevent durable intake.
5. A human-approved and a policy-approved operation both carry an exact plan,
   authority evidence, destination receipt, and postcondition result.
6. Spreadsheet and PDF exports can be reconstructed from the approved record
   set and their manifests verify against stored digests.
7. Webhook timeouts and ambiguous provider results become `uncertain` and are
   not blindly retried.
8. A caller cannot select another tenant or workspace by supplying a different
   `scope_id` or `subject_id`.
9. Local deletion and external deletion are reported as separate operations
   with separate receipts.
10. Core tests contain no provider names or business-domain vocabulary.
11. Core installs and runs without Channels or Outbound dependencies, and the
    existing Python, CLI, MCP, and agent-integration memory contract remains
    backward compatible.

## 18. Open decisions

1. Whether channels and outbound ship as optional Python distributions or as
   separately deployed services.
2. The enterprise identity and secret-manager integrations to support first.
3. The canonical attachment encryption and retention envelope.
4. The policy language for pre-authorized outbound operations.
5. Whether event delivery uses an internal durable queue immediately or begins
   with a single-node SQLite-backed worker model.
6. Which channel and outbound destination are justified by the first design
   partners.
