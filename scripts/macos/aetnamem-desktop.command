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
LOCAL_MODEL="${AETNAMEM_LOCAL_MODEL:-qwen3:1.7b}"
OLLAMA_URL="${AETNAMEM_OLLAMA_URL:-http://localhost:11434}"

mkdir -p "$(dirname "$AETNAMEM_DB")" "$AETNAMEM_WORKSPACE"

echo "Starting aetnamem desktop..."
echo "Workspace: $AETNAMEM_WORKSPACE"
echo

# --- local model bootstrap (best effort; the app still runs without it) -----
if ! command -v ollama >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing Ollama (one-time, via Homebrew)..."
    brew install --cask ollama || echo "Ollama install failed; continuing without a local model."
  else
    echo "Ollama not found and Homebrew unavailable."
    echo "Install it from https://ollama.com/download to enable the local model."
  fi
fi

if command -v ollama >/dev/null 2>&1; then
  if ! curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "Starting Ollama in the background..."
    nohup ollama serve >/tmp/aetnamem-ollama.log 2>&1 &
    for _ in {1..20}; do
      curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1 && break
      sleep 0.5
    done
  fi
  if curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$LOCAL_MODEL"; then
      echo "Downloading local model $LOCAL_MODEL (one-time)..."
      ollama pull "$LOCAL_MODEL" || echo "Model download failed; you can retry from Settings later."
    fi
    echo "Local model ready: $LOCAL_MODEL"
  else
    echo "Ollama did not start; the assistant will run in offline echo mode."
  fi
fi
echo

# The service signs the dashboard in automatically (tokens ride in the URL
# fragment) and opens the browser itself.
"$PYTHON" -m aetnamem.service --encrypted-db "$AETNAMEM_ENCRYPTED_DB"
