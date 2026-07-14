#!/bin/zsh
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "aetnamem desktop launcher is macOS-only."
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "Python 3.10 or newer is required. Install Python from python.org or Homebrew."
  exit 1
fi

export AETNAMEM_DB="${AETNAMEM_DB:-$HOME/Library/Application Support/aetnamem/memories.db}"
export AETNAMEM_WORKSPACE="${AETNAMEM_WORKSPACE:-$HOME/Aetnamem Workspace}"
export AETNAMEM_ENCRYPTED_DB="${AETNAMEM_ENCRYPTED_DB:-$HOME/Library/Application Support/aetnamem/memories.db.enc}"

mkdir -p "$(dirname "$AETNAMEM_DB")" "$AETNAMEM_WORKSPACE"

echo "Starting aetnamem desktop..."
echo "Workspace: $AETNAMEM_WORKSPACE"
echo
"$PYTHON" -m aetnamem.service --encrypted-db "$AETNAMEM_ENCRYPTED_DB"
