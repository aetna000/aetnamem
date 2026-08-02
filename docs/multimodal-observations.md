# Multimodal observations

AetnaMem does not store or interpret media bytes. A multimodal host or model interprets an image, audio clip or video and submits a typed text observation envelope.

The envelope binds:

- modality and exact byte-stream SHA-256;
- host-controlled reference;
- observation text and segment identity;
- extractor provider, model and version;
- source/session identity and optional confidence;
- digest-assurance level.

The resulting record is quarantined by default. A reviewer sees the exact description that would become recallable and, where the OpenClaw host reference remains available and its digest verifies, the source image beside it. Approval promotes the text description—not the image bytes. Recall returns the description and provenance.

Confidence is evidence only. It never controls ranking or approval. A caller cannot self-assert `verified_by_aetnamem`; that assurance is reserved for a trusted path that actually hashes bytes.

Two extractors may create accumulating observations of the same artifact. A rerun of the same artifact, segment and extractor lineage supersedes only that lineage and never silently displaces a promoted fact.

```bash
aetnamem observe memories.db user-1 --envelope observation.json
aetnamem promote memories.db user-1 rec_123
aetnamem forget-artifact memories.db user-1 <64-character-sha256>
```

Forget-by-artifact deletes memories derived from that exact byte stream and returns a verified receipt. Re-encoded or resized copies have different digests. The original host file, copies, backups and provider logs remain outside AetnaMem's deletion boundary.
