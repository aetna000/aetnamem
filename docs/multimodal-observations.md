# Governed memory for multimodal agents

AetnaMem does not need to see or store image, audio, video, or document bytes.
The multimodal host or model observes the artifact; AetnaMem stores a validated
text observation and the evidence envelope needed to govern, search, audit, and
delete that observation.

> **AetnaMem turns multimodal agent observations into governed, searchable,
> and auditable memory.**

This capability ships in Python `v0.5.2` and OpenClaw npm `v0.3.1`.

## The boundary

```text
host-controlled media bytes
        │
        ├── SHA-256 exact byte-stream digest
        │
multimodal extractor (Grok, OpenClaw/Hermes model, or another provider)
        │
        └── typed text observation + segment + extractor identity
                             │
                             ▼
                          AetnaMem
             quarantine → search → audit → promote/delete
```

AetnaMem stores:

- a first-class artifact row keyed by subject and exact-byte SHA-256;
- the first secretless host reference admitted for that digest, never the
  original bytes;
- one record and one evidence envelope per observation;
- segment, extractor provider/model/version, optional model digest, and
  extractor-local confidence;
- lineage and envelope hashes, supersession, and audit-chain events.

AetnaMem does not:

- caption, transcribe, OCR, or embed the original media;
- fetch or delete the host's original file;
- treat two re-encodings as the same artifact;
- let an extractor confidence score promote a record;
- treat an observation as action authority.

## Python

```python
from aetnamem import Memory

memory = Memory("memory.db")
result = memory.remember_observation(
    "user-42",
    {
        "text": "The receipt shows a total of $42.",
        "modality": "image",
        # Replace with SHA-256 of the exact file bytes:
        "media_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "host_reference": "openclaw://media/receipt-1",
        "segment": {"region": "x=10,y=20,w=300,h=80"},
        "extractor": {
            "provider": "xai",
            "model": "grok-vision",
            "version": "2026-07",
            # optional: "model_digest": "<64 hex characters>"
        },
        "confidence": 0.86,
    },
    session_id="session-7",
)
```

Admission deterministically creates exactly one `quarantined` memory record.
The caption does not need to match AetnaMem's ordinary fact-extraction grammar.
Show the observation to the user or apply host policy before calling
`promote()`.

The same artifact + segment + extractor identity defines an extraction
lineage. A new result in that lineage supersedes an older quarantined
observation. Observations from different extractors accumulate. A newer
untrusted extraction never deactivates an already promoted record. If the
newer observation is explicitly promoted, that promotion supersedes older
active records from the same lineage so recall does not surface two accepted
versions. The promotion event names the record and observation IDs it
superseded.

Digest assurance is deliberately asymmetric:

- `caller_asserted` is the default and is forced by CLI and generic MCP;
- `host_asserted` is available to an embedded host that owns the byte-digest
  boundary;
- `verified_by_aetnamem` is reserved and currently rejected on every
  observation path because AetnaMem does not yet hash media bytes itself.

A future stream/file observation helper may legitimately produce
`verified_by_aetnamem`. Accepting that label from an envelope would be
self-certification and therefore fails closed today.

An artifact currently retains its first host reference. If identical bytes
are later observed at another host location, the observation audit evidence
retains the submitted reference digest, but the artifact row is not rewritten
and is not a multi-location registry. A future location table can add that
behavior without changing exact-byte artifact identity.

The CLI accepts the same object from a file or standard input and marks its
digest claim `caller_asserted`:

```bash
aetnamem observe memory.db user-42 --envelope observation.json
aetnamem observe memory.db user-42 --envelope - < observation.json
```

## MCP, OpenClaw, and Hermes

`memory_observe` accepts the same typed fields. Generic MCP always labels its
digest claim `caller_asserted`; a model cannot claim that AetnaMem or a trusted
host verified the bytes.

The OpenClaw plugin exposes:

- `aetnamem_observe` after OpenClaw has analyzed media;
- `aetnamem_forget_artifact` after an explicit user deletion request.

The plugin does not infer media provenance from unstable hook internals. The
host supplies the digest, reference, and extractor identity explicitly.
Hermes discovers the underlying `memory_observe` and
`memory_forget_artifact` tools through its existing MCP connection.

## Search and trace

Ordinary `memory_list`, recall results, and audit-investigation memory results
carry a `media_observation` object when applicable. Investigator search also
has a dedicated `media` scope:

```bash
aetnamem search "red bicycle" --scope media --format text
aetnamem search "grok-vision" --scope all --format json --output evidence.json
aetnamem trace "red bicycle" --format text --output trace.txt
```

The trace links:

```text
artifact → observation → episode → quarantined/promoted memory → recall
         → context/action/outcome events when present
```

Semantic investigation search continues to embed only canonical text records.
Media provenance travels with the validated result; AetnaMem does not create
media embeddings in this implementation.

## Exact-artifact deletion

```python
result = memory.forget_artifact(
    "user-42",
    media_sha256="<64 hex characters>",
    artifact_id="media_...",  # optional second, matching identifier
)
```

The equivalent terminal operation is:

```bash
aetnamem forget-artifact memory.db user-42 <64-hex-sha256>
```

The indexed artifact relationship resolves every derived observation and
record. AetnaMem purges record and episode content, graph derivatives, and
registered semantic-index vectors before tombstoning the provenance metadata.
As with ordinary AetnaMem deletion, immutable audit evidence and tombstones
retain identifiers and cryptographic digests needed to verify what happened;
they do not retain the observation text, extractor metadata, segment, or host
reference.
The returned `aetnamem-artifact-deletion-receipt-v1` states:

- the digest names one exact byte stream;
- which observation, record, episode, graph, and vector objects were covered;
- whether absence checks succeeded;
- that the host file was **not** deleted;
- that a resized, transcoded, or otherwise re-encoded copy has another digest.

That is deliberately narrower and more verifiable than claiming that AetnaMem
forgot everything conceptually learned from “the same image.”
