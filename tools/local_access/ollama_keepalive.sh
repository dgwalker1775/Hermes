#!/usr/bin/env bash
# Keeps local12b-hermes:latest warm in Ollama VRAM.
# Called by launchd every 240s. Sends a keep_alive=-1 ping
# so the model is never evicted between Hermes sessions.
# Also pins any other models listed in MODELS below.

set -euo pipefail

MODELS=(
    "local12b-hermes:latest"
)

OLLAMA_URL="http://localhost:11434"

for model in "${MODELS[@]}"; do
    curl -sf -X POST "$OLLAMA_URL/api/generate" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"$model\",\"prompt\":\"\",\"keep_alive\":-1}" \
        -o /dev/null \
        && echo "$(date -Iseconds) [keepalive] $model pinned" \
        || echo "$(date -Iseconds) [keepalive] $model unavailable (Ollama down?)"
done
