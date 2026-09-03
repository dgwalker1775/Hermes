#!/usr/bin/env bash
# Master run script — executes the full fix pipeline in sequence.
# Run from your home directory: bash ~/hermes-fix/RUN_ME_FIRST.sh
set -euo pipefail

export HERMES_FIX_DIR="${HERMES_FIX_DIR:-$HOME/hermes-fix}"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

step() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  STEP $1: $2"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║         HERMES LOCAL MODEL FIX — MASTER PIPELINE          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Output dir: $HERMES_FIX_DIR"
mkdir -p "$HERMES_FIX_DIR"

# ── 0: prereqs ────────────────────────────────────────────────────────────────
step 0 "Checking prerequisites"
errors=0

if ! command -v ollama &>/dev/null; then
  echo "  ✗ ollama not found — install from https://ollama.com/download"
  (( errors++ )) || true
else
  echo "  ✓ ollama $(ollama --version 2>/dev/null | head -1)"
fi

if ! command -v python3 &>/dev/null; then
  echo "  ✗ python3 not found"
  (( errors++ )) || true
else
  echo "  ✓ python3 $(python3 --version)"
fi

if [[ $errors -gt 0 ]]; then
  echo ""
  echo "Fix the above errors then re-run this script."
  exit 1
fi

# ── 1: recon ──────────────────────────────────────────────────────────────────
step 1 "System recon"
bash "$SCRIPTS_DIR/00_recon.sh"

# ── 2: benchmark (optional — skip if no models yet) ───────────────────────────
step 2 "Model benchmark (pre-fix)"
if ollama list 2>/dev/null | grep -q hermes; then
  bash "$SCRIPTS_DIR/01_model_benchmark.sh"
else
  echo "  No hermes model installed yet — skipping pre-fix benchmark"
fi

# ── 3: rebuild modelfiles ─────────────────────────────────────────────────────
step 3 "Rebuild Modelfiles and recreate Ollama models"
bash "$SCRIPTS_DIR/02_rebuild_modelfiles.sh"

# ── 4: post-fix benchmark ─────────────────────────────────────────────────────
step 4 "Model benchmark (post-fix)"
bash "$SCRIPTS_DIR/01_model_benchmark.sh"

# ── 5: test suite ─────────────────────────────────────────────────────────────
step 5 "Router test suite"
if bash "$SCRIPTS_DIR/04_test_suite.sh"; then
  TESTS_OK=true
else
  TESTS_OK=false
fi

# ── 6: optional commit ────────────────────────────────────────────────────────
step 6 "Git commit (if in repo)"
bash "$SCRIPTS_DIR/05_commit.sh" || true

# ── 7: arm improvement loop cron ─────────────────────────────────────────────
step 7 "Arm self-terminating improvement loop (cron every 60 min)"
LOOP_SCRIPT="$SCRIPTS_DIR/improvement_loop.py"
if python3 "$LOOP_SCRIPT" --install-cron 60; then
  echo "  ✓ Improvement loop armed — runs every 60 min"
  echo "    Status:  python3 $LOOP_SCRIPT --status"
  echo "    Kill it: python3 $LOOP_SCRIPT --remove-cron"
else
  echo "  ✗ Could not arm cron — run manually: python3 $LOOP_SCRIPT --install-cron 60"
fi

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                     PIPELINE COMPLETE                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Outputs written to: $HERMES_FIX_DIR"
echo ""
echo "Files:"
ls -lh "$HERMES_FIX_DIR"/*.txt "$HERMES_FIX_DIR"/*.jsonl 2>/dev/null || echo "  (no output files)"
echo ""

if $TESTS_OK; then
  echo "✓ All tests passed. Paste test_output.txt back to Claude to confirm."
else
  echo "✗ Some tests failed. Paste test_output.txt back to Claude for diagnosis."
fi
echo ""
echo "Next step — wire the router into Hermes dispatch:"
echo "  python3 $SCRIPTS_DIR/03_router.py --json 'your prompt here'"
