# Safe Switch: try AetnaMem beside your agent

Status: **beta in AetnaMem 0.6.1**

Safe Switch answers a practical adoption question:

> Can I inspect AetnaMem on my own agent before I let it influence a prompt?

It is a reversible integration path for a local, single-user OpenClaw or
Hermes installation. It is not a claim that every agent becomes cheaper or
more accurate.

## Five commands to the first preview

```bash
# 1. Install the Python package. No snapshot/sudo package is required.
python3 -m pip install --upgrade aetnamem

# 2. OpenClaw only: install the matching lifecycle-hook plugin.
openclaw plugins install npm:openclaw-memory-aetnamem@0.4.0 --pin

# 3. Detect one supported local host, snapshot its AetnaMem plugin config,
#    install the trial hook, and start candidate-only capture.
aetnamem trial start --host auto

# 4. Keep using the agent, then inspect normalized candidate memories.
aetnamem trial candidates

# 5. Approve selected candidates and enter observer-only preview mode.
aetnamem trial approve tc_example
aetnamem trial preview
```

Open the local review surface at any time:

```bash
aetnamem trial dashboard
```

It binds to `127.0.0.1`, uses a one-time sign-in URL and an HttpOnly session
cookie, and requires CSRF tokens for changes.

## What the command words mean

### `--host auto`

`auto` checks which supported executable is installed on `PATH`.

- Exactly one of `openclaw` or `hermes`: use it.
- Both: stop and ask you to pass one explicitly.
- Neither: stop and explain what is missing.

It does not inspect your conversations to choose a host.

### Subject

The simple trial commands do not ask for `--subject`. They use the internal
scope `local-user` because Safe Switch 0.6.1 is a local, single-user beta.

In the generic MCP and Python APIs, `subject_id` is a storage partition
provided by the host—not proof of authenticated identity. Multi-user
applications must map their authenticated user or tenant to that field.

### `rollback`

Rollback first writes the control state to `off`, then restores the exact
AetnaMem plugin configuration captured at trial start and verifies the
restored digest.

Rollback does not:

- undo agent responses already produced;
- delete provider-side logs;
- delete the separate trial database;
- remove facts from an unrelated native memory system; or
- promise that a host-controlled original media file was deleted.

Use `aetnamem trial off` for an immediate stop without host restoration.

## The safety boundary by mode

| Mode | Local writes | Preview computed | Context sent to model | Provider calls added |
|---|---:|---:|---:|---:|
| `off` | No | No | No | No |
| `capture` | Candidate facts and evidence | No | No | No |
| `preview` | Candidate facts and preview manifests | Yes | No | No |
| `canary` | Evidence plus bounded exposures | Yes | Yes, up to the declared turn cap | No separate calls |
| `active` | Evidence plus exposures | Yes | Yes | No separate calls |

The plugin uses the host's existing model call. AetnaMem does not mirror
traffic or call a second model in these modes.

In 0.6.1, `active` means AetnaMem's approved context is enabled on eligible
turns. It does not silently delete or disable `MEMORY.md`, `USER.md`, or an
existing Hermes memory provider. Removing duplicated native memory is a
separate, reviewed migration after the user has verified their own results.

Only authenticated user-turn text is eligible for trial capture. Webpages,
tool output and assistant replies do not become trial candidates. The raw
message is not stored; AetnaMem stores a deterministic extracted fact plus
the source-message SHA-256. Candidate approval is available only through the
local CLI/dashboard, not through agent-facing tools.

## OpenClaw

Safe Switch uses the same `memory-aetnamem` plugin as the existing integration
but routes hooks to a private four-tool trial protocol:

- `trial_capture`
- `trial_prepare`
- `trial_exposure_shown`
- `trial_status`

No approve, reject, mode-change, forget, or arbitrary memory tool is exposed
on that protocol. The plugin also registers no agent-callable AetnaMem tools
while Safe Switch is enabled.

OpenClaw configuration is written through its validated `config set` CLI.
The prior `plugins.entries.memory-aetnamem` object is saved before any write.
OpenClaw normally hot-reloads this plugin configuration.

## Hermes

Safe Switch installs a Hermes **general plugin**, not a memory-provider
replacement. It can therefore observe beside the current Hermes memory
provider.

- `pre_llm_call` computes a preview and returns `{"context": ...}` only in
  canary or active mode.
- `post_llm_call` confirms the exposure and captures the authenticated user
  turn.

Hermes must be restarted after initial plugin installation. The plugin
registers no model-callable tool.

## What the numbers prove

The trial can verify:

- the host plugin configuration snapshot and restore digest;
- the trial state digest and transition hash chain;
- candidate status and content digest;
- the exact preview manifest and context digest;
- whether a host requested and confirmed a context exposure; and
- the number of characters supplied.

These are operational and retrieval measurements. They do not establish that
memory caused a better answer.

The repository's published OpenClaw benchmark is a controlled reference run,
not a measurement of your installation. The default-off Memory Impact Lab is
the research surface for randomized, host-verified causal studies. It is
documented separately because a scientific experiment and a low-risk product
trial are different jobs.

## Files

Default locations:

```text
~/.aetnamem/safe-switch.json          digest-bound mode control
~/.aetnamem/trials/trial_*/evidence.db
~/.aetnamem/trials/trial_*/openclaw-rollback.json
~/.aetnamem/trials/trial_*/hermes-rollback.json
```

Trial evidence is separate from `~/.aetnamem/memories.db` and is never
silently imported into live AetnaMem memory.
