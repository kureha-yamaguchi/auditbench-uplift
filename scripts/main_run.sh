#!/usr/bin/env bash
# Main defence run on 4xH200 with W&B online (user instruction 2026-10-08), unattended:
#   1 wait for the H200-only ladder (scripts/launch_ladder.sh with SPEC=configs/skypilot/runpod-4xh200-only.yaml)
#   2 grow the landed volume to 500 GB (fp32 exports filled 280 GB in the pilot; exports are converted to bf16 anyway)
#   3 defence-main: 65 GRPO iterations, in-loop dev eval every 5 (W&B), bf16 exports every 5
#   4 standalone dev evaluation of the exports at steps 10,20,...,60,65 (step 0 = the baseline's dev evaluation)
#   5 PLAN §5.3 selection  6 selected checkpoint on the test split  7 collect artefacts, stop the pod
#   bash scripts/main_run.sh > runs_local/sky/main_run.log 2>&1 &
set -uo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd); cd "$REPO"
NODE=${CLUSTER:-auditbench}; NREPO=/workspace/auditbench/auditbench-uplift; DURABLE=/workspace/auditbench
ARM=defence-main; RUN=defence-seed1-main; STEPS="10 20 30 40 50 60 65"; SESSION_CAP=${SESSION_CAP:-600}
SSH="ssh -o BatchMode=yes -o ConnectTimeout=30 $NODE"
say() { echo "$(date -u +%FT%TZ) main_run: $*"; }
collect() {
  mkdir -p reports/evaluations reports/runs/main trajectories
  rsync -az -e "ssh -o BatchMode=yes" "$NODE:$NREPO/reports/evaluations/" reports/evaluations/ 2>/dev/null || true
  rsync -az -e "ssh -o BatchMode=yes" --include='selection-*.json' --exclude='*' "$NODE:$NREPO/reports/" reports/runs/main/ 2>/dev/null || true
  rsync -az -e "ssh -o BatchMode=yes" "$NODE:$DURABLE/spend.json" "$NODE:$DURABLE/runs/$RUN/train.log" "$NODE:$DURABLE/runs/$RUN/export_bf16.log" reports/runs/main/ 2>/dev/null || true
  rsync -az -e "ssh -o BatchMode=yes" --include='*.jsonl' --exclude='*' "$NODE:$NREPO/trajectories/" trajectories/ 2>/dev/null || true
}
fail() { say "FAILED: $*"; collect; rm -f runs_local/sky/HOLD
  (sleep 2700; [ -f runs_local/sky/HOLD ] || { bash scripts/pod_stop.sh; echo "$(date -u +%FT%TZ) main_run: pod stopped after 45 min without a resume"; }) >> runs_local/sky/main_run.log 2>&1 &
  say "pod kept up for 45 min pending a fix; artefacts collected"; exit 1; }
run() { local name=$1; shift; local envs=(); while [ "$1" != "--" ]; do envs+=("$1"); shift; done; shift
  say "step $name: ${envs[*]} run_phase $*"
  env KEEP_POD=1 "${envs[@]}" bash scripts/run_phase.sh "$@" > "runs_local/sky/$name.log" 2>&1 || fail "$name (see runs_local/sky/$name.log)"
  say "step $name: done"; }
export_dir() { $SSH "find $DURABLE/runs/$RUN/exports -maxdepth 3 -name config.json -path '*global_step_$1/*' -printf '%h\n' 2>/dev/null | head -1"; }

# 1. wait for the H200 node
until grep -q "is up on" runs_local/sky/ladder.log 2>/dev/null; do grep -q "non-capacity failure" runs_local/sky/ladder.log 2>/dev/null && fail "ladder"; sleep 60; done
sky status "$NODE" 2>/dev/null | grep -q " UP " || fail "cluster not up"
sky status "$NODE" 2>/dev/null | grep -q "H200" || fail "landed on a non-H200 node (user asked for 4xH200)"
$SSH "touch $DURABLE/KEEP_POD; cd $NREPO && python3 scripts/spend_guard.py session-start --ledger $DURABLE/spend.json --cap $SESSION_CAP" || fail "session cap"
say "node up: $(sky status "$NODE" 2>/dev/null | grep -oE 'RunPod \([A-Z0-9-]+\)' | head -1); session cap \$$SESSION_CAP"

# 2. grow the landed volume to 500 GB (RunPod REST; the volume name carries SkyPilot's suffix)
vol=$(grep -oE "with volume [a-z0-9-]+" runs_local/sky/ladder.log | tail -1 | awk '{print $3}')
set -a; . ./.env; set +a
vid=$(curl -sf -A "auditbench-uplift/1.0" -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/networkvolumes | python3 -c "import json,sys; print(next((v['id'] for v in json.load(sys.stdin) if v['name'].startswith('$vol')), ''))")
if [ -n "$vid" ]; then
  r=$(curl -s -A "auditbench-uplift/1.0" -X PATCH -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" -d '{"size": 500}' "https://rest.runpod.io/v1/networkvolumes/$vid"); say "volume $vol ($vid) resize -> ${r:0:120}"
else say "volume id for $vol not found; continuing with the current size"; fi

# 3. training
run defence-main TRAIN_CONFIG=configs/training/defence-main.yaml -- defence-main
collect

# 4. standalone dev evaluation of the exports (bf16) ; step 0 == base
$SSH "cp -n $NREPO/reports/evaluations/base-dev-step0000.json $NREPO/reports/evaluations/$ARM-dev-step0000.json" || fail "no base dev evaluation on the node"
for s in $STEPS; do
  d=$(export_dir "$s"); [ -n "$d" ] || { say "no export at step $s; skipping"; continue; }
  run "eval-$ARM-dev-step$s" EVAL_SPLIT=dev EVAL_ARM=$ARM EVAL_STEP="$s" EVAL_MODEL="$d" -- eval
done
collect

# 5. selection
.venv/bin/python scripts/select_checkpoint.py --arm $ARM > runs_local/sky/selection-main.log 2>&1 || fail "selection"
S=$(.venv/bin/python -c "import json; print(json.load(open('reports/selection-$ARM.json'))['selected_step'])") || fail "selection output"
say "selected $ARM step S=$S"

# 6. selected on test (and the terminal step when S=0)
sync_test() { [ "$(ls tasks/test 2>/dev/null | wc -l)" -ge 325 ] || fail "tasks/test incomplete"; rsync -rlptDz --no-owner --no-group --delete -e "ssh -o BatchMode=yes" tasks/test/ "$NODE:$DURABLE/test_tasks/" || fail "test task sync"; }
if [ "$S" = 0 ]; then
  say "S=0: base wins on dev; evaluating the terminal step 65 on test as $ARM-final"; d=$(export_dir 65); sync_test
  run "eval-$ARM-final-test" EVAL_SPLIT=test EVAL_ARM=$ARM-final EVAL_STEP=65 EVAL_MODEL="$d" -- eval
else
  d=$(export_dir "$S"); sync_test
  run "eval-$ARM-selected-test" EVAL_SPLIT=test EVAL_ARM=$ARM-selected EVAL_STEP="$S" EVAL_MODEL="$d" -- eval
fi
$SSH "rm -rf $DURABLE/test_tasks"

# 7. artefacts and stop
collect; $SSH "rm -f $DURABLE/KEEP_POD" >/dev/null 2>&1 || true; bash scripts/pod_stop.sh || true
say "ALL DONE: pod stopped; see reports/evaluations, reports/selection-$ARM.json, W&B ky295/auditbench-uplift"
