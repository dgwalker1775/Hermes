#!/usr/bin/env bash
# Benchmark every local Ollama model on 3 standardized prompts with latency
set -euo pipefail

OUT="${HERMES_FIX_DIR:-$HOME/hermes-fix}/benchmark_$(date +%Y%m%d_%H%M%S).txt"
mkdir -p "$(dirname "$OUT")"

MODELS=("hermes" "aegis" "vox" "atlas")

PROMPTS=(
  "In one sentence, describe your primary role and operating constraints."
  "Analyze: a trade signal shows RSI=78, MACD diverging bearish, volume 2x average. What is your assessment?"
  "Draft a 30-word executive summary of a Q3 earnings beat driven by margin expansion."
)
PROMPT_LABELS=("identity" "trade_analysis" "content_gen")

benchmark_model() {
  local model="$1"
  local prompt="$2"
  local label="$3"

  if ! ollama list 2>/dev/null | grep -q "^${model}"; then
    echo "  SKIP: model '${model}' not installed"
    return
  fi

  local start end elapsed response
  start=$(date +%s%3N)
  response=$(echo "$prompt" | timeout 60 ollama run "$model" 2>/dev/null || echo "ERROR: timeout or failure")
  end=$(date +%s%3N)
  elapsed=$(( end - start ))

  echo "  [${label}] ${elapsed}ms"
  echo "  Response: ${response:0:200}"
  echo ""
}

{
  echo "=== HERMES MODEL BENCHMARK ==="
  echo "Date: $(date)"
  echo ""

  for model in "${MODELS[@]}"; do
    echo "--- Model: ${model} ---"
    for i in "${!PROMPTS[@]}"; do
      benchmark_model "$model" "${PROMPTS[$i]}" "${PROMPT_LABELS[$i]}"
    done
    echo ""
  done

  echo "=== END BENCHMARK ==="
} | tee "$OUT"

echo "Benchmark saved to: $OUT"
