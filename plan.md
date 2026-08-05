# Implementation plan: rollback check · continuous run evidence · encryption at rest

## Implementation status (2026-08-03)

- **P0/P1 complete:** frozen report-digest semantics, transactional control-store
  v1→v2 migration, and migration/kind-scoped evidence chains are implemented and
  tested for tampering, reordering, and cross-migration splicing.
- **C complete:** restore is staged, journaled, resumable, receipt-bound, and
  audit-bound. Baseline restoration and active-period additions are separate
  proofs. CLI and dashboard expose the non-destructive restore drill using the
  exact claim boundary below.
- **B implementation started:** the read-only verification engine, compatibility
  parser, CLI/dashboard surface, stable evidence digest, report chaining, applied
  configuration capture, and core red-path tests are implemented. The isolated
  host probe and CI compatibility automation remain.
- **A prerequisites implemented:** authoritative household policy, inert key
  initialization, file/keyring/env key resolution, header fail-closed checks,
  and shared/exclusive household locks are implemented. SQLCipher/Fernet
  migration, archive conversion, resumable encrypt/decrypt journals, and their
  platform CI tiers remain and must not be described as shipped yet.

Instructions for the implementing agent. Three workstreams, built in this
order:

1. **C — rollback check** (restore staging, receipts, drill)
2. **B — continuous run evidence** (`control verify`, strictly read-only)
3. **A — encryption at rest** (household policy + locking first, then
   SQLCipher migration, then control archives)

C comes first because restore must be demonstrably safe before
verification makes claims about it, and because encrypted snapshots (A)
must pass through the same restore and drill paths. B's
`restore_readiness` check consumes C's drill timestamp.

Prerequisite for all three: P0 and P1.

Conventions that already exist in this codebase — follow them:

- Evidence formats are dicts with a `format` key, digested with
  `sha256_hex(canonical_json(body))` from `aetnamem/core/canonical.py`.
- Deletion-style operations fail closed and emit receipts
  (see `Memory.forget_artifact` in `aetnamem/memory.py`).
- New CLI subcommands go into the existing parser structure in
  `aetnamem/cli.py`; every command supports `--json`.
- Tests are plain pytest in `tests/`; the fake OpenClaw host harness
  pattern is in `tests/test_host_adapter.py` and
  `tests/test_openclaw_control.py`.

---

## P0 — Frozen evidence formats

Freeze these before writing feature code; receipts outlive code. Every
format includes `format` and `report_sha256`. Reports that describe
measured state additionally carry `evidence_sha256`:

- `report_sha256` — digest over the complete canonical body, including
  timestamps. Unique per run.
- `evidence_sha256` — digest over a format-specific stable projection.
  Each evidence format defines exactly which nested fields are excluded;
  generated IDs, timestamps, durations, gateway uptime and
  `report_sha256` are never included. Identical measured state ⇒
  identical `evidence_sha256`, so runs are comparable.

| format | purpose |
|---|---|
| `aetnamem-control-verification-v1` | verify report (B) |
| `aetnamem-restore-receipt-v1` | real restore outcome (C) |
| `aetnamem-restore-drill-v1` | drill outcome, explicit claim fields (C) |
| `aetnamem-restore-journal-v1` | two-phase restore journal (C) |
| `aetnamem-encryption-receipt-v1` | household encryption outcome (A) |
| `aetnamem-encryption-journal-v1` | resumable encrypt/decrypt journal (A) |

## P1 — Control-store schema migration + evidence chain

`aetnamem/control/store.py` currently accepts only schema version 1.
Add a versioned migration path (v1 → v2) and the evidence table:

```sql
evidence(
    id,
    migration_id,
    kind,
    sequence,
    created_at,
    body_json,
    body_sha256,
    prev_sha256,
    entry_sha256,
    UNIQUE(migration_id, kind, sequence)
)
```

Chains are scoped per `(migration_id, kind)` — never globally, so
unrelated migrations cannot mix. `entry_sha256 =
sha256_hex(canonical_json({prev_sha256, migration_id, kind, sequence,
body_sha256}))`, binding identity and order into the chain so tampering,
reordering, and splicing are all detectable.

Opening a v1 store migrates in place inside a transaction; opening a
newer-than-known version fails closed. Tests: v1 → v2 preserves rows;
chain verification detects a tampered body, a reordered pair, and a row
spliced in from another migration_id.

---

## C — Rollback check (restore receipt + drill)

### C1. Shared staging helpers

Extract from `restore_takeover` / `_restore_cutover`
(`aetnamem/control/openclaw_native.py:1463`, `:1634`) pure helpers
parameterized by target root:

```python
def _manifest_diff(expected: dict[str, str], root: Path) -> list[dict]
def _stage_restore_tree(cutover: dict, staging_root: Path) -> list[dict]
def _swap_staged_tree(staging_root: Path, live_root: Path, journal: Journal) -> list[dict]
```

Drill and real restore must execute the same staging and diff code.

### C2. Two-phase, journaled restore

Rework `restore_takeover` into validate → stage → swap. The ordering of
steps 8–9 is deliberate: the baseline proof is taken **before**
active-memory export, because the export legitimately adds content and
must never be counted against baseline equality.

Phase 1 — no live mutation:
1. Validate the frozen archive and cutover metadata parse and their
   digests match the freeze-time manifest.
2. Stage the restored tree under the control dir (`staging/<ts>/`).
3. `_manifest_diff` on the staged tree — every file must match the
   baseline manifest before anything live is touched.
4. Validate every saved config value exists when expected, parses, and
   has the recorded type. Applicability is not claimed until Phase 2
   actually restores and re-reads the value.
5. Write `aetnamem-restore-journal-v1` with the planned steps.

Phase 2 — journaled swap:
6. Swap staged files into the live workspace, marking each journal step
   done as it completes; preserve divergent live files (existing
   preservation machinery) before overwriting.
7. Restore config keys; re-read each and compare.
8. **Baseline proof**: re-diff the live workspace against the baseline
   manifest now — before any additions. This becomes the receipt's
   `files` block.
9. **Active-memory export**: run
   `_export_active_memories_to_native`, recording every file written and
   its digest as a separate additions list. Additions are a second,
   independent proof — they never count against the baseline diff.
10. `restart_and_verify_gateway()`.
11. Post-restore proof combines the step-8 baseline result, the verified
    step-9 additions, restored configuration and `gateway_health`. Do not
    compare against the old mirror manifest after export: the export
    intentionally changes native files.

Any interruption: rerun reads the journal and resumes from the first
incomplete step. A rerun over a completed journal is a no-op returning
the existing receipt.

### C3. Restore receipt (`aetnamem-restore-receipt-v1`)

Two separate proofs, never merged:

- `files`: the step-8 baseline proof — per baseline-manifest entry,
  expected sha256, actual sha256, `matched`.
- `active_memory_export`: the step-9 additions — per file written, path
  digest and content digest, plus the export summary digest.

Plus:

- `divergent_preserved`: preserved live files with digests and
  preservation root.
- `config`: each saved key — saved value vs re-read value, `matched`.
- `gateway`: restart/verify result.
- `journal`: step list with completion status, so a failed receipt states
  exactly what changed and what did not.
- `valid` = baseline matched AND config matched AND export completed AND
  gateway verified; `evidence_sha256`, `report_sha256`; audit event
  `control.restored`; row in the P1 evidence table.

Fail closed: any baseline or config mismatch ⇒ cutover status
`restore_verification_failed`, exit 1, preservation kept — and the
receipt with `valid: false` is still written.

### C4. `control restore --drill`

- Runs Phase 1 only (validate + stage + manifest diff) in a sandbox
  staging root, plus config **readability**: `openclaw config get` per
  saved key — never `set`.
- Emits `aetnamem-restore-drill-v1` with explicit claim fields:

```json
{
  "files_restoration_tested": true,
  "saved_config_readable": true,
  "live_rollback_performed": false,
  "duration_ms": 0
}
```

- Surfaces (CLI `control status` + dashboard) use exactly this wording —
  never the phrase "rollback tested":

```text
File restoration tested <when>
Saved configuration readable
Live rollback not performed
```

- Timestamp persisted in the evidence table; B's `restore_readiness`
  consumes it; a drill older than the last observed host-version change
  degrades that check to warn.
- Upgrade path (not this release): if OpenClaw can run against an
  isolated config copy, extend the drill to a true isolated restore and
  only then strengthen the label.

### C5. Tests (`tests/test_restore_receipt.py`)

1. Full cycle on the fake host: shadow → activate → mutate one native
   file → restore ⇒ receipt valid; baseline matched; divergent file
   preserved with digest; config keys matched.
2. Active-period memories exist ⇒ restore succeeds; `files` (baseline)
   all matched; `active_memory_export` lists the additions; the additions
   do NOT appear as baseline mismatches.
3. Staged tree fails manifest diff (tampered frozen file) ⇒ Phase 2 never
   starts; live workspace digest-identical before/after; receipt
   `valid: false`, exit 1.
4. Interruption injected after each journal step ⇒ rerun resumes and
   completes; receipt flags the resume; no step applied twice.
5. Drill: claim fields exactly as specified; live config and native files
   digest-identical before/after; timestamp lands in the evidence table.
6. Rerun over a completed journal returns the existing receipt unchanged.

---

## B — Continuous run evidence (`aetnamem control verify`)

**Invariant: verify is strictly read-only.** It never syncs, repairs,
restarts, or writes anything except its own report row. A test enforces
this (B6.2).

### B1. Engine

New module `aetnamem/control/verify.py`:

```python
def run_verification(state: ControlState, *, probe: bool = False) -> dict
```

Output `aetnamem-control-verification-v1`: header (migration_id, mode from
`takeover_status`, host version, bridge version, started/ended),
`checks: [{name, status: pass|fail|skip|warn, measured, evidence}]`,
`valid`, `evidence_sha256`, `report_sha256`. Persist to the P1 evidence
table; print both digests.

Checks:

| name | how |
|---|---|
| `host_version_tested` | `openclaw --version` vs manifest (B3). Untested minor/major ⇒ FAIL; CLI exits 2 when this is the only failure. Untested patch of a tested minor ⇒ WARN. |
| `bridge_version_pinned` | plugin entry version equals `OPENCLAW_PLUGIN_VERSION`; reuse `_find_plugin_version` from `aetnamem/control/hosts.py`. |
| `mirror_integrity` | **read-only**: compute the current native source manifest (hash the source files), load the *stored* mirror manifest, compare. Never call `sync_mirror` — repairing before measuring would hide staleness. A stale mirror is a FAIL with the divergent paths in evidence. Empty-but-consistent memory (zero records both sides) passes. Activation's own sequence is `sync → verify → activate`; also relax `activate_takeover`'s `record_count ≥ 1` precondition to the same manifest-equality rule. Mirror audit chain verifies (read-only). |
| `config_consistency` | compare the **complete applied configuration** recorded at activation (B4a) against live values: memory slot, session-memory hook, plugin enablement and mode, database/workspace/subject, capture and recall settings, allowed memory tools. Cutovers written before B4a carry only four keys — verify those and WARN that the recorded set is partial. |
| `shadow_configuration_safe` | shadow mode only. The AetnaMem plugin **is expected to be present** because it mirrors and observes. Verify the native provider remains selected and takeover is false. This proves configuration, not absence of injected context. Active mode ⇒ skip with reason. |
| `shadow_context_probe` | shadow mode only. PASS only when B2's isolated on/off comparison proves identical `llm_input`; otherwise SKIP with `isolation unavailable`. Never infer non-interference from the exposures schema. Active mode ⇒ skip with reason. |
| `frozen_paths_unchanged` | active mode only: re-hash frozen native files against the cutover manifest. |
| `restore_readiness` | rollback snapshot validates (C Phase 1 validation, sandboxed); drill record present; drill older than last host-version change ⇒ warn. |
| `gateway_health` | `openclaw gateway status --require-rpc --json` — status only; never restart during verify. |

### B2. Probe tier — isolated only

`verify --probe` never mutates customer config. Order of preference:

1. If OpenClaw supports an isolated config/workspace (config-file path
   flag or environment override): copy the live config, toggle the plugin
   entry **in the copy**, run the bridge's `verify-probe` scripted turn
   against the copy twice (plugin on / off), compare `llm_input` sha256s.
2. If isolation is not available: the check reports
   `skip · "isolation unavailable"` and probe functionality ships only as
   a documented development-lab check, not a customer guarantee.

Bridge side (`integrations/openclaw/`): `verify-probe` runs one scripted
turn with a fixed prompt and returns only the final `llm_input` sha256.

### B3. Tested-versions manifest

`aetnamem/control/compat.py`:
`TESTED_OPENCLAW_VERSIONS = ("2026.7.1-2",)` to start, plus
`evaluate_host_version(version) -> tested | untested_patch | untested`
with exact version parsing for OpenClaw's scheme (including the `-N`
suffix). Generate the list into the npm bridge at build time; the bridge
prints a banner at gateway start on an untested host — banner + continue
in both modes; never silently disable memory.

### B4. Wiring

- CLI: `control verify [--probe] [--json] [--state ...]`. Exit codes:
  0 pass, 1 fail, 2 untested-host-only.
- **B4a**: widen `activate_takeover` to record the complete applied
  configuration (every key it reads or writes, plus database, workspace,
  subject, capture/recall settings, allowed tools) in the cutover file.
- `activate_takeover`: `sync_mirror` first, then config-tier verification
  as step 0 of mutation; refuse on failure, before any change.
- `restore_takeover`: read-only mirror comparison + `gateway_health` at
  the end, embedded in the restore receipt.
- Dashboard: "Verify now" button on the switch view (existing POST route
  pattern in `aetnamem/control/web.py`); render last report + digests.
- `control status`: last verify result, `evidence_sha256`, age.

### B5. CI

- Tier 1 (every PR): fake-host verification tests (B6), no npm.
- Tier 2 (nightly + release): matrix over `TESTED_OPENCLAW_VERSIONS`
  installing real `openclaw@<version>`, fixture workspace:
  `openclaw install → control shadow → verify → activate → verify →
  restore --drill → restore`. If the gateway cannot run headless in CI,
  the matrix still exercises the config surface — that is what breaks on
  host upgrades.
- Weekly cron: `npm view openclaw version`; unlisted version ⇒ run matrix
  against it; open a repo issue on failure.
- `tools/update_compat_matrix.py` renders `docs/compat-matrix.md`
  (version · date · evidence_sha256 · result) from CI artifacts; README
  embeds it. Release gate: newest manifest version green.

### B6. Tests (`tests/test_control_verify.py`)

1. All green on a healthy shadow setup — including one with an **empty**
   native memory (zero records, consistent manifests), and with the
   plugin present in shadow (expected, must not fail
   `shadow_configuration_safe`).
2. **Read-only proof**: digest every household file (mirror DB, control
   files, native sources) before and after `verify` on a *stale* mirror —
   identical afterward, and the report FAILs `mirror_integrity` naming
   the divergent paths.
3. Drift the memory slot ⇒ only `config_consistency` fails.
4. Swap bridge version ⇒ only `bridge_version_pinned` fails.
5. Tamper a frozen native file in active mode ⇒ only
   `frozen_paths_unchanged` fails, file named in evidence.
6. Unknown host version ⇒ exit 2; untested patch ⇒ warn, exit 0.
7. Activation refuses when verification fails and performs no config
   mutation (config digest before/after identical).
8. Two runs on identical state: equal `evidence_sha256`, different
   `report_sha256`. Changed state ⇒ different `evidence_sha256`.
9. Reports chain per (migration_id, kind); tampered body, reordered
   pair, and cross-migration splice are each detected.
10. Pre-B4a cutover (four keys only) ⇒ `config_consistency` WARNs about
    the partial recorded set instead of failing.

---

## A — Encryption at rest

### A1. Approach and packaging

SQLCipher for every SQLite database, as the `aetnamem[encryption]` extra.
`sqlcipher3` (source build, needs libsqlcipher) and `sqlcipher3-binary`
(bundled) have different installation characteristics per platform, and
environment markers cannot detect wheel availability — so do not promise
one universal install line. Document three support tiers, each backed by
its own CI job:

```text
pip-only installation verified   (job: pip install ".[encryption]" alone succeeds)
native prerequisite required     (job: install sqlcipher via OS package manager first; labeled as such)
unsupported                      (documented)
```

A job that pre-installs Homebrew SQLCipher proves the *second* tier, not
the first — never conflate them in docs.

Do NOT use the old whole-file seal (`aetnamem/service/encrypted_db.py`,
`git show 32c0524^:aetnamem/service/encrypted_db.py`) — it left the DB
plaintext while open. Read once for the keychain ideas; set aside.

### A2. Household policy and state

One authoritative, **never-encrypted**, non-secret state file beside the
main memory database (`<db>.encryption.json`). No second writable copy
anywhere — duplicates can disagree. It records:

```text
state:   plaintext → migration-prepared → encrypting → encrypted
                     (and encrypted → decrypting → plaintext)
backend: file | keyring        (selected at keys init; non-secret)
key_id: stable non-secret household key identifier
control_kdf_salt: random non-secret salt for the derived archive key
```

A `HouseholdPolicy` object is loaded from this file and passed explicitly
to every store constructor and to `connect` — a sidecar path (vectors,
graph partition, mirror, control DB) cannot discover the policy from its
own path, so it is never guessed:

```python
def connect(path, *, policy: HouseholdPolicy,
            mode: Literal["runtime", "migration"] = "runtime",
            isolation_level=None) -> Connection
```

- `keys init` creates key material and records the chosen backend
  **only**. State stays `plaintext`; database behavior is unchanged.
  (Regression test A7.1 — the naive design bricks installs here.)
- The runtime factory consults recorded state, not key presence:
  `encrypted` ⇒ SQLCipher + `PRAGMA key` + readability probe; missing key
  or missing `sqlcipher3` ⇒ fail closed with hint. `plaintext` ⇒ stdlib
  sqlite3 even if a key exists. `encrypting`/`decrypting` ⇒ refuse with
  "resume migration" message.
- Header sanity both ways: encrypted-looking file under `plaintext`
  state, or plaintext header under `encrypted` state ⇒ fail closed, never
  recreate.
- Replace all direct `sqlite3.connect` call sites:
  `aetnamem/store/sqlite.py:25`, `aetnamem/semantic/index.py:41`,
  `aetnamem/control/store.py:23`, `aetnamem/graph.py:430`, `:807`, `:938`.

### A3. Household advisory lock

SQLite write locks cannot prove another process has released a file. Add
a household lock file (`<db>.lock`, `flock`-based) acquired by every
database holder — `Memory`, primary store, semantic index, graph archive,
control store, dashboard daemon, MCP/control MCP and short-lived CLI — and
by the migration command in exclusive mode. `:memory:` uses an explicit
lock-free plaintext policy. Migration refuses to start while any holder
owns a shared lock; holders refuse to start while migration owns the
exclusive lock. OS locks release when a process dies; pid + start-time is
diagnostic metadata only, never stale-lock authority.

### A4. Key management

`aetnamem/core/keys.py`:

- `aetnamem keys init --backend file` (default) or `--backend keyring` —
  the chosen backend is recorded in household state, so keyring is
  actually reachable. `AETNAMEM_DB_KEY` env (64-char hex) is an explicit
  override checked first at runtime, regardless of backend.
- File backend: `~/.aetnamem/keys/db.key`, 0600, refuse
  group/world-readable. Keyring backend: via `keyring` package (extra
  dependency of `[encryption]`'s keyring option, never core).
- `keys init` prints the loss-means-loss warning. `keys status --json`
  names the active backend and source, never the key. The key never
  appears in logs, receipts, journals, or audit events.

### A5. Household encryption — crash-recoverable transaction

`aetnamem encrypt <db-path>` operates on the complete household: primary
DB · vector sidecars (via `store.semantic_index_paths`) · graph partition
files · mirror DB · control evidence DB · A6 control archives.

Order matters — inventory comes **after** quiesce and checkpoint, because
checkpointing modifies the files:

1. **Lock**: take the A3 exclusive household lock; refuse if any holder
   is registered.
2. **Quiesce**: close/stop all AetnaMem writers; checkpoint
   (`PRAGMA wal_checkpoint(TRUNCATE)`) and close every DB.
3. **Inventory**: enumerate the household, hash every file, write
   `aetnamem-encryption-journal-v1` (state → `migration-prepared`).
4. **Stage** (state → `encrypting`): per DB, one **SQLCipher** connection
   opens the plaintext source with no key, `ATTACH DATABASE <staged> AS
   encrypted KEY '<key>'`, `SELECT sqlcipher_export('encrypted')`,
   `DETACH`; fsync the staged file. (A stdlib source connection cannot do
   this — the export must run inside a SQLCipher connection.)
5. **Verify staged**: reopen every staged DB with the key; integrity
   check and row counts against inventory. Stage and authenticate every
   A6 control archive under the same journal before state can advance.
6. **Swap**: journaled per-file atomic rename for DBs and control
   archives; delete plaintext control originals and plaintext-era
   `-wal`/`-shm` files only after their encrypted replacements verify;
   record every deletion in the receipt.
7. **Finish**: state → `encrypted`; emit `aetnamem-encryption-receipt-v1`
   (per-file path_sha256, before/after, size, wal_shm_removed,
   `evidence_sha256`, `report_sha256`); audit event `storage.encrypted`
   per subject; receipt row in the evidence table; release the lock.

Interruption at any step: rerun reads the journal and resumes; a
completed journal is a no-op returning the receipt.

### A6. Control archives — scope and ownership boundary

Encrypt **everything AetnaMem owns under its control directory** that
contains memory content: JSON snapshots (`_private_json` / `_read_json`
in `openclaw_native.py`), cutover archives, preservation trees
(`_new_preservation_root`), frozen native copies held in the control dir,
and exported-memory files. Mechanism: Fernet (`cryptography`, same
extra), key derived from the A4 key via HKDF (info
`"aetnamem-control-files"`); `.enc` variants written when household state
is `encrypted`. Runtime reads are state-strict: `plaintext` requires the
plaintext file, `encrypted` requires `.enc`, and only migration code may
resolve both forms according to its journal. An unexpected plaintext
fallback in encrypted state fails closed. The state file itself (A2) is
never encrypted.

Ownership boundary: files in the **OpenClaw workspace** belong to the
host. Never encrypt them in place, in any mode — AetnaMem encrypts its
copies, never the host's originals.

### A7. Decryption — first-class, not "symmetric" hand-waving

`aetnamem decrypt <db-path>` is its own journaled operation
(state `encrypted → decrypting → plaintext`), same lock and step
structure as A5 with the export reversed (SQLCipher source opened with
the key, plaintext destination attached with empty key). It must also:

- decrypt every A6 `.enc` control archive back to plaintext and verify
  each replacement's digest;
- remove `.enc` variants, staged files, and stale WAL/SHM only after
  verification;
- update household state and emit the receipt (same format, direction
  recorded);
- resume from its journal after interruption.

### A8. Tests (`tests/test_encryption.py`)

1. **`keys init` alone changes nothing**: existing plaintext install keeps
   opening and recalling normally; state stays `plaintext`.
2. Round trip: init → encrypt → reopen via `Memory` → recall works; no
   household file starts with the SQLite magic bytes; receipt lists every
   file including wal/shm cleanup; digests verify.
3. Decrypt round trip: encrypt → decrypt ⇒ recall identical; no `.enc`,
   staged, or stale WAL files remain; state `plaintext`; receipt records
   the direction.
4. Keyring backend: `keys init --backend keyring` (fake keyring) is
   selected and used; env var overrides it.
5. Wrong key ⇒ clear failure, no fallback, no file modification.
6. Encrypted state + no key ⇒ fail closed; plaintext header while state
   says `encrypted` ⇒ fail closed.
7. Interruption injected at every journal step of **both** encrypt and
   decrypt ⇒ rerun resumes; recall results identical to pre-migration.
8. Migration refuses while a registered holder (daemon/MCP) exists;
   holders refuse to start during migration.
9. Semantic purge + `forget` still yield `verified_absent` receipts on an
   encrypted household.
10. Drill and restore succeed against A6-encrypted snapshots.
11. Suite guarded by `pytest.importorskip("sqlcipher3")`; CI jobs per
    A1's tier definitions.

Docs: "Encryption" section in `docs/data-storage-and-backup.md` — key
backends, state machine, encrypt/decrypt and resume, recovery caveat,
and the three-tier platform support table.

---

## End-to-end acceptance

Run the full sequence on the fake host and (Tier 2) real host matrix:

```text
clean install → shadow → verify → activate → verify →
restore --drill → restore
```

Then repeat:

1. with encryption enabled end-to-end (including decrypt afterward);
2. with injected failures during encryption and decryption migration
   (each journal step), during activation, and during restoration —
   every interruption must resume or fail closed with a receipt, never a
   mixed state.

Done means all of the above green, plus:

- `control verify --json` covers every guarantee in
  `docs/control-plane.md` as a named check; verify is provably read-only
  (B6.2); each check has a test turning it red for its own reason and no
  other; identical state reproduces `evidence_sha256`.
- `control restore` proves baseline restoration and active-memory
  additions as two separate receipt blocks and fails closed before
  Phase 2 on any staged mismatch; `--drill` claims exactly what it
  proves, in the specified wording.
- Encryption install claims match the three CI-backed support tiers;
  `keys init` is inert; encrypt and decrypt are both resumable at every
  step; the state file is single, authoritative, and never encrypted.
- `docs/compat-matrix.md` generated from CI; control-plane.md and
  openclaw-setup.md document `verify`, `--drill`, and encryption.
