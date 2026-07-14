# aetnamem Desktop for macOS

This is the practical, non-developer path for a local assistant protected by
`aetnamem`.

## What it gives you today

- A local web dashboard at `http://127.0.0.1:8765/app`.
- A chat shell backed by OpenAI, DeepSeek, any OpenAI-compatible API, or an
  offline echo mode for testing.
- Durable local memory with provenance and deletion receipts.
- Approval-gated file writes in a safe workspace folder.
- Mac Keychain protected database key with encrypted at-rest database sealing
  when the service shuts down cleanly.

The live SQLite database is plaintext while the service is running. On clean
shutdown, `--encrypted-db` seals it into `memories.db.enc` and removes the
runtime copy. This is not SQLCipher and does not protect against a compromised
running user session. It is meant to protect the idle local database on disk.

## Start it

From a checkout:

```bash
chmod +x scripts/macos/aetnamem-desktop.command
open scripts/macos/aetnamem-desktop.command
```

The terminal prints:

- dashboard URL
- agent token
- reviewer token
- workspace path

Open the dashboard URL and paste both tokens into the Connect panel.

## First-run questions

The dashboard checks:

- macOS
- Python version
- at least 1 GB free disk

Then choose a provider:

- `Offline echo` to test without an API key
- `OpenAI`
- `DeepSeek`
- `OpenAI-compatible` for local gateways or custom providers

## Safe workspace

By default writes are confined to:

```text
~/Aetnamem Workspace
```

The assistant can stage a write there, but cannot execute it until you approve
and commit it in the dashboard.

## Current limitations

- This is a local web app, not a signed/notarized `.app` bundle yet.
- Tokens are still printed in Terminal for this development build.
- Provider API keys configured through the dashboard are stored in macOS
  Keychain. Environment-provided keys are not rewritten unless you save them in
  the dashboard.
- Full live SQLite encryption needs SQLCipher or another native dependency.
