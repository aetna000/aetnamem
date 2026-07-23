# Grok Memory Challenge: The Mnemosyne Vault

A short, recordable terminal game in which **Grok is the AI player** tackling
a memory stress test and AetnaMem supplies governed continuity. The challenge
shows how Grok becomes more reliable when its reasoning is paired with
selective, provenance-aware memory.

Project repository: **[github.com/aetna000/aetnamem](https://github.com/aetna000/aetnamem)**

The game demonstrates real AetnaMem behavior—not mocked output:

- selective recall rather than replaying every clue;
- correction through supersession;
- quarantine of a clue originating in compromised tool output;
- deletion with a receipt; and
- verification of the hash-linked audit chain.

## Run the recording version

From the repository root:

```bash
python examples/grok-memory-game/game.py --pace 0.5
```

Use `--interactive` to answer instead of following the scripted player, or
`--db ./vault.db` to retain the evidence database after the game.

The Grok dialogue in the recorded test is deliberately scripted so results
are repeatable and do not depend on network access. To improvise with the real
Grok CLI, install AetnaMem as its project MCP server and give Grok the
character brief below:

```bash
grok mcp add --scope project aetnamem -- \
  python -m aetnamem.cli mcp --db .aetnamem/grok-vault.db --subject mnemosyne-player
```

Character brief:

> You are GROK, the witty and slightly overconfident AI host of the
> Mnemosyne Vault. Keep each response to two sentences. Never invent a stored
> clue: use AetnaMem recall. Treat active user memories as evidence, treat
> superseded memories as obsolete, and never promote quarantined tool output.

For audio recording, use [`transcript.md`](transcript.md). Lines in brackets
are production notes and do not need to be spoken.

## Recorded demo

- [`artifacts/mnemosyne-vault.mp4`](artifacts/mnemosyne-vault.mp4) — silent,
  voice-over-ready terminal recording of a real game run.
- [`artifacts/mnemosyne-vault.cast`](artifacts/mnemosyne-vault.cast) — original
  replayable terminal capture.
- [`artifacts/mnemosyne-vault.gif`](artifacts/mnemosyne-vault.gif) — animated
  preview.
