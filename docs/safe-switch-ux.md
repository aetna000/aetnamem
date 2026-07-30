# AetnaMem Safe Switch — CLI and dashboard UX specification

Current implemented subset: v0.6.1.1a3 experimental · Status: design contract with future
comparison/report sections.

The [Safe Switch guide](safe-switch.md) and
[current capability status](current-status.md) are the implementation truth.
The shipped dashboard provides live mode, candidate review, evidence and
transition controls. Comparison charts, exported readiness reports and paid
paired evaluation described below remain design targets, not public product
claims.

## Design principles

1. **The mode is the interface.** At any moment the user must be able to
   answer "is AetnaMem influencing my agent right now?" in under one second,
   from any screen. The mode banner is always present, color-coded, and
   worded in plain language.
2. **One primary action per state.** Every screen ends in exactly one
   suggested next step. Everything else is secondary.
3. **Evidence is labeled or it is not shown.** Every number carries a
   Verified / Estimated / Observed chip. An aggregate inherits the weakest
   label among its inputs. Never mix labels inside one number.
4. **Privileged actions are ceremonies.** Activation, canary, and rollback
   use explicit multi-step confirmation. Nothing privileged ever happens from
   a single click or a bare command.
5. **Rollback is never more than one step away.** The emergency `off` control
   is visible in the persistent chrome in every mode except `off`.

## Design tokens

Implement as CSS custom properties on `:root`, redefined under
`@media (prefers-color-scheme: dark)` and again under
`:root[data-theme="dark"]` / `:root[data-theme="light"]` (explicit toggle
wins in both directions).

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#F7F8F7` | `#0F1715` | page ground |
| `--raised` | `#FFFFFF` | `#16211F` | cards, modals |
| `--ink` | `#1A2B2F` | `#E4ECEA` | primary text |
| `--muted` | `#5B6E72` | `#8CA09B` | secondary text |
| `--hairline` | `#DDE4E2` | `#263531` | borders, grid |
| `--accent` | `#008A70` | `#0EA88C` | AetnaMem identity, links, primary buttons |
| `--series-aetnamem` | `#008A70` | `#0EA88C` | chart series (validated) |
| `--series-current` | `#8256E8` | `#8E75E8` | chart series (validated) |
| `--good` | `#1B7F4D` | `#3FAE72` | status only |
| `--warn` | `#9A5B00` | `#D99A3D` | status only |
| `--critical` | `#B3261E` | `#E5716A` | status only |

The two chart series pairs pass all six palette checks (lightness band,
chroma floor, CVD separation, normal-vision floor, contrast) on their
respective surfaces — do not substitute hues without re-validating.
Status colors are reserved for state; never use them as chart series.
Charts always carry a legend plus direct labels; identity is never
color-alone.

Type: UI text in the platform grotesque stack
(`system-ui, -apple-system, "Segoe UI", sans-serif`); all digests, IDs,
counts, CLI text, and evidence values in the platform mono stack
(`ui-monospace, "SF Mono", "Cascadia Code", monospace`) with
`font-variant-numeric: tabular-nums`. Scale: 13px base UI, 15px reading
text, 20/28/40px headings, 11px uppercase labels with 0.08em tracking.

Mode → color mapping (banner, chips, rail indicator):

| Mode | Color | Banner headline |
|---|---|---|
| Off | neutral gray | `OFF — AETNAMEM IS NOT RUNNING` |
| Capture | accent teal | `OBSERVING — NOT INFLUENCING YOUR AGENT` |
| Preview | accent teal | `PREVIEWING — NOT SHOWN TO THE AGENT` |
| Canary | warning amber | `CANARY — INFLUENCING n OF LAST 20 FRESH SESSIONS` |
| Active | good green | `ACTIVE — AETNAMEM CONTEXT IS ENABLED` |
| Rollback in progress | critical red | `ROLLING BACK — RESTORING SNAPSHOT` |

## CLI design

### Command surface

Two renames from the draft plan, for safety-in-language:
`trial enable --canary-turns` becomes `trial canary --turns` ("enable" reads
like full activation), and emergency stop is its own verb.

```
aetnamem openclaw install                         # verified OpenClaw setup
aetnamem trial start [--host auto|openclaw|hermes]
aetnamem trial status
aetnamem trial candidates
aetnamem trial preview [--query TEXT]           # observer-only
aetnamem trial approve <candidate-id...>
aetnamem trial reject <candidate-id...>
aetnamem trial canary --turns N                 # limited fresh-session exposure
aetnamem trial activate                         # full switch, guarded ceremony
aetnamem trial rollback                         # turn off and restore host snapshot
aetnamem trial off                              # emergency: state-file kill, no restart needed
aetnamem dashboard
aetnamem dashboard daemon start --port 8766
```

Paid paired comparison, exported readiness reports, and receipt-backed purge
are later milestones; they are not accepted commands in 0.6.1.1a3.

### Output conventions

- The 0.6.1.1a3 CLI prints a human-readable `State`/`Next` view by default.
  Automation receives the same underlying result with `--json`.
- Respect `NO_COLOR`. Never encode meaning in color alone — state words are
  always printed.
- Privileged commands (`canary`, `activate`, `rollback`)
  print what will change, then require typing the host name (e.g.
  `openclaw`) to proceed. `--yes` exists for scripts but still refuses if a
  readiness gate fails; there is no flag that overrides a failed gate.
- A future `trial compare` must state estimated provider cost and ask for
  consent before spending; it must never run on install or on a schedule.

### Example transcripts (canonical wording)

`aetnamem trial start --host auto`:

```
AetnaMem Safe Switch trial

  Host detected      OpenClaw 2026.7 (config digest 8f2…91c)
  Snapshot saved     ~/.aetnamem/trials/t-0725/rollback.json
  Trial database     ~/.aetnamem/trials/t-0725/trial.db (separate from live memory)
  Mode               capture — observing only

  AetnaMem is NOT injecting context, exposing tools, or calling models.
  Your current memory and provider remain in control.

  Dashboard: http://127.0.0.1:8766  (local only)

State: capture
Next:  let it observe for a while, then: aetnamem trial status
```

`aetnamem trial activate` (gates passing):

```
Activate AetnaMem for OpenClaw

  This changes your agent's live memory configuration.

  Config diff (2 keys, AetnaMem-owned only):
    + memory.provider = aetnamem
    + memory.context_budget_tokens = 1200

  Snapshot digest    8f2…91c (matches current config — no drift)
  Readiness          READY FOR LIMITED CANARY → canary completed 20/20 healthy
  Rollback           tested 2026-07-27 (4.1s)

  Type the host name to confirm: openclaw

  Applying… ✓ config applied ✓ host reloaded ✓ health probe passed

State: active
Next:  inspect current evidence: aetnamem trial status
```

Gate-blocked activation prints the failing gates verbatim from the
readiness card and exits 2 — same words in CLI and dashboard, always.

## Mode state machine

```
off → capture → preview ⇄ capture
preview → (compare jobs, isolated) → canary → active
any mode → off            (emergency, via state file; works even if host restart fails)
canary|active → rollback → off (snapshot restored)
missing/corrupt state file → off  (fail closed, never fail into an influencing mode)
```

The agent can never trigger a transition. Only the CLI and dashboard can,
and both write through the same state manager with the same gates.

## Dashboard information architecture

Persistent chrome:

- **Top status bar** (always visible): mode chip with color + word, host
  chip, subject, elapsed capture time, and — in any mode except `off` — an
  `Emergency off` button on the far right. Emergency off asks one plain
  confirm ("Stop AetnaMem influencing your agent immediately? Your host
  keeps running.") and works through the state file.
- **Left rail**: six sections in journey order — Overview, Memory, Recall
  Preview, Comparison, Switch, Value — each with a state dot (gray = not
  started, teal = has data, amber = needs attention, green = passed).
  Rail footer shows trial ID, data directory, and AetnaMem version.

Sections (job → content → primary action):

1. **Overview** — orient. Mode banner (hero), four stat tiles (captured
   turns, memory candidates, sessions observed, replay budget spent), a
   "What AetnaMem is *not* doing right now" list matching the mode table
   from the plan, and one next-step card. Primary action follows the
   journey (e.g. in capture: "Review captured memories").
2. **Memory** — review. Filter chips (Candidate / Quarantined / Conflict /
   Superseded / Forgotten / All), list rows: content, status chip, source
   chip, provenance disclosure (episode, digests, extractor for media),
   per-row Approve / Reject, bulk bar for reviewed selections. Approving
   makes the item eligible for preview and a later user-confirmed
   canary/active mode. In preview, copy must say "Approved for preview. Not
   visible to your agent in the current mode."
3. **Recall Preview** — build trust. Permanent banner: "Previews are
   computed after the fact. Nothing here was shown to your agent." Turn
   list; detail pane: the query, what AetnaMem would have recalled with a
   one-line reason each ("matched fact slot · trusted · 3 weeks old"),
   context size vs. budget bar, manifest digest in mono.
4. **Comparison** — prove. The readiness card is the centerpiece (see
   below). Below it: paired-bar chart of verified success, token/cost
   tiles, retrieval accuracy, safety counts — every figure with its
   evidence chip. "Run comparison" states cost and requires consent.
5. **Switch** — the ceremony. Pre-flight gate checklist (each gate with its
   measured value and PASS/FAIL/PENDING), exact config diff in mono,
   snapshot digest + drift check, canary controls (turns stepper, start),
   Activate (disabled until gates pass — disabled state shows *why*),
   Rollback card, emergency-off explainer.
6. **Value** — after the switch. Live tiles: context supplied per session,
   verified token trend (line chart, hover tooltip), corrections,
   quarantine interceptions, deletion receipts, audit chain health. Each
   number keeps its evidence chip; "estimated savings" is never presented
   as verified.

### Readiness card specification

Layout: verdict strip (one of the five conclusions, colored by severity) →
host/model/config digests in mono → two-column Current vs AetnaMem table
(success, complete prompt tokens, provider cost, median latency — deltas
computed, one decimal) → safety block (target-memory retrieval, irrelevant
recalls, stale memories shown, unsafe actions) → integrity block (audit
chain, deletion drill, rollback test) → gate checklist with measured values
→ primary action. Verdict wording maps 1:1 to the plan's five conclusions;
the CLI prints the identical card in monospace. The gate config is
digest-pinned and shown on the card so a report cannot be reshaped after
the fact.

### Evidence chips

- **Verified** — filled chip, check icon. Provider telemetry or host-verifier
  evidence; tooltip names the source and receipt digest.
- **Estimated** — outlined chip, tilde icon. Tokenizer or price projection;
  tooltip names the method.
- **Observed** — outlined chip, eye icon. Descriptive before/after only;
  tooltip: "Not causal proof."

### Guarded activation flow (dashboard)

Four-step modal, no step skippable: 1) exact diff + snapshot digest with
drift check; 2) gate checklist re-run live; 3) typed host-name
confirmation; 4) progress (apply → reload → health probe) with automatic
return to `off` and a visible incident note if any step fails. During
canary and active, the Switch section keeps a one-click `Roll back` button
with the tested-rollback timestamp next to it.

## Charts

- Success: paired bars per arm, `--series-current` vs `--series-aetnamem`,
  4px rounded data-ends, 2px gaps, direct value labels, legend, single axis.
- Tokens over time (Value): single-series line, 2px stroke, endpoint
  emphasized and direct-labeled, faint hairline grid, crosshair tooltip.
- Never dual-axis. Every chart offers a table view toggle for
  accessibility and audit copy-paste.

## Security and accessibility checklist (release gate)

Security (dashboard controls host config, so this is not optional):
bind 127.0.0.1 only; session token issued at `trial start`, not stored in
localStorage (HttpOnly cookie); Host/Origin checks; CSP with no external
sources; CSRF token on every mutating route; `Cache-Control: no-store`;
stored-XSS tests over memory content rendered in the UI (memory text is
attacker-influenced by definition); privileged routes re-verify mode and
gates server-side.

Accessibility: all state encoded in word + shape + color (never color
alone); full keyboard path through review, canary, activation with visible
focus; `prefers-reduced-motion` respected; charts have table equivalents;
mode banner is `role="status"` so screen readers announce transitions.

## UI acceptance criteria

1. From any screen, mode is identifiable with the page's top 60px only.
2. Kill the dashboard process mid-activation → state resolves to `off`,
   never a half-applied config (state file is written before host changes).
3. Every number on Comparison and Value carries exactly one evidence chip.
4. Activation with any failed gate is impossible in both CLI and dashboard,
   and both show the same failing-gate wording.
5. Memory review actions never mutate live agent memory in capture/preview.
6. The readiness card renders identically (same numbers, same verdict) in
   dashboard, CLI, and exported report.html.
7. Both themes pass the palette validator; charts re-validated per theme.

## Visual source

The implemented UI in `aetnamem/trial/ui.py` is the product source. Earlier
clickable mockups and their state simulators were design communication only
and must not be presented as working product behavior.
