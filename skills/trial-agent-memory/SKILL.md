---
name: trial-agent-memory
description: Run AetnaMem beside an existing OpenClaw or Hermes agent through capture, review, preview, limited canary, activation, emergency stop, and rollback. Use when a user wants to evaluate governed memory without immediately replacing native memory, inspect candidate memories, quantify context exposure, switch only after review, or restore the saved host configuration.
---

# Trial agent memory

Use Safe Switch as a staged adoption workflow. Capture and preview do not
change model context. Canary and active do.

## Required workflow

1. Confirm that AetnaMem and exactly one supported host are installed, or ask
   the user to select `openclaw` or `hermes`.
2. Start in capture mode with `scripts/trial_memory.py start`.
3. Keep the agent in ordinary use while AetnaMem collects candidate facts.
4. Show candidates and obtain explicit approval or rejection.
5. Preview locally. Explain that preview is not proof of improved answers.
6. Start a small canary only after approval and explicit user confirmation.
7. Compare measured exposures, context size, failures, and user-visible
   behavior. Do not invent savings or quality gains.
8. Activate only after the canary gate passes. Otherwise stop or roll back.

## Commands

```bash
python scripts/trial_memory.py start --host auto
python scripts/trial_memory.py status
python scripts/trial_memory.py candidates
python scripts/trial_memory.py approve tc_123 --confirm
python scripts/trial_memory.py preview --query "What format should reports use?"
python scripts/trial_memory.py canary --turns 5 --confirm
python scripts/trial_memory.py activate --confirm
python scripts/trial_memory.py rollback --confirm
```

`--host auto` detects exactly one installed supported host and fails on
ambiguity. It does not choose between two hosts.

Read `references/trial-modes.md` before a canary, activation, emergency stop,
or rollback.

## Non-negotiables

- Never skip candidate review.
- Never describe capture or preview as changing model behavior.
- Never start canary or active mode without explicit confirmation.
- Never claim cost or quality improvement without a paired measurement.
- Never delete trial evidence during rollback.
- Report that past model outputs and provider logs cannot be reversed.
