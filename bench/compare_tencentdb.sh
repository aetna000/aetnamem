#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_DIR="${MEMORYSTACKBENCH_DIR:-"$(cd "$ROOT_DIR/.." && pwd)/ai_lab"}"
TENCENT_DIR="${TENCENTDB_AGENT_MEMORY_DIR:-"$(cd "$ROOT_DIR/.." && pwd)/TencentDB-Agent-Memory_TWO"}"
PYTHON_BIN="${PYTHON:-python3}"
ENV_FILE="${ENV_FILE:-"$ROOT_DIR/.env.aetna-c709e"}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${OUT_DIR:-"/tmp/aetnamem-vs-tencentdb-$RUN_ID"}"

if [[ ! -d "$BENCH_DIR/memorybench" ]]; then
  echo "MemoryStackBench checkout not found: $BENCH_DIR" >&2
  echo "Set MEMORYSTACKBENCH_DIR=/path/to/MemoryStackBench" >&2
  exit 2
fi

if [[ ! -d "$TENCENT_DIR" ]]; then
  echo "TencentDB-Agent-Memory checkout not found: $TENCENT_DIR" >&2
  echo "Set TENCENTDB_AGENT_MEMORY_DIR=/path/to/TencentDB-Agent-Memory" >&2
  exit 2
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

mkdir -p "$OUT_DIR"

# Keep the benchmark repo as the neutral runner, but overlay aetnamem's local
# adapter/target just like CI does until the target is upstreamed there.
cp "$ROOT_DIR/bench/adapters/aetnamem.py" "$BENCH_DIR/memorybench/adapters/aetnamem.py"
cp "$ROOT_DIR/bench/targets/aetnamem.yaml" "$BENCH_DIR/targets/aetnamem.yaml"

export PYTHONPATH="$BENCH_DIR:$ROOT_DIR"
export TENCENTDB_AGENT_MEMORY_DIR="$TENCENT_DIR"

run_target() {
  local name="$1"
  local target="$2"
  local out="$OUT_DIR/$name"
  local log="$OUT_DIR/$name.time.log"

  echo "==> Running $name"
  /usr/bin/time -p -o "$log" "$PYTHON_BIN" -m memorybench.cli run \
    --target "$target" \
    --suite "$BENCH_DIR/suites/seven_sins_v0_1" \
    --out "$out"

  "$PYTHON_BIN" - "$out/scorecard.json" "$log" <<'PY'
import json
import sys
from pathlib import Path

scorecard = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
timing = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
print("score:", scorecard["overall"])
print(timing)
PY
}

run_target "aetnamem" "$BENCH_DIR/targets/aetnamem.yaml"
run_target "tencentdb-agent-memory" "$BENCH_DIR/targets/tencentdb_agent_memory.yaml"

echo
echo "Artifacts: $OUT_DIR"
