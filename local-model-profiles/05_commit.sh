#!/usr/bin/env bash
# Commit rebuilt Modelfiles and router to the Hermes repo
set -euo pipefail

REPO="${HERMES_REPO:-$HOME/hermes-fix}"
MODELFILES="${HERMES_FIX_DIR:-$HOME/hermes-fix}/modelfiles"

if [[ ! -d "$REPO/.git" ]]; then
  echo "No git repo found at $REPO — skipping commit"
  exit 0
fi

cd "$REPO"

echo "=== Staging files ==="
cp -v "$MODELFILES"/Modelfile.* . 2>/dev/null || true
git add Modelfile.* 2>/dev/null || true
git add local-model-profiles/ improvement_loop.py 2>/dev/null || true

echo ""
echo "=== Status ==="
git status

echo ""
echo "=== Committing ==="
git commit -m "feat(local-models): rebuild Modelfiles and add dynamic router

- Rewrote Modelfiles for hermes/aegis/vox/atlas with correct SYSTEM prompts,
  per-agent temperatures, and Phase Zero hard constraints
- Added 03_router.py: task classification → agent → model selection with
  memory pressure override and approval gates
- Added diagnostic, benchmark, and test scripts (00–04)
- All trade signals advisory only; no external actions without human approval
- Added improvement_loop.py: self-terminating benchmark/auto-tune/cron loop
  (scores all agents each run, nudges temperatures, self-removes after 3
   consecutive converged runs or 50-run hard ceiling, sends Telegram reports)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XQT7j7cBtJ83eFL8R91WXM" || echo "Nothing to commit"

echo ""
echo "=== Done ==="
