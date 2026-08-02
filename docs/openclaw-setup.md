# OpenClaw setup

## Requirements

- a local OpenClaw installation on `PATH`;
- Python 3.10 or newer;
- an OpenClaw workspace readable by the current user.

## Install

```bash
python -m pip install --pre aetnamem==1.0.0a1
aetnamem --version
aetnamem openclaw install
```

Do not install `openclaw-memory-aetnamem` directly. It is a bridge, not a standalone memory engine. `aetnamem openclaw install` selects the matching bridge version, pins the exact Python executable, shows staged progress, restarts the gateway and verifies the running plugin.

## Inspect before switching

```bash
aetnamem control status
aetnamem openclaw memory status
aetnamem dashboard daemon start
```

The dashboard must report OpenClaw as the provider, a verified native baseline, a valid mirror and no activation blockers. Search a known memory and inspect its source path and history.

## Activate or restore

```bash
aetnamem control activate
aetnamem control status

# Return to the saved OpenClaw memory configuration:
aetnamem control restore
```

Both destructive state transitions require confirmation in an interactive terminal unless `--yes` is supplied deliberately. A failed activation does not claim success. A restore preserves AetnaMem evidence and does not undo past agent outputs.

For dashboard lifecycle and authentication, see the [main README](../README.md). For the exact switch guarantees, see [control-plane.md](control-plane.md).
