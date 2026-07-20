# Specification: Governed Memory for Inference Engineering

Status: **draft / application proposal**
Author: **aetna000.com**
Scope: an optional inference-engineering SDK and reference application built
on `aetnamem-core`

---

## 1. Purpose

Inference engineers repeatedly evaluate how a trained model should run under a
particular workload, hardware environment, quality requirement, and cost or
latency objective. The numerical results may live in benchmark files, metrics
systems, experiment trackers, notebooks, and deployment platforms, while the
reason a configuration was selected is often left in chat, a pull request, or
an engineer's memory.

This specification defines a governed decision-memory layer that connects:

```text
hypothesis -> run -> evidence -> comparison -> decision -> deployment -> outcome
```

It lets a team reconstruct what was tested, whether the runs were comparable,
why a choice was approved, what it superseded, and what happened after
deployment.

The application does not make inference faster itself. It makes inference
engineering decisions durable, reviewable, and independently auditable.

## 2. Product boundary

```text
Serving engines / model registries / inference APIs / benchmark tools
                  / metrics systems / experiment trackers
                                  |
                                  v
                 inference adapters and importers
          resolve models and targets; normalize evidence
                                  |
                                  v
                         aetnamem-core
        provenance, trust, recall, lifecycle, audit, approval
                                  |
                                  v
                    aetnamem-outbound (optional)
          reports / issues / pull requests / deployment APIs
```

### 2.1 `aetnamem-core` owns

- canonical episodes and governed records;
- trust, quarantine, promotion, supersession, and deletion;
- deterministic retrieval and graph-path evidence;
- audit events and externally anchorable checkpoints;
- exact-plan approval and guarded effects;
- encryption, backup, restore, and verification contracts.

Core must not contain inference metric names, hardware schemas, serving-engine
flags, benchmark formats, or deployment-provider logic.

### 2.2 The inference application owns

- run, model, workload, environment, and artifact references;
- inference-target references and governed execution receipts;
- metric summaries and quality gates;
- comparison eligibility and deterministic ranking;
- engineering decisions and incident findings;
- inference-specific views, commands, and SDK objects;
- adapters for model registries, inference targets, benchmarks, metrics, and
  deployment systems.

Application rows reference Core episode, record, audit-event, and action IDs.
They do not redefine Core trust or authority semantics.

### 2.3 Existing agent memory remains independent

The inference application is optional. Installing or using it must not change
the existing Python, CLI, MCP, Grok/xAI, OpenClaw, or other direct agent-memory
interfaces. An AI assistant can use `aetnamem-core` without creating an
inference workspace, and an inference workspace can use Core without enabling
Channels or Outbound.

## 3. Non-goals

The first release is not:

- an inference runtime, compiler, scheduler, kernel library, or load balancer;
- a transparent proxy that hides which provider, endpoint, or model revision
  handled a request;
- a replacement for an experiment tracker or time-series metrics store;
- a benchmark generator or automatic parameter optimizer;
- a storage location for unrestricted request traces or large tensor data;
- an autonomous system that selects and deploys a model without authority;
- a post-training pipeline;
- a claim that two runs are comparable merely because they share a model name.

## 4. Users and responsibilities

| Actor | Responsibility | Authority |
|---|---|---|
| Inference engineer | Registers hypotheses, runs, evidence, and proposed conclusions | May ingest and propose |
| Reviewer or technical lead | Reviews comparisons, accepts decisions, grants exceptions | May promote and approve |
| Benchmark importer | Normalizes external run artifacts | Ingest only |
| Analysis model | Drafts summaries or identifies possible anomalies | Derived output only |
| Deployment adapter | Prepares and executes an approved change | Exact approved plan only |
| Auditor | Reconstructs evidence and verifies integrity | Read and verify only |

An authenticated engineer is authoritative about what they observed or
decided, not automatically about the correctness of an imported metric or a
model-generated conclusion.

## 5. Daily workflow

### 5.1 Define the workload and objectives

The engineer records:

- the service or use case being optimized;
- input and output length distributions;
- concurrency or request-rate profile;
- streaming and batching behavior;
- latency, throughput, cost, memory, power, or availability objectives;
- mandatory quality and correctness gates;
- the representative workload or dataset digest.

### 5.2 Establish a baseline

The current accepted configuration is registered as a baseline with model,
tokenizer, runtime, hardware, workload, and environment commitments. A
baseline is not inferred from whichever run happened most recently.

### 5.3 Run experiments

External tools execute the benchmarks. Importers register immutable run
manifests, metric summaries, and artifact references in Aetnamem. Repeated
deliveries are idempotent. Alternatively, a target adapter may dispatch the
inference request and attach a governed execution receipt to the run. The
adapter delegates execution to the selected local runtime or remote service;
it does not implement inference itself.

### 5.4 Compare candidates

The application first checks comparability and required quality gates. It then
applies a versioned deterministic objective to eligible runs. An analysis model
may explain the table but cannot change eligibility, ranking, or lifecycle.

### 5.5 Approve an engineering decision

The engineer proposes a conclusion. A reviewer may accept it, reject it,
request more evidence, or approve a documented comparability exception. An
accepted decision supersedes the previous decision for the same decision key;
history is never overwritten.

### 5.6 Deploy and observe

An optional outbound adapter stages the exact configuration change. Human or
narrow policy authority approves the plan. The adapter revalidates, executes,
observes postconditions, and records a receipt. A canary failure, rollback, or
ambiguous provider response becomes an explicit outcome.

### 5.7 Investigate incidents

During an incident, the engineer can recall the accepted configuration, prior
experiments, recent changes, known invalid runs, and decision rationale. New
findings cite the incident evidence and remain proposals until reviewed.

## 6. Canonical objects

These are application-owned objects. Field names are normative for the first
SDK version but are not added to Core tables.

### 6.1 `ModelArtifactRef`

```json
{
  "schema_version": "aetnamem.inference.model-ref.v1",
  "model_id": "model-family/release-id",
  "weights_sha256": "...",
  "tokenizer_sha256": "...",
  "model_config_sha256": "...",
  "quantization": {
    "weights": "none",
    "activations": "none",
    "kv_cache": "none"
  },
  "source_uri": "artifact-reference",
  "source_revision": "immutable-revision"
}
```

A mutable name such as `latest` is insufficient. If a source cannot provide a
content digest, the application records the strongest immutable revision
available and marks identity assurance accordingly.

### 6.2 `WorkloadRef`

```json
{
  "schema_version": "aetnamem.inference.workload-ref.v1",
  "workload_id": "interactive-long-context-v3",
  "dataset_sha256": "...",
  "generator_version": "workload-generator-v2",
  "sample_count": 1000,
  "input_tokens": {"p50": 900, "p95": 4000, "max": 8192},
  "output_tokens": {"p50": 180, "p95": 700, "max": 1024},
  "request_pattern": {"mode": "concurrency", "value": 32},
  "contains_sensitive_data": false
}
```

### 6.3 `EnvironmentRef`

```json
{
  "schema_version": "aetnamem.inference.environment-ref.v1",
  "hardware": [{"type": "accelerator", "model": "device-class", "count": 4}],
  "host_cpu": "cpu-class",
  "host_memory_bytes": 274877906944,
  "driver_version": "version",
  "runtime_name": "serving-runtime",
  "runtime_version": "immutable-version",
  "container_digest": "sha256:...",
  "topology_sha256": "...",
  "environment_sha256": "..."
}
```

Secrets and unrestricted environment-variable dumps are prohibited.

### 6.4 `InferenceTargetRef`

```json
{
  "schema_version": "aetnamem.inference.target-ref.v1",
  "target_id": "target_...",
  "mode": "local_runtime",
  "adapter": {"name": "adapter-name", "version": "immutable-version"},
  "protocol": "provider-protocol",
  "endpoint_ref": null,
  "endpoint_security": "local",
  "region": null,
  "provider_policy": "explicit",
  "requested_provider": null,
  "credential_binding_id": null,
  "request_data_policy_id": "local-private-v1",
  "target_config_sha256": "..."
}
```

Target mode is `local_runtime`, `provider_api`, `dedicated_endpoint`, or
`customer_endpoint`. `endpoint_ref` is a secretless logical identifier, not a
credential-bearing URL. `credential_binding_id` identifies a host-managed
secret binding but cannot reveal the secret. The target commitment includes
timeouts, retry policy, generation defaults, endpoint class, region, and any
other option that can change execution behavior.

### 6.5 `InferenceRun`

```json
{
  "schema_version": "aetnamem.inference.run.v1",
  "run_id": "run_...",
  "scope_id": "org/workspace/service",
  "hypothesis": "Increasing the token budget improves throughput within the TTFT SLO",
  "created_by": "principal-123",
  "created_at": "2026-07-19T10:00:00Z",
  "status": "registered",
  "model_ref_sha256": "...",
  "workload_ref_sha256": "...",
  "environment_ref_sha256": "...",
  "target_ref_sha256": "...",
  "serving_config_sha256": "...",
  "benchmark_config_sha256": "...",
  "command_sha256": "...",
  "invocation_artifact_id": "art_...",
  "source_revision": "git-commit-or-equivalent",
  "repetition": 1,
  "warmup_policy": "policy-id",
  "run_identity_sha256": "...",
  "execution_resolution_sha256": null,
  "artifact_ids": [],
  "metric_summary_ids": []
}
```

`run_identity_sha256` is computed from the immutable model, workload,
environment, inference target, serving configuration, benchmark
configuration, invocation, source revision, repetition, and warmup-policy
fields. Mutable lifecycle state and later artifact or metric attachments are
excluded. The invocation artifact retains the exact structured command or
request needed for reproduction; `command_sha256` commits it without placing
potentially sensitive arguments in the audit payload.

Before measured requests begin, the adapter records an immutable execution
resolution: requested and resolved model identity, model revision when the
provider exposes it, resolved provider and endpoint class, adapter version,
and route metadata allowed by policy. `execution_resolution_sha256` commits
that object. If a provider does not disclose a field, its value is `unknown`;
the application must not infer it. A run with unresolved identity or routing
may be useful operational evidence but is ineligible for a strict comparison
that controls that dimension.

Run status is one of:

```text
registered -> running -> completed
                    \-> failed
completed -> invalidated
```

An invalidated run is retained with a reason and is excluded from normal
comparison. Status transitions are append-only audit events.

### 6.6 `BenchmarkArtifact`

```json
{
  "schema_version": "aetnamem.inference.artifact.v1",
  "artifact_id": "art_...",
  "run_id": "run_...",
  "kind": "benchmark-results",
  "uri": "artifact-store-reference",
  "sha256": "...",
  "bytes": 483902,
  "media_type": "application/json",
  "producer": "benchmark-adapter-id",
  "producer_version": "version"
}
```

Large artifacts remain in a local or external artifact store. Aetnamem retains
their immutable identity, provenance, selected summaries, and availability
state. A missing artifact is reported as missing rather than silently ignored.

### 6.7 `MetricSummary`

```json
{
  "schema_version": "aetnamem.inference.metric-summary.v1",
  "metric_summary_id": "met_...",
  "run_id": "run_...",
  "name": "time_to_first_token",
  "statistic": "p99",
  "value": 248.4,
  "unit": "ms",
  "sample_count": 1000,
  "measurement_window_seconds": 300,
  "source_artifact_id": "art_...",
  "normalizer_version": "metrics-normalizer-v1"
}
```

Missing is distinct from zero. Units are normalized for comparison while the
original values remain available in the cited artifact.

### 6.8 `Comparison`

```json
{
  "schema_version": "aetnamem.inference.comparison.v1",
  "comparison_id": "cmp_...",
  "baseline_run_id": "run_...",
  "candidate_run_ids": ["run_..."],
  "comparability_policy": "strict-v1",
  "objective_policy": "online-latency-v1",
  "quality_gate_policy": "quality-v2",
  "eligible_run_ids": [],
  "excluded_runs": [{"run_id": "run_...", "reasons": ["workload_mismatch"]}],
  "ranking": [],
  "input_digest": "...",
  "result_digest": "..."
}
```

### 6.9 `EngineeringDecision`

Implementation should use the generic artifact/revision, ballot, adoption,
approval, and authorization contracts in
[decision-workflow-spec.md](decision-workflow-spec.md) rather than introducing
a second decision state machine. The JSON below remains the inference-profile
content carried by a decision artifact revision.

```json
{
  "schema_version": "aetnamem.inference.decision.v1",
  "decision_id": "dec_...",
  "decision_key": "service-a/production-serving-configuration",
  "status": "proposed",
  "proposal": "Adopt candidate configuration B",
  "rationale": "Meets quality gates and improves throughput within the TTFT SLO",
  "comparison_id": "cmp_...",
  "evidence_run_ids": ["run_..."],
  "proposed_by": "principal-123",
  "reviewed_by": null,
  "supersedes_decision_id": null
}
```

Decision status is `proposed`, `accepted`, `rejected`, `needs_evidence`,
`superseded`, or `withdrawn`.

### 6.10 `DeploymentChange`

A deployment change references one accepted decision, one exact prepared plan,
authority evidence, preconditions, postconditions, and the guarded-action
transaction and receipt IDs. Deployment state uses the existing action-engine
states rather than introducing a second execution state machine.

### 6.11 `IncidentFinding`

An incident finding references observed metrics, relevant deployment changes,
run or decision IDs, a confidence annotation, and a lifecycle state. A
model-generated root-cause suggestion is derived and quarantined until a human
accepts it.

## 7. Comparability and ranking

### 7.1 Strict comparability

By default, candidate runs must match the baseline on:

- model and tokenizer identity, unless model choice is the experiment;
- target mode, resolved provider, endpoint class, and model-revision assurance,
  unless one of those is the declared independent variable;
- workload and dataset digest;
- request pattern and sample-count minimum;
- hardware class and accelerator count;
- serving-runtime major version;
- warmup and measurement policy;
- required metric definitions and normalizer versions;
- quality-evaluation policy.

The comparison declares which dimensions are controlled and which are the
intentional independent variables. Every other mismatch excludes the run.

### 7.2 Exceptions

A reviewer may approve a specific mismatch for an exploratory comparison.
The exception records the mismatched dimensions, rationale, reviewer, and
policy version. Exception results are visibly labeled and cannot silently
replace a strict production baseline.

### 7.3 Quality gates

Quality and correctness gates execute before performance ranking. A run that
fails a mandatory gate is ineligible even when it is faster or cheaper.
Unknown or missing gate results fail closed unless the policy explicitly
allows exploratory comparison.

### 7.4 Deterministic objective

An objective policy contains ordered constraints and one optimization target,
for example:

```json
{
  "policy_id": "online-latency-v1",
  "constraints": [
    {"metric": "time_to_first_token", "statistic": "p99", "op": "<=", "value": 300, "unit": "ms"},
    {"metric": "inter_token_latency", "statistic": "p99", "op": "<=", "value": 40, "unit": "ms"}
  ],
  "optimize": {"metric": "output_token_throughput", "direction": "max"},
  "tie_breakers": ["lower_cost", "lower_memory", "run_id"]
}
```

The application recalculates eligibility and ranking from stored metric
summaries. Model prose never determines the winner.

## 8. Trust, confidence, and ambiguity

- Imported metrics carry adapter and artifact provenance; they are not trusted
  solely because they are numeric.
- Engineer-authored hypotheses and notes are attributed observations, not
  measured results.
- Analysis-model summaries are derived and quarantined.
- Accepted engineering decisions require reviewer authority or an explicit
  organization policy.
- Run validity is separate from decision confidence.
- Evidence strength is computed from declared completeness, repetitions,
  variability, and artifact availability; it is not an LLM confidence score.
- Conflicting runs remain visible. The application does not average across
  incompatible environments to hide disagreement.
- A provider timeout or missing artifact becomes `unknown` or `uncertain`, not
  success or zero.

## 9. SDK surface

The first SDK is synchronous and typed, matching the existing embedded Core.
A remote client may provide equivalent asynchronous methods later.

### 9.1 Required generic Core extension

The application must not write Core tables directly. Core therefore needs a
small source-agnostic admission API for structured applications:

```python
episode = core.memory.ingest_episode(
    subject_id=scope_id,
    content=human_readable_source,
    source_type="application_event",
    actor=principal_id,
    raw=committed_metadata,
    idempotency_key=external_event_id,
)

proposal = core.memory.propose_record(
    subject_id=scope_id,
    episode_id=episode.id,
    content=proposed_conclusion,
    source_type="derived",
    fact_key=decision_key,
    metadata_sha256=application_object_digest,
)
```

`ingest_episode` records authenticated provenance but does not equate source
identity with factual correctness. `propose_record` always creates a
quarantined record and cannot supersede active state until the normal Core
promotion path supplies reviewer authority. These verbs are generic enough for
other structured applications and contain no inference vocabulary.

### 9.2 Inference workspace

```python
from aetnamem import Aetnamem
from aetnamem_inference import InferenceWorkspace, RunManifest

core = Aetnamem.local()
workspace = InferenceWorkspace(core=core, scope_id="org/service-a")

run = workspace.runs.register(RunManifest(...))
workspace.runs.attach_artifact(run.id, artifact=...)
workspace.runs.record_metrics(run.id, metrics=[...])
workspace.runs.complete(run.id)

comparison = workspace.comparisons.create(
    baseline_run_id="run_baseline",
    candidate_run_ids=[run.id],
    objective_policy="online-latency-v1",
)

decision = workspace.decisions.propose(
    decision_key="service-a/production-serving-configuration",
    comparison_id=comparison.id,
    proposal="Adopt candidate configuration B",
)
workspace.decisions.accept(decision.id, reviewer="principal-lead")
```

The same workspace exposes a provider-neutral execution facade. An invocation
can stand alone for interactive use or attach its receipt to a registered run:

```python
model_ref = workspace.models.resolve(
    registry="huggingface",
    model_id="organization/model",
    revision="full-commit-hash",
)

result = workspace.inference.generate(
    model=model_ref,
    target=target_ref,
    request={"messages": [{"role": "user", "content": "Summarize this run"}]},
    capture_policy="digests-and-metrics-v1",
    run_id=run.id,
)
```

The result includes an execution ID, resolution commitment, usage and timing
fields when available, response digest, and optional encrypted payload-artifact
reference. A capture policy determines whether request and response bodies are
discarded, retained as digests only, or stored as encrypted artifacts. Raw
content never enters the audit payload. Streaming calls commit chunks
incrementally and finish with one receipt; a disconnected or incomplete
stream is recorded as partial rather than successful.

Required services:

```text
workspace.runs
workspace.models
workspace.targets
workspace.inference
workspace.artifacts
workspace.comparisons
workspace.decisions
workspace.deployments
workspace.incidents
workspace.recall
workspace.verify
```

## 10. Adapter contracts

### 10.1 Benchmark importer

```python
class BenchmarkImporter(Protocol):
    name: str

    def manifest(self) -> dict:
        """Versioned adapter capabilities and supported input formats."""

    def inspect(self, source: ArtifactSource) -> ImportPreview:
        """Parse without committing and report missing required fields."""

    def normalize(self, source: ArtifactSource) -> NormalizedRunBundle:
        """Return canonical references, metrics, and artifact commitments."""
```

V1 should ship a documented canonical JSON importer before provider-specific
importers. This gives every tool a stable integration target.

### 10.2 Metrics source

A metrics adapter may snapshot selected values from a monitoring system. It
must record query digest, query window, source identity, retrieval time, and
result artifact digest. It must not copy unrestricted production traces by
default.

### 10.3 Artifact store

```python
class ArtifactStore(Protocol):
    def put(self, source: Path, *, media_type: str) -> ArtifactRef: ...
    def verify(self, artifact: ArtifactRef) -> VerificationResult: ...
    def open(self, artifact: ArtifactRef) -> BinaryIO: ...
    def delete(self, artifact: ArtifactRef) -> DeletionResult: ...
```

The first implementation may use a local content-addressed directory. Remote
object storage is an optional adapter.

### 10.4 Deployment adapter

Deployment integrations implement `aetnamem-outbound` guarded actions. V1 may
prepare a configuration file or pull-request artifact without directly
changing production. Direct deployment requires stronger identity,
precondition, rollback, and postcondition support.

### 10.5 Model-registry adapter

```python
class ModelRegistryAdapter(Protocol):
    name: str

    def search(self, query: ModelQuery) -> ModelPage: ...

    def resolve(
        self, model_id: str, revision: str | None
    ) -> ResolvedModelSource:
        """Resolve mutable input to the strongest immutable source identity."""

    def materialize(
        self, source: ResolvedModelSource, destination: Path
    ) -> ModelSnapshot:
        """Download and verify a local snapshot when requested."""
```

Search is a convenience, not evidence of model quality or safety. Resolution
returns access and license metadata, the immutable revision when available,
and identity-assurance limits. Materialization is optional because a remote
target may need only the resolved source reference. Registry credentials use
the same host secret-binding rules as target credentials.

### 10.6 Inference-target adapter

```python
class InferenceTargetAdapter(Protocol):
    name: str

    def manifest(self) -> dict:
        """Versioned tasks, streaming support, and identity guarantees."""

    def health(self, target: InferenceTargetRef) -> TargetHealth: ...

    def resolve(
        self, model: ModelArtifactRef, target: InferenceTargetRef
    ) -> ExecutionResolution:
        """Resolve the actual route without exposing credentials."""

    def generate(
        self, resolution: ExecutionResolution, request: InferenceRequest
    ) -> InferenceResponse:
        """Execute one request and return evidence for a governed receipt."""
```

An adapter declares the tasks it actually supports. The first API surface
should cover chat completion and text generation, with ordinary and streaming
responses. Image, audio, embedding, and training tasks are out of scope until
their request, artifact, and retention contracts are defined. Retries are
recorded as attempts under one execution ID; they are never hidden from cost,
latency, or reliability evidence.

### 10.7 Hugging Face reference integration

Hugging Face is the first registry and remote-inference integration, not a
Core dependency or a product-level naming constraint. It is an optional extra:

```text
pip install "aetnamem-inference[huggingface]"
```

The adapter supports three execution modes through the same workspace API:

| Mode | Model source | Execution location | Required identity evidence |
|---|---|---|---|
| Hub snapshot plus local runtime | Hugging Face Hub | User-selected local runtime | Full Hub commit, file-manifest digest, runtime and environment digests |
| Inference Providers API | Hub model ID | Explicit remote provider selected through the Hugging Face client | Requested model, explicit provider, returned model and route metadata when available |
| Dedicated or customer endpoint | Endpoint configuration | Managed or customer-controlled endpoint | Endpoint alias, security class, region, deployed revision/config digest, adapter version |

#### Local Hub execution

The adapter resolves a repository revision to a full commit hash and downloads
that immutable snapshot into a content-addressed cache. It records a sorted
manifest of file paths, sizes, and digests; a mutable branch or tag alone
cannot identify a strict benchmark. Offline execution may reuse a previously
verified snapshot. Aetnamem then delegates execution to an installed runtime
adapter such as Transformers, vLLM, or llama.cpp; downloading a model does not
make Aetnamem an inference engine.

Loading repository-supplied executable code is disabled by default. A model
that requires remote code needs an explicit policy exception, a pinned commit,
and an isolated execution environment. License or access acceptance is the
user's responsibility and is recorded as policy metadata, not inferred from
successful download.

#### Inference Providers API

The reference adapter uses `huggingface_hub.InferenceClient`; an
OpenAI-compatible client may be used where the service exposes that protocol.
For strict benchmarks, the provider and model are explicit. Automatic provider
selection is allowed for exploratory or availability-oriented inference only.
If automatic routing or failover occurs, the adapter records the resolved
provider from authoritative response metadata; when that metadata is not
available, the route is `unknown` and the run cannot enter a comparison that
controls provider identity.

#### Dedicated and customer endpoints

The target records a secretless endpoint alias, deployed model or revision,
region, endpoint security class, scaling policy, and configuration digest.
Sensitive workloads must satisfy the workspace's endpoint-security, region,
and data-residency policy before dispatch. Scale-to-zero initialization,
capacity rejection, and cold-start retries are classified separately from
model-quality failures and are retained in latency and reliability evidence.

#### Seamless setup

The intended command flow is:

```text
aetnamem inference connect huggingface
aetnamem inference doctor huggingface
aetnamem inference model add organization/model --revision <full-commit>
aetnamem inference run --model organization/model --target local
aetnamem inference run --model organization/model --target hf-provider \
  --provider <explicit-provider>
```

`connect` stores a token in the operating-system or configured enterprise
secret store and writes only a non-secret binding ID to Aetnamem. Public model
downloads require no token. Tokens are never accepted as ordinary manifest
fields, command arguments, audit values, artifact contents, or exception text.
`doctor` checks authentication, model access, endpoint health, adapter version,
and local cache capacity without issuing a billable generation request unless
the user explicitly asks for an end-to-end probe.

These behaviors follow the official Hugging Face contracts for
[Hub snapshot downloads](https://huggingface.co/docs/huggingface_hub/guides/download),
[Inference Providers](https://huggingface.co/docs/inference-providers/en/index),
and [Inference Endpoint security](https://huggingface.co/docs/inference-endpoints/en/security).

## 11. Audit events

The inference application appends the following event families to the same
per-scope Core audit chain:

```text
inference.run_registered
inference.run_started
inference.execution_resolved
inference.execution_attempted
inference.execution_completed
inference.execution_partial
inference.execution_failed
inference.artifact_attached
inference.metrics_recorded
inference.run_completed
inference.run_failed
inference.run_invalidated
inference.comparison_created
inference.comparison_exception_approved
inference.decision_proposed
inference.decision_accepted
inference.decision_rejected
inference.decision_superseded
inference.deployment_staged
inference.deployment_observed
inference.incident_opened
inference.finding_proposed
inference.finding_accepted
inference.incident_resolved
```

Audit payloads contain identifiers, versions, statuses, and digests rather
than raw prompts, benchmark files, secrets, or production traces. Selected
application fields require a versioned digest envelope so an independent
verifier can reconstruct run identity, comparison eligibility, ranking, and
decision provenance.

## 12. Retrieval questions

The application should answer questions such as:

- What is the accepted serving configuration for this service?
- Why was it selected and what did it supersede?
- Which runs support the decision?
- Were those runs comparable to the baseline?
- Which local runtime, provider, or endpoint actually executed each request?
- Was the model tied to an immutable revision, or is its identity incomplete?
- Which quality gates were applied?
- Which configurations were rejected, and why?
- When did the latency regression begin relative to deployment changes?
- Which conclusions are proposed rather than accepted?
- Is the cited raw artifact still available and digest-valid?

Answers return records plus structured evidence. Generated narrative is
optional and never replaces the evidence response.

## 13. Storage and retention

- Core records, decisions, lifecycle events, and audit evidence use the
  configured Core store.
- Application objects use an application repository sharing the same unit of
  work where atomic decision and audit transitions are required.
- Raw benchmark files and large traces use the artifact store.
- Downloaded model snapshots use the registry or runtime cache and are tracked
  by immutable revision and manifest digest; model bytes are not copied into
  Core records.
- Time-series data remains in the metrics system and is referenced through
  committed snapshots.
- Local mode uses encrypted SQLite and encrypted local artifacts when that
  storage work is complete.
- Server mode may use PostgreSQL and an encrypted object store after backend
  contract parity is established.

Retention policy distinguishes run metadata, decisions, raw artifacts,
production traces, and deployment receipts. Deleting local evidence does not
claim to delete copies in an experiment tracker, metrics system, object store,
source repository, or deployment platform. External deletion is a separately
authorized operation with its own receipt.

## 14. Security and privacy

- Scope and principal identity are derived by an authenticated host.
- Adapter credentials come from an OS or enterprise secret store.
- Provider tokens are represented only by non-secret credential-binding IDs
  and are redacted from structured logs and exception chains.
- Artifact URIs are treated as sensitive references and are not automatically
  injected into model prompts.
- Importers enforce size, media-type, parser-depth, and decompression limits.
- Production request content is excluded unless an approved data policy
  explicitly permits it.
- Remote dispatch is denied before network access when model access terms,
  endpoint security, region, retention, or data-residency policy is unknown or
  incompatible with the workload.
- Provider redirects and automatic failover cannot silently weaken the target
  policy; the resolved route is recorded or the result remains uncertain.
- Model-generated analysis receives only the minimum approved evidence.
- A remote model call records provider, model, prompt version, data-policy
  decision, and output digest.
- Deployment changes require complete mediation at the deployment boundary;
  direct shell or platform access can bypass the application.
- Encryption protects stored data but does not prove benchmark correctness or
  deployment authority.

## 15. User interface

The reference application contains five compact operational views:

1. **Runs:** status, model, workload, environment, key metrics, artifact state.
2. **Comparisons:** baseline, candidates, exclusions, quality gates, ranking.
3. **Decisions:** proposal, evidence, review state, supersession history.
4. **Deployments:** prepared plan, approval, execution, verification, rollback.
5. **Incidents:** timeline of metrics, changes, findings, and resolution.

Every decision and deployment provides a direct "why" view showing the
evidence path. Raw and generated text are visually distinguished. Missing,
invalid, quarantined, superseded, and uncertain states are never collapsed
into a generic warning.

## 16. Package layout

```text
packages/aetnamem_inference/
  __init__.py
  models.py
  targets.py
  execution.py
  repository.py
  runs.py
  comparisons.py
  decisions.py
  incidents.py
  policies/
    comparability.py
    objectives.py
    quality.py
  adapters/
    benchmark_json.py
    metrics.py
    artifacts.py
    huggingface.py
    deployment.py
  verifier.py

examples/inference_engineering/
  import_run.py
  run_huggingface_local.py
  run_huggingface_api.py
  compare_runs.py
  approve_decision.py
  incident_reconstruction.py
```

Dependency direction is one way:

```text
aetnamem-inference -> aetnamem-core
aetnamem-core -X-> aetnamem-inference
```

## 17. Delivery phases

| Phase | Scope | Gate |
|---|---|---|
| 0 | Structured proposal/admission API in Core, application repository contract, canonical serialization | Existing agent-memory tests remain unchanged and pass |
| 1 | Run, model, workload, environment, target, artifact, and metric objects; canonical JSON importer | Import is idempotent and artifact tampering is detected |
| 2 | Provider-neutral execution facade and Hugging Face local/API/endpoint reference adapter | Resolution, credential, streaming, retry, and data-policy conformance tests pass |
| 3 | Strict comparability, quality gates, objective policies, comparisons | Ranking is independently reproducible |
| 4 | Proposed/accepted/superseded decisions, recall views, standalone verifier | A decision reconstructs to its source artifacts and runs |
| 5 | Reports and issue/PR preparation through Outbound | Exact-plan approval and receipts pass conformance tests |
| 6 | Deployment observation, rollback evidence, incident workflow, selected metrics connectors | Failure and ambiguous-effect scenarios pass |

The first useful release ends after Phase 4. Direct production deployment is
not required to validate governed inference decision memory.

## 18. Acceptance criteria

1. Reimporting the same run bundle creates no duplicate run, metric, artifact,
   or audit event.
2. Changing any committed model, workload, environment, target, serving, or
   benchmark configuration changes the run identity digest.
3. Modifying a referenced artifact is detected before it is used as evidence.
4. A strict comparison excludes an undeclared model, workload, environment,
   runtime, or measurement-policy mismatch.
5. A comparability exception identifies the exact mismatch and reviewer and
   cannot silently replace a strict baseline.
6. A run that fails or lacks a mandatory quality gate cannot win a production
   objective.
7. Ranking is independently recalculated from stored normalized metrics and
   the versioned objective policy.
8. A model-generated summary remains derived and cannot accept a decision.
9. Accepting a decision records reviewer authority and supersedes, rather than
   overwrites, the prior accepted decision for the same key.
10. A deployment proposal binds the accepted decision, exact configuration,
    adapter manifest, preconditions, authority, and postconditions.
11. A timeout after external dispatch becomes `uncertain` and is not blindly
    retried.
12. A recalled decision resolves through comparison and run references to
    digest-valid source artifacts.
13. Deleting an artifact produces a scoped receipt and leaves no claim that
    external copies were deleted.
14. `aetnamem-core` installs and passes its existing direct agent-memory suite
    without inference-package dependencies or inference vocabulary.
15. A Hub branch or tag resolves to a full commit and verified file manifest
    before a local run becomes strict-comparison evidence.
16. A provider token never appears in an application object, command history,
    audit event, artifact, structured log, or returned exception.
17. Automatic provider selection is visibly exploratory unless the adapter
    records an authoritative resolved route satisfying the comparison policy.
18. Local, provider-API, and dedicated-endpoint calls produce the same
    provider-neutral execution receipt shape.
19. A dropped stream is `partial`; a cold start, capacity rejection, timeout,
    and model error remain distinguishable attempts.
20. A sensitive request is rejected before dispatch when the endpoint security
    or data-residency policy is insufficient or unknown.
21. Removing the Hugging Face extra leaves canonical import, comparison,
    decision, and direct Core memory behavior functional.

## 19. Initial success measures

The application is useful when a team can demonstrate that it:

- reconstructs an accepted configuration decision without relying on the
  original engineer's memory;
- identifies previously failed or invalid experiments before they are
  repeated;
- distinguishes comparable evidence from superficially similar runs;
- shortens incident reconstruction across metrics, changes, and decisions;
- produces an independently verifiable engineering-decision report.

Performance improvement is not itself an Aetnamem success metric. The product
is responsible for decision integrity and recovery, not for claiming credit
for the serving engine's speed.

## 20. Open decisions

1. Whether inference objects begin in application-owned SQLite tables or a
   generic structured-object extension store.
2. The minimum metric vocabulary and unit-normalization registry for V1.
3. The statistical requirements for repeated-run evidence strength.
4. Which quality-evaluation formats receive the first import adapters.
5. Whether an initial deployment adapter stops at a generated configuration or
   can prepare a pull request through Outbound.
6. Which fields enter the independently verified digest envelope.
7. Which existing experiment and metrics systems are justified by design
   partners after the canonical JSON importer is stable.
8. Which local runtime adapter ships first: Transformers, vLLM, or llama.cpp.
9. Which Hugging Face text-generation capabilities form the V1 conformance
   profile beyond chat, completion, and streaming.
10. Whether request and response capture defaults to digest-only or no
    retention for remote interactive inference.
