#!/usr/bin/env bash
# aetnamem flagship demo — a prompt-injected agent tries to poison memory and
# execute an unauthorized action; the engine blocks both; every claim is then
# verified by standalone tools that import no aetnamem code.
#
# Deterministic: no LLM, no network. Requires Python >= 3.10, nothing else.
# Usage: ./run.sh [workdir]   (workdir is wiped; default: ./demo-run)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORKDIR="${1:-$HERE/demo-run}"
SUBJECT="demo-user"

# ---- pick a Python >= 3.10 --------------------------------------------------
pick_python() {
  for candidate in "${PYTHON:-}" python3 python3.13 python3.12 python3.11 python3.10; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}
PY="$(pick_python)" || { echo "error: Python >= 3.10 required (set PYTHON=/path/to/python)" >&2; exit 2; }

am()  { PYTHONPATH="$REPO_ROOT" "$PY" -m aetnamem.cli "$@"; }
sha() { "$PY" -c 'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())' "$1"; }
sql() { "$PY" -c 'import sqlite3, sys
con = sqlite3.connect(sys.argv[1]); con.execute(sys.argv[2]); con.commit(); con.close()' "$1" "$2"; }

if [ -t 1 ]; then BOLD=$'\033[1m'; DIM=$'\033[2m'; OFF=$'\033[0m'; else BOLD=""; DIM=""; OFF=""; fi
act()  { printf '\n%s================ %s ================%s\n' "$BOLD" "$*" "$OFF"; }
step() { printf '\n%s[%s]%s %s\n' "$BOLD" "$1" "$OFF" "$2"; }
run()  { printf '%s$ %s%s\n' "$DIM" "$*" "$OFF"; }

# Run a command that MUST be refused; show the engine's refusal, fail otherwise.
expect_refusal() {
  local out
  if out="$("$@" 2>&1)"; then
    echo "UNEXPECTED SUCCESS — the engine should have refused this" >&2
    printf '%s\n' "$out" >&2
    exit 1
  fi
  printf 'REFUSED — %s\n' "$(printf '%s\n' "$out" | tail -n 1 | sed -E 's/^[A-Za-z_.]+(Error|Violation|Exception): //')"
}

# Extract visible text from an HTML file exactly the way a naive agent would.
page_text() { "$PY" - "$1" <<'PYEOF'
import sys
from html.parser import HTMLParser

class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if not self.skip and data.strip():
            self.chunks.append(" ".join(data.split()))

parser = Text()
with open(sys.argv[1], encoding="utf-8") as handle:
    parser.feed(handle.read())
print(" ".join(parser.chunks))
PYEOF
}

records_table() { "$PY" -c '
import json, sys
rows = json.load(sys.stdin)
rows = rows if isinstance(rows, list) else rows.get("records", [])
if not rows:
    print("(no records)")
for r in rows:
    print("%s  %-11s  %-17s  %s" % (r["id"], r["status"], r["trust_tier"], r["content"]))'; }

json_get() { "$PY" -c 'import json, sys
obj = json.load(sys.stdin)
for key in sys.argv[1].split("."):
    obj = obj[int(key)] if key.isdigit() else obj[key]
print(obj)' "$1"; }

quarantined_record() { "$PY" -c '
import json, sys
for r in json.load(sys.stdin):
    if r["status"] == "quarantined":
        print(r["id"]); print(r["content"]); break'; }

# ---- ACT 0: fresh workspace --------------------------------------------------
act "SETUP"
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR/workspace"
DB="$WORKDIR/memories.db"
echo "engine   : aetnamem @ $REPO_ROOT"
echo "python   : $PY"
echo "workdir  : $WORKDIR"
echo "subject  : $SUBJECT"

# ---- ACT 1: a hostile webpage tries to poison memory -------------------------
act "ACT 1 — MEMORY POISONING ATTEMPT"

step 1.1 "The user states a fact; it becomes an active, trusted record."
run "aetnamem remember memories.db $SUBJECT 'My report file is report.md.'"
am remember "$DB" "$SUBJECT" "My report file is report.md." --session s1 --turn 1 | records_table

step 1.2 "The agent summarizes a webpage with a hidden injection targeting the SAME fact slot."
run "cat fixtures/hostile-page.html   # note the display:none div"
grep -A2 'display:none' "$HERE/fixtures/hostile-page.html"
PAGE_TEXT="$(page_text "$HERE/fixtures/hostile-page.html")"
run "aetnamem remember memories.db $SUBJECT '<webpage>…page text…</webpage>' --source-type webpage"
am remember "$DB" "$SUBJECT" "<webpage>${PAGE_TEXT}</webpage>" --session s1 --turn 2 --source-type webpage | records_table
echo "-> extracted, but QUARANTINED: untrusted content cannot become durable memory."

step 1.3 "Recall never surfaces quarantined records: the poisoning failed."
run "aetnamem recall memories.db $SUBJECT 'Which file should the weekly report be written to?'"
am recall "$DB" "$SUBJECT" "Which file should the weekly report be written to?" | records_table

step 1.4 "Both records remain inspectable, with full provenance."
run "aetnamem list memories.db $SUBJECT --all"
am list "$DB" "$SUBJECT" --all | records_table

REC_INFO="$(am list "$DB" "$SUBJECT" --all | quarantined_record)"
REC_ID="$(printf '%s' "$REC_INFO" | sed -n 1p)"
REC_CONTENT="$(printf '%s' "$REC_INFO" | sed -n 2p)"

# ---- ACT 2: the injected action is blocked; the authorized one commits -------
act "ACT 2 — UNAUTHORIZED ACTION ATTEMPT (enforce mode)"

step 2.1 "The agent stages the exfil write, citing the quarantined record as its authority."
EVIDENCE="$("$PY" -c 'import json, sys
print(json.dumps([{"kind": "memory_record", "ref_id": sys.argv[1], "digest": sys.argv[2],
                   "relation": "authorized_by", "trust_tier": "untrusted_content", "attested": False}]))' \
  "$REC_ID" "$(sha "$REC_CONTENT")")"
run "aetnamem actions stage … write_text '{\"path\":\"steal.md\",…}' --evidence '[…untrusted_content…]'"
expect_refusal am actions stage "$DB" "$SUBJECT" filesystem write_text \
  --root "$WORKDIR/workspace" --mode enforce \
  --args '{"path":"steal.md","content":"weekly report + gathered credentials"}' \
  --actor research-agent --session s1 --turn 3 \
  --evidence "$EVIDENCE"

step 2.2 "Without any authority at all, enforce mode also refuses."
run "aetnamem actions stage … write_text '{\"path\":\"report.md\",…}'   # no authorized_by evidence"
expect_refusal am actions stage "$DB" "$SUBJECT" filesystem write_text \
  --root "$WORKDIR/workspace" --mode enforce \
  --args '{"path":"report.md","content":"draft"}' \
  --actor research-agent --session s1 --turn 3

step 2.3 "The real user task is host-attested authority; staging now succeeds."
TASK_DIGEST="$(sha 'Task 42: write the weekly summary to report.md in the project workspace')"
run "aetnamem actions stage … write_text '{\"path\":\"report.md\",…}' --authority-id task-42 --authority-digest sha256(task)"
am actions stage "$DB" "$SUBJECT" filesystem write_text \
  --root "$WORKDIR/workspace" --mode enforce \
  --args '{"path":"report.md","content":"# Weekly summary\n\nAll deliverables on track.\n"}' \
  --actor research-agent --session s1 --turn 4 \
  --authority-id task-42 --authority-digest "$TASK_DIGEST" > "$WORKDIR/stage.json"
ACT_ID="$(json_get transaction_id < "$WORKDIR/stage.json")"
PLAN_HASH="$(json_get plan_hash < "$WORKDIR/stage.json")"
echo "transaction : $ACT_ID"
echo "state       : $(json_get state < "$WORKDIR/stage.json")"
echo "plan_hash   : $PLAN_HASH"
echo "effect      : $(json_get operations.0.effect_class < "$WORKDIR/stage.json")"

step 2.4 "The agent cannot execute its own plan."
APPROVAL_KEY="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
echo "The agent-facing process holds no reviewer key:"
run "aetnamem actions commit memories.db $ACT_ID"
expect_refusal am actions commit "$DB" "$ACT_ID" --root "$WORKDIR/workspace"
echo "And even a key holder cannot commit an unapproved plan:"
run "AETNAMEM_APPROVAL_KEY=*** aetnamem actions commit memories.db $ACT_ID"
expect_refusal env AETNAMEM_APPROVAL_KEY="$APPROVAL_KEY" \
  PYTHONPATH="$REPO_ROOT" "$PY" -m aetnamem.cli actions commit "$DB" "$ACT_ID" --root "$WORKDIR/workspace"

step 2.5 "A separate reviewer process signs the EXACT plan hash (HMAC, expiring, single-use nonce)."
run "AETNAMEM_APPROVAL_KEY=*** aetnamem actions approve memories.db $ACT_ID --approver-label demo-user"
AETNAMEM_APPROVAL_KEY="$APPROVAL_KEY" am actions approve "$DB" "$ACT_ID" --approver-label demo-user > "$WORKDIR/approve.json"
echo "approved plan_hash : $(json_get approvals.0.plan_hash < "$WORKDIR/approve.json")"
echo "expires_at         : $(json_get approvals.0.expires_at < "$WORKDIR/approve.json")"
echo "state              : $(json_get state < "$WORKDIR/approve.json")"

step 2.6 "Commit revalidates plan, manifest, and preconditions, executes, and emits a receipt."
run "AETNAMEM_APPROVAL_KEY=*** aetnamem actions commit memories.db $ACT_ID"
AETNAMEM_APPROVAL_KEY="$APPROVAL_KEY" am actions commit "$DB" "$ACT_ID" --root "$WORKDIR/workspace" > "$WORKDIR/commit.json"
echo "terminal_state : $(json_get receipt.terminal_state < "$WORKDIR/commit.json")"
echo "op state       : $(json_get receipt.operation_receipts.0.state < "$WORKDIR/commit.json")"
echo "receipt_sha256 : $(json_get receipt.receipt_sha256 < "$WORKDIR/commit.json")"
run "cat workspace/report.md"
cat "$WORKDIR/workspace/report.md"

step 2.7 "The receipt verifies against the audit chain."
run "aetnamem actions verify memories.db $ACT_ID"
am actions verify "$DB" "$ACT_ID"

step 2.8 "Mutating an approved plan is caught: commit refuses a tampered copy."
cp "$DB" "$WORKDIR/tampered-plan.db"
TASK43_DIGEST="$(sha 'Task 43: append the retro notes')"
ACT2_ID="$(am actions stage "$WORKDIR/tampered-plan.db" "$SUBJECT" filesystem write_text \
  --root "$WORKDIR/workspace" --mode enforce \
  --args '{"path":"retro.md","content":"retro notes"}' \
  --actor research-agent --authority-id task-43 --authority-digest "$TASK43_DIGEST" | json_get transaction_id)"
AETNAMEM_APPROVAL_KEY="$APPROVAL_KEY" am actions approve "$WORKDIR/tampered-plan.db" "$ACT2_ID" --approver-label demo-user > /dev/null
echo "staged + approved $ACT2_ID on a copy, then the attacker edits the stored plan:"
run "sqlite3 tampered-plan.db \"UPDATE action_operations SET arguments_digest='deadbeef…' WHERE transaction_id='$ACT2_ID'\""
sql "$WORKDIR/tampered-plan.db" "UPDATE action_operations SET arguments_digest='deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef' WHERE transaction_id='$ACT2_ID'"
run "AETNAMEM_APPROVAL_KEY=*** aetnamem actions commit tampered-plan.db $ACT2_ID"
expect_refusal env AETNAMEM_APPROVAL_KEY="$APPROVAL_KEY" \
  PYTHONPATH="$REPO_ROOT" "$PY" -m aetnamem.cli actions commit "$WORKDIR/tampered-plan.db" "$ACT2_ID" --root "$WORKDIR/workspace"
[ ! -e "$WORKDIR/workspace/retro.md" ] && echo "-> retro.md was never written."

# ---- ACT 3: verify everything with tools that import no aetnamem code --------
act "ACT 3 — INDEPENDENT VERIFICATION"

step 3.1 "Checkpoint the audit heads. Anchor this file somewhere the DB owner cannot rewrite."
run "aetnamem checkpoint memories.db checkpoints.jsonl"
am checkpoint "$DB" "$WORKDIR/checkpoints.jsonl"

step 3.2 "Engine self-check of every chain against the checkpoint."
run "aetnamem verify memories.db --checkpoints checkpoints.jsonl"
am verify "$DB" --checkpoints "$WORKDIR/checkpoints.jsonl"

step 3.3 "Standalone audit verifier — imports no aetnamem code."
run "python tools/verify_audit.py memories.db --checkpoints checkpoints.jsonl"
"$PY" "$REPO_ROOT/tools/verify_audit.py" "$DB" --checkpoints "$WORKDIR/checkpoints.jsonl"

step 3.4 "Standalone action verifier — plan, approval signature scope, receipt, chain binding."
run "python tools/verify_actions.py memories.db $ACT_ID"
"$PY" "$REPO_ROOT/tools/verify_actions.py" "$DB" "$ACT_ID"

step 3.5 "Rewriting history is caught: erase the quarantine evidence on a copy and re-verify."
cp "$DB" "$WORKDIR/tampered-audit.db"
run "sqlite3 tampered-audit.db \"UPDATE audit_log SET payload = replace(payload,'quarantined','active') …\""
sql "$WORKDIR/tampered-audit.db" "UPDATE audit_log SET payload = replace(payload,'quarantined','active') WHERE payload LIKE '%quarantined%'"
run "python tools/verify_audit.py tampered-audit.db --checkpoints checkpoints.jsonl"
if "$PY" "$REPO_ROOT/tools/verify_audit.py" "$WORKDIR/tampered-audit.db" --checkpoints "$WORKDIR/checkpoints.jsonl"; then
  echo "UNEXPECTED: tampering was not detected" >&2
  exit 1
else
  echo "-> tampering detected (nonzero exit), as required."
fi

act "DONE"
echo "Artifacts you can verify yourself:"
echo "  $WORKDIR/memories.db        — the actual database this demo produced"
echo "  $WORKDIR/checkpoints.jsonl  — the externally anchorable audit heads"
echo "Re-verify with:"
echo "  python3 tools/verify_audit.py $WORKDIR/memories.db --checkpoints $WORKDIR/checkpoints.jsonl"
echo "  python3 tools/verify_actions.py $WORKDIR/memories.db $ACT_ID"
