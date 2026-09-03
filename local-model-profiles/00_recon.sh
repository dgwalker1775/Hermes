#!/usr/bin/env bash
# Full system snapshot: Ollama state, models, Modelfiles, env, GPU/RAM
set -euo pipefail

OUT="${HERMES_FIX_DIR:-$HOME/hermes-fix}/recon_$(date +%Y%m%d_%H%M%S).txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== HERMES LOCAL MODEL RECON ==="
  echo "Date: $(date)"
  echo "Host: $(hostname)"
  echo ""

  echo "--- Ollama version ---"
  ollama --version 2>/dev/null || echo "ollama not found in PATH"

  echo ""
  echo "--- Ollama running models ---"
  ollama ps 2>/dev/null || echo "(none running)"

  echo ""
  echo "--- Ollama model list ---"
  ollama list 2>/dev/null || echo "(error)"

  echo ""
  echo "--- Ollama show (hermes) ---"
  ollama show hermes 2>/dev/null || echo "model 'hermes' not found"

  echo ""
  echo "--- Ollama show (aegis) ---"
  ollama show aegis 2>/dev/null || echo "model 'aegis' not found"

  echo ""
  echo "--- Ollama show (vox) ---"
  ollama show vox 2>/dev/null || echo "model 'vox' not found"

  echo ""
  echo "--- Ollama show (atlas) ---"
  ollama show atlas 2>/dev/null || echo "model 'atlas' not found"

  echo ""
  echo "--- Modelfiles present ---"
  find "$HOME" -maxdepth 4 -name 'Modelfile*' 2>/dev/null | head -20 || echo "(none found)"

  echo ""
  echo "--- Memory ---"
  if command -v vm_stat &>/dev/null; then
    vm_stat | head -10
    echo "Physical RAM: $(sysctl -n hw.memsize | awk '{printf "%.1f GB\n", $1/1073741824}')"
  else
    free -h 2>/dev/null || echo "(free not available)"
  fi

  echo ""
  echo "--- GPU ---"
  if command -v system_profiler &>/dev/null; then
    system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Chipset|VRAM|Metal" | head -8
  else
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || \
      lspci 2>/dev/null | grep -i vga || echo "(GPU info unavailable)"
  fi

  echo ""
  echo "--- Disk (Ollama models) ---"
  du -sh "$HOME/.ollama/models" 2>/dev/null || echo "(no ollama model dir)"

  echo ""
  echo "--- Hermes repo ---"
  find "$HOME" -maxdepth 4 -name 'hermes' -type d 2>/dev/null | head -5
  find "$HOME" -maxdepth 5 -name 'router.py' -o -name 'dispatch*.py' 2>/dev/null | head -10

  echo ""
  echo "--- Environment relevant vars ---"
  env | grep -iE 'OLLAMA|HERMES|MODEL|AGENT|LLM|GPU' | sort || echo "(none)"

  echo ""
  echo "=== END RECON ==="
} | tee "$OUT"

echo ""
echo "Recon saved to: $OUT"
