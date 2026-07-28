# Safe Switch modes and boundaries

| Mode | Local behavior | Changes model context? |
|---|---|---|
| `capture` | Extract candidate facts from authenticated user turns | No |
| `preview` | Show what approved memory would be recalled | No |
| `canary` | Supply approved context for a fixed number of turns | Yes, limited |
| `active` | Supply approved context on eligible turns | Yes |
| `off` | Stop future AetnaMem capture and injection | No |

## Approval

Candidate extraction is not promotion. A human or authorized host must approve
eligible candidates. Confidence is evidence metadata and must not decide
promotion.

## Canary

A canary is a bounded context exposure, not a proof that memory improved the
answer. Compare the same task and provider configuration where possible. Track
context characters or tokens, latency, failures, and a host-verified outcome.

## Stop versus rollback

- `off` fails closed for future AetnaMem capture and injection.
- `rollback` also restores the saved host plugin configuration.

Neither deletes trial evidence, reverses past agent outputs, or deletes
provider-side logs.

## Host boundary

The skill controls AetnaMem through the local trial state. OpenClaw and Hermes
hooks remain the mechanism that observes authenticated turns and supplies
approved context. A skill alone is not an always-on interceptor.
