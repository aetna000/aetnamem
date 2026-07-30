# OpenClaw Safe Switch: mirror, inspect, then take over

Status: **experimental preview in AetnaMem 0.6.1.1a2**

Safe Switch gives a local, single-user OpenClaw installation a reversible way
to adopt AetnaMem:

> Keep OpenClaw memory live while AetnaMem mirrors it. Search and audit the
> mirror. Switch only after the evidence verifies. Roll back to the frozen
> native state whenever you want.

It is not a promise that every agent becomes cheaper or more accurate.

## Install and shadow

```bash
# 1. Install the engine. No sudo or snapshot package is required.
python -m pip install --pre aetnamem==0.6.1.1a2
aetnamem --version

# 2. Let AetnaMem install and verify the matching OpenClaw bridge.
aetnamem openclaw install

# 3. Inspect without changing the model's prompt.
aetnamem openclaw memory status
aetnamem openclaw memory search "TypeScript preference"
aetnamem openclaw memory trace "TypeScript preference"

# 4. Open the friendly local dashboard.
aetnamem dashboard
```

The installer pins the exact engine executable, installs npm
`0.4.1-experimental.2` internally, takes and verifies a complete byte-for-byte
baseline of the existing native memory, builds the searchable mirror, restarts
and probes the gateway, and enters shadow mode. If any step fails, it restores
the prior plugin configuration. Users do not install the npm package directly.

Shadow mode copies these native sources into an isolated AetnaMem database:

| OpenClaw source | AetnaMem plane | Active during shadow? |
|---|---|---|
| `MEMORY.md` | semantic | OpenClaw remains authoritative |
| `memory/**/*.md` | episodic | OpenClaw remains authoritative |
| `USER.md` | semantic, pinned | yes |
| `AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `HEARTBEAT.md` | procedural/safety, pinned | yes |
| workspace `skills/**/SKILL.md` | procedural, pinned | yes |

The baseline covers every recognized persistent OpenClaw memory source:
`MEMORY.md`, the complete `memory/` tree, `USER.md`, pinned workspace
instructions and workspace skills, including non-Markdown files and empty
directories. Every searchable mirrored chunk retains its source path,
source-file SHA-256 and line range. Changed native states are versioned and
changed Markdown triggers a deterministic mirror rebuild. Shadow recall is
computed without injecting context or making another provider call.

OpenClaw session JSONL and its derived search SQLite are not removed or
rewritten during takeover; they remain host-owned conversation/runtime state.
AetnaMem cannot recover information OpenClaw deleted or never persisted before
the initial baseline. “Complete” means every byte present in the recognized
persistent memory sources when shadowing starts and when cutover occurs.

## Dashboard daemon

```bash
aetnamem dashboard daemon start --port 8766
aetnamem dashboard daemon status
aetnamem dashboard daemon restart
aetnamem dashboard daemon stop
aetnamem dashboard daemon remove
```

The dashboard binds only to `127.0.0.1`. It uses a one-time login URL, an
HttpOnly session cookie, CSRF and Origin checks. `remove` deletes the daemon
service record, not memory or trial evidence.

## Canary, activate and rollback

```bash
# Optional: let AetnaMem influence only a bounded number of turns.
aetnamem trial preview
aetnamem trial canary --turns 10

# Full OpenClaw memory takeover. Requires typing `openclaw`.
aetnamem trial activate
aetnamem openclaw memory status

# Restore the pre-activation OpenClaw memory state.
aetnamem trial rollback
```

Activation is a guarded cutover:

1. Synchronize and verify the final searchable mirror.
2. Checkpoint the SQLite database.
3. Copy every file and empty directory in `MEMORY.md` and `memory/` into a
   private switch-time snapshot and hash every file.
4. Refuse activation if the source changes while copying or any digest differs.
5. Record the complete snapshot manifest, then deactivate the live copies.
6. Disable OpenClaw's native memory slot and `session-memory` writer.
7. Point the AetnaMem bridge at the verified mirror with bounded recall.
8. Restart OpenClaw and require a successful gateway probe.
9. Restore everything automatically if any cutover step fails.

OpenClaw remains the agent and execution engine. Its identity, safety,
authorization, tools and executable skills remain pinned. AetnaMem takes over
supplemental durable memory.

Rollback restores every file and empty directory from the switch-time
snapshot, re-verifies their hashes, restores the memory slot, session hook and
prior plugin configuration, restarts the gateway, and verifies it. The initial
pre-shadow baseline and observed shadow versions remain as evidence. OpenClaw's
derived search SQLite is left host-controlled and is not deleted. Rollback
does not undo past agent responses or provider logs.

`aetnamem trial off` is an emergency bridge stop. After an active takeover it
leaves the native freeze untouched so two memory systems cannot silently
restart together; run `rollback` to restore usable native memory.

## What the evidence means

The mirror can prove:

- the complete native state before shadowing and at switch time;
- which observed native versions appeared while shadowing;
- which native files and line ranges produced each searchable memory;
- whether the mirror database and hash-chained audit log verify;
- which memories shadow recall would select;
- which bounded context was actually exposed during canary/active modes;
- whether cutover and rollback configuration checks passed.

The dashboard's token figure is a **context-budget projection**. It compares
native memory bytes with AetnaMem's bounded recall allowance; it is not a
provider bill or a universal saving. If the native memory is already smaller
than the allowance, the dashboard says that no reduction is expected.

## Command words

- `--host auto` detects exactly one supported executable. It does not inspect
  conversations.
- The simple trial uses internal subject `local-user`. A `subject_id` is a
  storage partition supplied by the host, not authenticated identity.
- `rollback` means restore the saved host configuration and frozen native
  memory. It does not delete the evidence database.

Default evidence files:

```text
~/.aetnamem/safe-switch.json
~/.aetnamem/trials/trial_*/evidence.db
~/.aetnamem/trials/trial_*/openclaw-mirror.db
~/.aetnamem/trials/trial_*/openclaw-mirror.json
~/.aetnamem/trials/trial_*/openclaw-native-baseline/
~/.aetnamem/trials/trial_*/openclaw-native-baseline.json
~/.aetnamem/trials/trial_*/openclaw-shadow-history/
~/.aetnamem/trials/trial_*/openclaw-cutover.json
~/.aetnamem/trials/trial_*/openclaw-native-snapshot.json
~/.aetnamem/trials/trial_*/openclaw-native-frozen/
```

Hermes keeps the earlier coexistence behavior: it can shadow, preview, canary
and activate AetnaMem context, but 0.6.1.1a2 does not replace the selected
Hermes memory provider.
