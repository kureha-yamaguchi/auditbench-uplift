#!/usr/bin/env bash
# Unattended continuation once scripts/launch_ladder.sh has brought the cluster up: smoke (pod kept up, includes the
# vLLM context-contract check and an 8-task Qwen run), then the baseline (the pod stops itself at the end). If the smoke
# fails, the pod is stopped so nothing bills idle, and the log says why.
#   bash scripts/after_launch.sh runs_local/sky/ladder.log
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd); cd "$REPO"
LADDER_LOG=${1:-runs_local/sky/ladder.log}
until grep -q "is up on" "$LADDER_LOG" 2>/dev/null; do
  if grep -qE "non-capacity failure" "$LADDER_LOG" 2>/dev/null; then echo "after_launch: ladder stopped on a failure; not continuing"; exit 1; fi
  sleep 30
done
echo "$(date -u +%FT%TZ) after_launch: cluster up; running smoke"
if KEEP_POD=1 bash scripts/run_phase.sh smoke > runs_local/sky/smoke.log 2>&1; then
  echo "$(date -u +%FT%TZ) after_launch: smoke passed; running baseline (pod stops itself at the end)"
  bash scripts/run_phase.sh baseline > runs_local/sky/baseline.log 2>&1 && echo "$(date -u +%FT%TZ) after_launch: baseline finished" || { echo "$(date -u +%FT%TZ) after_launch: baseline FAILED (see runs_local/sky/baseline.log)"; bash scripts/pod_stop.sh || true; exit 1; }
else
  echo "$(date -u +%FT%TZ) after_launch: smoke FAILED (see runs_local/sky/smoke.log); stopping the pod"
  bash scripts/pod_stop.sh || true
  exit 1
fi
