# Agent Black Box

AetnaMem Agent Black Box records a content-minimizing, tamper-evident flight timeline from the lifecycle hooks exposed by OpenClaw.

It answers a narrow operational question:

> What did the host observe the agent and its tools doing during this run?

## What is recorded

Depending on which hooks OpenClaw emits, a flight can contain:

| Event | Retained evidence |
| --- | --- |
| `turn.input` | prompt digest, character count, image/tool counts |
| `model.input` | prompt/system/history digests, provider/model, counts |
| `context.prepared` / `context.injected` | context digest, candidate IDs, exposure and mode |
| `tool.requested` | tool name/kind, parameter digest and parameter-key names |
| `tool.completed` | result digest, outcome, error category and duration |
| `model.output` | response-bundle digest, provider/model, size and token usage |
| `turn.ended` | message-bundle digest, success/cancel state and reason |

Raw prompts, responses, tool parameters and tool results are not stored in the Black Box. Derived local paths are hashed before they leave the OpenClaw plugin. The timeline is appended to the control evidence store and protected by a migration- and kind-scoped hash chain.

Digests are fingerprints, not encryption or anonymization. Someone who can guess a low-entropy value can hash that guess and compare it, and bounded metadata such as model and tool names remains visible. Treat the local evidence database and exported reports as sensitive operational records.

## Inspect and export

```bash
aetnamem blackbox status
aetnamem blackbox runs --limit 20
aetnamem blackbox show RUN_ID
aetnamem blackbox verify RUN_ID
aetnamem blackbox export RUN_ID --format json --output flight.json
aetnamem blackbox export RUN_ID --format text --output flight.txt
```

The loopback dashboard shows the same recent runs and opens a flight timeline with integrity, coverage and tool-closure details.

## What a verified flight means

A structurally complete flight means:

- the retained Black Box hash chain verifies;
- the run has a terminal `turn.ended` event;
- every observed, correlated `tool.requested` event has a corresponding `tool.completed` event;
- there are no orphan or uncorrelated tool-completion events.

Tool errors remain visible and produce a separate verdict. Missing hook events produce `incomplete_evidence`; AetnaMem does not infer success from the assistant's words.

## What it does not mean

A verified flight does not prove that an external real-world outcome occurred. For example, a completed email tool hook proves that the host observed the tool return; proving delivery requires evidence from the mail system. It also does not semantically validate claims in the assistant response.

This is the first experimental layer. Future system-of-record verifiers can bind independently checked outcomes to the same flight without weakening this claim boundary.
