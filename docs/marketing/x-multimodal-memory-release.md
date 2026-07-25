# X article — Your AI agent heard it. But can it prove where the memory came from?

AI agents can now see images, hear voice notes, watch video, and read
documents.

But there is a missing step between **“the model noticed something”** and
**“the agent should remember it.”**

Imagine you send an agent this voice note:

> “Please remember: send my weekly reports as PDF.”

A speech or multimodal model can transcribe that sentence. Grok, an OpenClaw
model, Hermes, or another host can understand it.

The difficult questions come next:

- Which audio file did this memory come from?
- Which model and version extracted it?
- Was it approved, or did a confidence score silently make it trusted?
- Can an auditor find the complete trail later?
- If the user deletes that audio, which derived memories are removed?

That is what AetnaMem 0.5.2 is built to handle.

## A simple boundary

The host keeps the image, audio, video, or document.

The host's model analyzes it.

AetnaMem stores only a governed text observation and its evidence envelope:

- SHA-256 of the exact media bytes;
- a secretless reference to where the host keeps the artifact;
- modality and segment;
- extractor provider, model, version, and optional model digest;
- observed time and extractor-local confidence;
- approval, lineage, recall, audit, and deletion history.

AetnaMem is not trying to become another vision or speech model. It gives
multimodal observations a memory control plane.

## Confidence is not permission

An extractor might say it is 86% confident.

That number is useful evidence, but it is not trust. An 86% score from one
model is not necessarily comparable to 86% from another model.

So every new media observation starts quarantined. Confidence cannot promote
it, make it action authority, or improve its ranking. A user or trusted host
policy must approve it.

For the voice note, the flow is:

**audio → text observation → quarantine → approval → searchable memory**

## Search by meaning, investigate by evidence

Once approved, the preference can be recalled like normal text memory:

> Send weekly reports as PDF.

But an investigator can also follow the evidence:

**artifact → observation → episode → memory → recall → context/action/outcome**

That matters when an agent makes a decision and someone asks, “Why did it
believe this?”

## Deletion that says exactly what it did

AetnaMem can delete every indexed derivative associated with one artifact
digest:

- observations;
- memory records;
- episode content;
- graph derivatives;
- semantic-search vectors.

It verifies the live state and returns a receipt.

The receipt deliberately does **not** say, “We deleted the picture” or “We
deleted the audio.”

SHA-256 identifies one exact byte stream. A re-encoded copy has a different
digest. The host still controls the original file, its backups, and its
replicas.

The honest claim is:

> AetnaMem deleted its derived memory for exact artifact digest X. The host's
> original file remains host-controlled.

## What ships

AetnaMem 0.5.2 adds:

- governed multimodal observation envelopes;
- searchable media provenance;
- lineage-aware re-extraction and approval;
- exact-artifact deletion receipts;
- Python, CLI, and MCP support;
- native OpenClaw media-memory tools in plugin 0.3.1.

It stores no media bytes and creates no media embeddings. Text-only agents
continue to work as before.

Install:

```text
python3 -m pip install --upgrade aetnamem
```

For OpenClaw:

```text
openclaw plugins install npm:openclaw-memory-aetnamem@0.3.1 --pin
```

Watch the 37-second
[voice-memory demo](../assets/demos/aetnamem-voice-memory-short.mp4), then see
the implementation and documentation:

https://github.com/aetna000/aetnamem

**AetnaMem turns multimodal agent observations into governed, searchable, and
auditable memory.**
