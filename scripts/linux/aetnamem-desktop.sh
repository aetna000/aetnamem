#!/usr/bin/env bash
# aetnamem desktop launcher for Linux (Ubuntu/Debian and RHEL/Fedora/CentOS).
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This launcher is Linux-only. Use scripts/macos/aetnamem-desktop.command on macOS."
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

# Detect the package manager so error messages give copy-paste commands.
if command -v apt-get >/dev/null 2>&1; then
  PY_INSTALL_HINT="sudo apt-get update && sudo apt-get install -y python3"
elif command -v dnf >/dev/null 2>&1; then
  PY_INSTALL_HINT="sudo dnf install -y python3"
elif command -v yum >/dev/null 2>&1; then
  PY_INSTALL_HINT="sudo yum install -y python3"
else
  PY_INSTALL_HINT="install Python 3.10+ with your distribution's package manager"
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3 not found. Install it first:"
  echo "  $PY_INSTALL_HINT"
  exit 1
fi

if ! "$PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "Python 3.10 or newer is required (found $("$PYTHON" --version 2>&1))."
  echo "  $PY_INSTALL_HINT"
  exit 1
fi

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export AETNAMEM_DB="${AETNAMEM_DB:-$DATA_HOME/aetnamem/memories.db}"
export AETNAMEM_WORKSPACE="${AETNAMEM_WORKSPACE:-$HOME/aetnamem-workspace}"
LOCAL_MODEL="${AETNAMEM_LOCAL_MODEL:-qwen3:1.7b}"
OLLAMA_URL="${AETNAMEM_OLLAMA_URL:-http://localhost:11434}"

mkdir -p "$(dirname "$AETNAMEM_DB")" "$AETNAMEM_WORKSPACE"

echo "Starting aetnamem desktop..."
echo "Workspace: $AETNAMEM_WORKSPACE"
echo

# --- local model bootstrap (best effort; the app still runs without it) -----
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama (one-time, official installer)..."
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh || \
      echo "Ollama install failed; continuing without a local model."
  else
    echo "curl not found — install Ollama manually from https://ollama.com/download/linux"
  fi
fi

if command -v ollama >/dev/null 2>&1; then
  if ! curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "Starting Ollama in the background..."
    # The official installer usually registers a systemd service; try that first.
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
      sudo systemctl start ollama 2>/dev/null || true
    fi
    if ! curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
      nohup ollama serve >/tmp/aetnamem-ollama.log 2>&1 &
    fi
    for _ in $(seq 1 20); do
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

# At-rest database sealing is macOS-only (Keychain); on Linux the database
# stays at $AETNAMEM_DB. The service signs the dashboard in automatically
# (tokens ride in the URL fragment) and opens the browser itself.
"$PYTHON" -m aetnamem.service --db "$AETNAMEM_DB" --workspace "$AETNAMEM_WORKSPACE"
