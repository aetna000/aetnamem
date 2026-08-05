# OpenClaw setup

## Requirements

- a local OpenClaw installation on `PATH`;
- Python 3.10 or newer;
- an OpenClaw workspace readable by the current user.

## Install

```bash
python -m pip install --pre aetnamem==1.0.0a6
aetnamem --version
aetnamem openclaw install
```

Do not install `openclaw-memory-aetnamem` directly. It is a bridge, not a standalone memory engine. `aetnamem openclaw install` selects the matching bridge version, pins the exact Python executable, shows staged progress, restarts the gateway and verifies the running plugin.

The installer is safe to rerun. If the same OpenClaw migration is already in
shadow mode, AetnaMem refreshes and verifies that migration instead of creating
a second control ID. The original pre-AetnaMem restore snapshot is preserved.

## Inspect before switching

```bash
aetnamem control status
aetnamem control verify
aetnamem openclaw memory status
aetnamem dashboard daemon start
```

The dashboard must report OpenClaw as the provider, a verified native baseline, a valid mirror and no activation blockers. Search a known memory and inspect its source path and history.

Use OpenClaw normally, then inspect the host-observed Agent Black Box flights:

```bash
aetnamem blackbox status
aetnamem blackbox runs
aetnamem blackbox verify RUN_ID
```

Flight recording stores content digests and bounded lifecycle metadata, not raw prompts, responses, tool parameters or results. See [agent-blackbox.md](agent-blackbox.md) before interpreting a verdict.

## Activate or restore

```bash
aetnamem control activate
aetnamem control status

# Non-destructively stage and verify the saved restore material:
aetnamem control restore --drill

# Return to the saved OpenClaw memory configuration:
aetnamem control restore
```

Both destructive state transitions require confirmation in an interactive terminal unless `--yes` is supplied deliberately. `control verify` and `restore --drill` are non-destructive. A failed activation does not claim success. A restore preserves AetnaMem evidence and does not undo past agent outputs.

For dashboard lifecycle and its loopback-only boundary, see the [main README](../README.md). For the exact switch guarantees, see [control-plane.md](control-plane.md).
