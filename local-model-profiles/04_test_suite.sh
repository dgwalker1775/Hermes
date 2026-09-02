#!/usr/bin/env bash
# Unit + integration + load + failure tests for the Hermes router
set -euo pipefail

ROUTER="$(dirname "$0")/03_router.py"
OUT="${HERMES_FIX_DIR:-$HOME/hermes-fix}/test_output.txt"
mkdir -p "$(dirname "$OUT")"

PASS=0
FAIL=0

assert_contains() {
  local label="$1" expected="$2" actual="$3"
  if echo "$actual" | grep -qi "$expected"; then
    echo "  ✓ ${label}"
    (( PASS++ )) || true
  else
    echo "  ✗ ${label}"
    echo "    expected to contain: ${expected}"
    echo "    actual: ${actual:0:200}"
    (( FAIL++ )) || true
  fi
}

assert_not_contains() {
  local label="$1" unexpected="$2" actual="$3"
  if ! echo "$actual" | grep -qi "$unexpected"; then
    echo "  ✓ ${label}"
    (( PASS++ )) || true
  else
    echo "  ✗ ${label}"
    echo "    expected NOT to contain: ${unexpected}"
    (( FAIL++ )) || true
  fi
}

run_router() {
  python3 "$ROUTER" --dry-run --json "$1" 2>/dev/null
}

{
  echo "=== HERMES ROUTER TEST SUITE ==="
  echo "Date: $(date)"
  echo ""

  # ── Unit tests: task classification ───────────────────────────────────────
  echo "--- Unit: task classification ---"

  out=$(run_router "RSI is 78 and MACD shows bearish divergence, what trade should I make?")
  assert_contains "trading prompt → AEGIS" "aegis" "$out"
  assert_contains "trading task type" "trading" "$out"

  out=$(run_router "Draft an email to the CFO about Q3 margins")
  assert_contains "email prompt → VOX" "vox" "$out"

  out=$(run_router "Summarize the history of quantitative easing")
  assert_contains "research prompt → ATLAS" "atlas" "$out"

  out=$(run_router "Remind me to review the roadmap tomorrow")
  assert_contains "admin prompt → HERMES" "hermes" "$out"

  echo ""

  # ── Unit tests: approval gates ────────────────────────────────────────────
  echo "--- Unit: approval gates ---"

  out=$(run_router "Place an order to buy 100 shares of AAPL")
  assert_contains "live trade → BLOCKED" "blocked" "$out"

  out=$(run_router "Send this email to the team")
  assert_contains "send email → HARD gate" "hard" "$out"

  out=$(run_router "Search the web for latest CPI data")
  assert_contains "web search → SOFT gate" "soft" "$out"

  out=$(run_router "Analyze the RSI on TSLA weekly chart")
  assert_contains "pure analysis → no gate" "none" "$out"

  echo ""

  # ── Unit tests: JSON output ───────────────────────────────────────────────
  echo "--- Unit: JSON output structure ---"

  out=$(run_router "What is quantitative tightening?")
  assert_contains "JSON has task_type key" "task_type" "$out"
  assert_contains "JSON has agent key" "agent" "$out"
  assert_contains "JSON has model key" "model" "$out"
  assert_contains "JSON has gate key" "gate" "$out"

  echo ""

  # ── Integration tests: Ollama presence ───────────────────────────────────
  echo "--- Integration: Ollama ---"

  if command -v ollama &>/dev/null; then
    echo "  ✓ ollama binary found"
    (( PASS++ )) || true

    installed=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | cut -d: -f1 | tr '\n' ' ')
    echo "  Installed models: ${installed:-none}"

    for agent in hermes aegis vox atlas; do
      if echo "$installed" | grep -qw "$agent"; then
        echo "  ✓ model '${agent}' installed"
        (( PASS++ )) || true
      else
        echo "  ✗ model '${agent}' NOT installed (run 02_rebuild_modelfiles.sh)"
        (( FAIL++ )) || true
      fi
    done
  else
    echo "  ✗ ollama not in PATH — skipping integration tests"
    (( FAIL++ )) || true
  fi

  echo ""

  # ── Load test: rapid classification (no Ollama calls) ────────────────────
  echo "--- Load: 20 rapid dry-run classifications ---"

  prompts=(
    "What is the P/E ratio of NVDA?"
    "Draft a LinkedIn post about AI trends"
    "Explain Black-Scholes model"
    "Write a cold email to a VC"
    "RSI overbought on daily BTC"
    "Summarize this earnings report"
    "Schedule a meeting for Friday"
    "What is quantitative easing?"
    "MACD crossover on SPY — what does this signal?"
    "Rewrite this paragraph more concisely"
    "Research competitors in the fintech space"
    "Send an update to the board"
    "What caused the 2008 financial crisis?"
    "Generate a trade thesis for gold"
    "Draft interview questions for a data scientist"
    "Portfolio rebalancing strategy for volatile markets"
    "Create a content calendar for Q4"
    "Explain momentum investing"
    "Remind me to check the news at 8am"
    "What is the Sharpe ratio?"
  )

  load_pass=0
  load_fail=0
  t0=$(date +%s%3N)
  for p in "${prompts[@]}"; do
    result=$(run_router "$p" 2>/dev/null)
    if echo "$result" | grep -q "task_type"; then
      (( load_pass++ )) || true
    else
      (( load_fail++ )) || true
    fi
  done
  t1=$(date +%s%3N)
  elapsed=$(( t1 - t0 ))

  echo "  ${load_pass}/20 classifications succeeded in ${elapsed}ms"
  if [[ $load_fail -eq 0 ]]; then
    echo "  ✓ load test passed"
    (( PASS++ )) || true
  else
    echo "  ✗ ${load_fail} classifications failed"
    (( FAIL++ )) || true
  fi

  echo ""

  # ── Failure tests: bad input ──────────────────────────────────────────────
  echo "--- Failure: edge cases ---"

  # Empty-ish prompt should still return valid JSON
  out=$(python3 "$ROUTER" --dry-run --json "." 2>/dev/null || echo '{}')
  assert_contains "minimal prompt returns task_type" "task_type" "$out"

  echo ""

  # ── Summary ───────────────────────────────────────────────────────────────
  echo "=== RESULTS: ${PASS} passed, ${FAIL} failed ==="

  if [[ $FAIL -gt 0 ]]; then
    echo "SOME TESTS FAILED — review output above"
  else
    echo "ALL TESTS PASSED"
  fi

} | tee "$OUT"

echo ""
echo "Test output saved to: $OUT"
[[ $FAIL -eq 0 ]]
