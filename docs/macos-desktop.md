# aetnamem Desktop for macOS

This is the practical, non-developer path for a local assistant protected by
`aetnamem`.

## What it gives you today

- A local web dashboard at `http://127.0.0.1:8765/app`.
- A chat shell backed by a lightweight local Ollama model, OpenAI, DeepSeek,
  any OpenAI-compatible API, or an offline echo mode for testing.
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

One launch does everything:

1. Installs Ollama via Homebrew if it is missing (skipped when Homebrew is
   unavailable; the app then runs in offline echo mode).
2. Starts `ollama serve` in the background and pulls `qwen3:1.7b` on first run.
3. Starts the control service and opens the dashboard in your browser,
   already signed in — the tokens ride in the URL fragment, which never
   leaves the browser, and are stored in `localStorage`.
4. Selects the local Ollama provider automatically when the Ollama API is
   reachable.

The terminal still prints the dashboard URL, tokens, and workspace path as a
fallback (for example if no browser opens). Pass `--no-open` to
`python -m aetnamem.service` to suppress the auto-open.

## Providers

The default is the local Ollama model when Ollama is running. You can switch
in Settings:

- `On this Mac (Ollama)` for a laptop-local model suitable for 12 GB Apple
  Silicon machines
- `Offline echo` to test without an API key
- `OpenAI`
- `DeepSeek`
- `OpenAI-compatible` for local gateways or custom providers

Settings also shows a system check: macOS, Python version, free disk,
Ollama install/API status, and the recommended local model.

## Local light model

The desktop launcher bootstraps the local model itself. The default model is:

```text
qwen3:1.7b
```

On an M1 laptop with 12 GB RAM, use this path first. It keeps inference local,
avoids API keys, and leaves memory/audit data inside the `aetnamem` sidecar.

If you want to prepare the model without starting the desktop app:

```bash
chmod +x scripts/macos/install-light-local-model.command
open scripts/macos/install-light-local-model.command
```

Or run the equivalent commands manually:

```bash
ollama pull qwen3:1.7b
ollama serve
```

The default base URL is `http://localhost:11434`. Override the model with
`AETNAMEM_LOCAL_MODEL`.

## Safe workspace

By default writes are confined to:

```text
~/Aetnamem Workspace
```

The assistant can stage a write there, but cannot execute it until you approve
and commit it in the dashboard.

The dashboard's **Files** tab lists everything in the workspace. Markdown
files open rendered in the browser; any text file can be edited and saved
in place. Dashboard saves are made by you (the reviewer), so they skip
staging but are still recorded on the audit chain as `user.file_saved`.
Reads and writes are confined to the workspace — path traversal is rejected.

Settings includes a **Data & security** panel showing where the live memory
database lives, whether it is sealed encrypted at rest on quit (and to which
path), and that the encryption key is stored in the macOS Keychain.

## Current limitations

- This is a local web app, not a signed/notarized `.app` bundle yet.
- Tokens are auto-injected into the browser at launch, but are still printed
  in Terminal as a fallback for this development build.
- Provider API keys configured through the dashboard are stored in macOS
  Keychain. Environment-provided keys are not rewritten unless you save them in
  the dashboard.
- Full live SQLite encryption needs SQLCipher or another native dependency.
