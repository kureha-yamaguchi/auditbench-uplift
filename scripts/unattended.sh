#!/usr/bin/env bash
# Unattended continuation of 2026-10-07 (user instructions: finish Stage 1 within ~8 h with a short defence run and benchmark
# base vs defence-selected on the AuditBench test split with 5 attempts; session ceiling $400; zero further input).
#   bash scripts/unattended.sh > runs_local/sky/unattended.log 2>&1 &
# Steps (each via scripts/run_phase.sh; the pod is kept up between steps by /workspace/auditbench/KEEP_POD and stopped at the end
# or on the first failure):
#   0 wait for the baseline chain  2 pilot (5 it)  1 base on test (after the pilot so the slow local test build can finish)  3 defence-short (10 it)  4 dev evaluation of every export
#   5 §5.3 selection  6 defence-selected on test  7 collect artefacts, stop the pod
# Test tasks are synced to /workspace/auditbench/test_tasks only for the duration of a test evaluation (never during training).
set -uo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd); cd "$REPO"
NODE=${CLUSTER:-auditbench}
NREPO=/workspace/auditbench/auditbench-uplift
DURABLE=/workspace/auditbench
SSH="ssh -o BatchMode=yes -o ConnectTimeout=30 $NODE"
say() { echo "$(date -u +%FT%TZ) unattended: $*"; }
collect() {  # evaluations, selection, reports, trajectory indexes -> laptop
  mkdir -p reports/evaluations reports/runs/unattended trajectories
  rsync -az -e "ssh -o BatchMode=yes" "$NODE:$NREPO/reports/evaluations/" reports/evaluations/ 2>/dev/null || true
  rsync -az -e "ssh -o BatchMode=yes" --include='selection-*.json' --include='iteration_budget.json' --exclude='*' "$NODE:$NREPO/reports/" reports/runs/unattended/ 2>/dev/null || true
  rsync -az -e "ssh -o BatchMode=yes" "$NODE:$DURABLE/spend.json" reports/runs/unattended/ 2>/dev/null || true
  rsync -az -e "ssh -o BatchMode=yes" --include='*.jsonl' --exclude='*' "$NODE:$NREPO/trajectories/" trajectories/ 2>/dev/null || true
}
finish_pod() { $SSH "rm -f $DURABLE/KEEP_POD $DURABLE/test_tasks -r" >/dev/null 2>&1 || true; bash scripts/pod_stop.sh || true; }
fail() {  # keep the pod for 45 min so the watcher can fix and resume (touch runs_local/sky/HOLD to keep it longer); then stop it
  say "FAILED: $*"; collect; rm -f runs_local/sky/HOLD
  (sleep 2700; [ -f runs_local/sky/HOLD ] || { bash scripts/pod_stop.sh; echo "$(date -u +%FT%TZ) unattended: pod stopped after 45 min without a resume"; }) >> runs_local/sky/unattended.log 2>&1 &
  say "pod kept up for 45 min pending a fix; artefacts collected"; exit 1; }
run() {  # name, env assignments..., -- phase
  local name=$1; shift; local envs=(); while [ "$1" != "--" ]; do envs+=("$1"); shift; done; shift
  say "step $name: ${envs[*]} run_phase $*"
  env KEEP_POD=1 "${envs[@]}" bash scripts/run_phase.sh "$@" > "runs_local/sky/$name.log" 2>&1 || fail "$name (see runs_local/sky/$name.log)"
  say "step $name: done"
}
sync_test_tasks() {  # wait for a complete local build (325 sealed test tasks) before syncing; never sync a partial set
  local n=0; for _ in $(seq 1 720); do n=$(ls tasks/test 2>/dev/null | wc -l); [ "$n" -ge 325 ] && ! pgrep -f "auditbench-harbor build" >/dev/null && break; sleep 10; done
  [ "$n" -ge 325 ] || fail "tasks/test incomplete ($n/325)"
  rsync -az --delete -e "ssh -o BatchMode=yes" tasks/test/ "$NODE:$DURABLE/test_tasks/" || fail "test task sync"
}
export_dir() { $SSH "find $DURABLE/runs/$1/exports -maxdepth 3 -name config.json -path '*global_step_$2*' -printf '%h\n' 2>/dev/null | head -1"; }

# 0. baseline: either wait for the after_launch chain, or (RESUME=1) the baseline trials are already indexed on the node's
#    volume from the 2026-10-07 07:03 run and only the step-0 scoring failed (W&B); rescore and continue from the pilot.
if [ "${RESUME:-0}" = 1 ]; then
  until grep -q "is up on" runs_local/sky/ladder.log 2>/dev/null; do grep -q "non-capacity failure" runs_local/sky/ladder.log 2>/dev/null && fail "ladder"; sleep 60; done
  sky status "$NODE" 2>/dev/null | grep -q " UP " || fail "cluster not up"
  $SSH "touch $DURABLE/KEEP_POD; cd $NREPO && python3 scripts/spend_guard.py session-start --ledger $DURABLE/spend.json --cap 400" || fail "session cap"
  if $SSH "test -d $DURABLE/jobs/baseline"; then   # raw job dir on this volume: rescore re-indexes it if the jsonl is gone
    run rescore -- rescore
  else
    # Landed outside CA-MTL-1: the baseline index is on another volume. Regenerate the step-0 dev evaluation of the base model
    # (needed for selection) with the standalone path; the train panel scoring is recovered later from the CA-MTL-1 volume.
    say "baseline.jsonl not on this volume; re-evaluating base on dev for the step-0 scores"
    run eval-base-dev EVAL_SPLIT=dev EVAL_ARM=base EVAL_STEP=0 -- eval
  fi
else
  until grep -qE "baseline finished|baseline FAILED" runs_local/sky/after_launch.log 2>/dev/null; do sleep 60; done
  grep -q "baseline finished" runs_local/sky/after_launch.log || fail "baseline"
  sky status "$NODE" 2>/dev/null | grep -q " UP " || fail "cluster not up after the baseline"
  $SSH "touch $DURABLE/KEEP_POD; cd $NREPO && python3 scripts/spend_guard.py session-start --ledger $DURABLE/spend.json --cap 400" || fail "session cap"
fi
collect; say "baseline scored; session cap \$400 recorded"

# 2. pilot
run pilot -- pilot
[ -n "$(export_dir pilot 5)" ] || fail "pilot produced no HF export at global_step_5"
collect

# 1. base model on test (evaluation only)
sync_test_tasks
run eval-base-test EVAL_SPLIT=test EVAL_ARM=base EVAL_STEP=0 -- eval
$SSH "rm -rf $DURABLE/test_tasks"; collect

# 3. short defence run from original weights
run defence-short TRAIN_CONFIG=configs/training/defence-short.yaml -- defence-short
collect

# 4. standalone dev evaluation of each export; step 0 == base (same weights) reuses the baseline's dev evaluation
$SSH "cp -n $NREPO/reports/evaluations/base-dev-step0000.json $NREPO/reports/evaluations/defence-dev-step0000.json" || fail "no base dev evaluation"
for s in 5 10; do
  d=$(export_dir defence-seed1-short "$s"); [ -n "$d" ] || fail "no export for defence step $s"
  run "eval-defence-dev-step$s" EVAL_SPLIT=dev EVAL_ARM=defence EVAL_STEP="$s" EVAL_MODEL="$d" -- eval
done
collect

# 5. selection (PLAN §5.3) on the laptop from the collected evaluations
.venv/bin/python scripts/select_checkpoint.py --arm defence > runs_local/sky/selection.log 2>&1 || fail "selection"
S=$(.venv/bin/python -c "import json; print(json.load(open('reports/selection-defence.json'))['selected_step'])" 2>/dev/null) || fail "selection output"
say "selected defence step S=$S"

# 6. defence-selected on test
if [ "$S" = 0 ]; then
  say "S=0: the selected checkpoint is the base model; its test evaluation is step 1's. Evaluating the terminal step 10 on test as well (defence-final)."
  d=$(export_dir defence-seed1-short 10); sync_test_tasks
  run eval-defence-final-test EVAL_SPLIT=test EVAL_ARM=defence-final EVAL_STEP=10 EVAL_MODEL="$d" -- eval
else
  d=$(export_dir defence-seed1-short "$S"); sync_test_tasks
  run "eval-defence-selected-test" EVAL_SPLIT=test EVAL_ARM=defence-selected EVAL_STEP="$S" EVAL_MODEL="$d" -- eval
fi
$SSH "rm -rf $DURABLE/test_tasks"

# 7. artefacts and stop
collect; finish_pod
say "ALL DONE: pod stopped; see reports/evaluations, reports/selection-defence.json, runs_local/sky/*.log"
