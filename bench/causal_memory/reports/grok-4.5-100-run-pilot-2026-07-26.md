# Grok 4.5 Memory Impact pilot — 100-run evidence summary

Date: **2026-07-26**

Status: **exploratory pilot; registered schedule intentionally incomplete; no
held-out or general causal claim**

This is the compact public evidence summary for the corrected paid Grok CLI
recovery pilot described in the AetnaMem 0.6.0 release notes. The full signed
receipts and generated report are not committed to the source repository.
Their hashes are recorded below so an exported evidence bundle can be matched
to this release without treating this summary as the underlying evidence.

## What ran

- Agent: Grok CLI `grok 0.2.111 (94172f2aa4e5)`
- Model: `grok-4.5`
- Registered experiment: `memory-impact-v1`
- Registered schedule: 384 calls
- Deliberate pilot cap: 100 new calls
- Verified signed receipts: 100
- Complete balanced 16-arm blocks: 6
- Missing registered calls after the cap: 284
- Aborts and timeouts: 0

Every complete block presented all 16 combinations of working, semantic,
episodic and procedural memory. A host verifier, not Grok, checked the
workspace result and signed the outcome receipt.

## Observed pilot results

| Measure | Result |
|---|---:|
| Host-verified successes | 57 / 100 |
| All-four-memory arm | 6 / 6 |
| No-memory arm | 1 / 6 |
| Experimental provider cost | USD 8.3339928 |
| Corrected paid smoke cost | USD 0.016532 |
| Provider-reported tokens | 8,955,452 |
| Mean call latency | 24,282.94 ms |

Exploratory intent-to-treat plane estimates from the six complete blocks:

| Memory plane | Estimated success effect | 95% interval |
|---|---:|---:|
| Working | +0.1875 | -0.235672 to +0.610672 |
| Semantic | +0.1875 | -0.055450 to +0.430450 |
| Episodic | +0.020833 | -0.344847 to +0.386514 |
| Procedural | +0.1875 | +0.049631 to +0.325369 |
| Semantic × procedural | +0.208333 | -0.136219 to +0.552885 |

These are pilot estimates, not deployment recommendations. The intervals are
wide, the registered schedule is incomplete, and the policy was not frozen
and evaluated on held-out tasks.

## Integrity identifiers

| Artifact | SHA-256 |
|---|---|
| Protocol | `7d638fe5e0183b1949b41d0b15297da37327515aacbefc8ca2c3973f51bcb5e2` |
| Registered schedule | `595d594ade24ec5c5cc08f428718156942cc6fe66bcdf2748fbe0a6c7dcee0a5` |
| Seed commitment | `ae95e6d759355a4714dd460cb937572b6190b14bf1f101c585cf327e6e1189ec` |
| Grok executable | `e1fafdfffe14f339460befaf194360e8f90bfd02efe8a4f24cfa1c7aea657ffe` |
| Metrology record | `622987992c45e453ee4939cc4a9a10f5fa11272fb7b295b1b75b1b36358515` |
| Host public key | `57bb9e6a43fc267cff46efc22893c35e1b5bcfdb9c71ebadd8f3420c8f8de1ad` |
| 100-run verification JSON | `14b15fcbc6d5c7ee129bb6274172ebae295c624f21df13d5ad6602d92a00b07f` |
| Generated HTML report | `049dc8b754f6490ad44fde87a7aad3c2ecc7678d40845dc3089740b5b7a07b92` |

Independent verification found schedule integrity and the seed reveal valid,
with no failed, aborted or extra receipts. Its overall completion flag is
`false` because 284 registered calls were deliberately not run.

## What this proves—and does not prove

The pilot shows that AetnaMem can assign Grok different memory combinations,
record the exact context exposure, bind externally verified outcomes to those
assignments, and preserve independently checkable evidence.

It does **not** prove that AetnaMem generally improves Grok, that all four
memory planes should always be included, or that the observed estimates will
replicate. Those claims require completion of the registered schedule, a
frozen-policy held-out evaluation, and replication.
