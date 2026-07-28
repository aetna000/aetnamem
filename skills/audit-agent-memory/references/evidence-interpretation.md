# Interpreting AetnaMem evidence

## Verification

`valid: true` means the stored hash chain recomputes correctly under the
implemented verifier. It does not authenticate the human identity asserted by
an untrusted caller and does not prove an external provider retained nothing.

## Trace sequence

A trace can show:

```text
source admitted → record created or quarantined → record promoted or corrected
→ retrieval event → context manifest → action or outcome event
```

The sequence is evidence of recorded operations. Unless a registered randomized
Memory Impact experiment supplies an intervention and trusted outcome, it does
not prove that the memory caused the outcome.

## Search modes

- `lexical`: inspectable token and FTS matches.
- `semantic`: embedding similarity from a pinned index epoch.
- `hybrid`: reciprocal-rank fusion of lexical and semantic nominations.

Semantic results must carry index/model evidence. Similarity is not truth,
authorization, or trust.

## Deletion

A deletion receipt defines its own coverage. Artifact deletion identifies one
exact byte stream by SHA-256 and AetnaMem derivatives linked to it. The host's
original file, re-encodings, copies, and backups are outside that boundary.

## Access logging

The audit wrapper supplies `--audit-access` and an asserted investigator actor.
An authenticated host should replace a free-form actor string with verified
identity. The access chain records a query digest, not the raw query.
