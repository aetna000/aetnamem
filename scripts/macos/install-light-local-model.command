#!/bin/zsh
set -euo pipefail

MODEL="${AETNAMEM_LOCAL_MODEL:-qwen3:1.7b}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper is intended for macOS."
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is required for the local light model."
  echo "Install it from https://ollama.com/download, then run this script again."
  exit 1
fi

echo "Pulling aetnamem local light model: $MODEL"
ollama pull "$MODEL"

echo
echo "Starting Ollama in the background if it is not already running..."
if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >/tmp/aetnamem-ollama.log 2>&1 &
  sleep 2
fi

echo "Local model ready: $MODEL"
