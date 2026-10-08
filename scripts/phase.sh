#!/usr/bin/env bash
# One experiment phase on the SkyPilot node. Every phase runs under the spend guard and ends by
# stopping the pod unless KEEP_POD=1, so idle time is never billed.
#   bash scripts/phase.sh smoke     # oracle smoke on two dev tasks (Modal sandboxes, isolation probe)
#   bash scripts/phase.sh baseline  # vLLM up, five attempts per train and dev task, index + score
#   bash scripts/phase.sh pilot     # sampling manifest + 10-iteration GRPO pilot + iteration budget
#   bash scripts/phase.sh defence   # main defence run (T_max from the pilot), selection
#   bash scripts/phase.sh control   # control run to the defence terminal step
set -euo pipefail
PHASE=${1:?phase}
DURABLE=/workspace/auditbench
REPO="$DURABLE/auditbench-uplift"
# `sky exec` syncs the workdir to ~/sky_workdir but does not rerun setup, so refresh the durable repo copy from it
# first (same rules as node_bootstrap.sh; node-generated trajectories/ and reports/ are left alone).
SRC="${SKY_WORKDIR:-$HOME/sky_workdir}"
if [ -d "$SRC" ] && [ "$(cd "$SRC" && pwd -P)" != "$(cd "$REPO" && pwd -P)" ]; then
  rsync -rlptD --no-owner --no-group --delete --exclude .venv --exclude .env --exclude 'tasks/test' --exclude jobs \
    --exclude trajectories --exclude reports "$SRC/" "$REPO/"
fi
cd "$REPO"
mkdir -p "$DURABLE/reports"
source "$DURABLE/harbor-train/skyrl-train/.venv/bin/activate"
export HF_HOME="$DURABLE/hf" AUDITBENCH_SANDBOX=${AUDITBENCH_SANDBOX:-modal}
# W&B: no writable entity for this API key (2026-10-07: "entity not found" / "permission denied" crashed scoring). Offline mode
# keeps wandb.init/log working (local run files under wandb/) without network writes; durable records stay authoritative.
export WANDB_MODE=${WANDB_MODE:-online}   # entity ky295 (verified writable 2026-10-08); set offline if W&B is unreachable
# Hourly rate for the spend ledger: the pod's actual price (the GPU ladder in configs/skypilot may have landed on a
# cheaper type than 4xH200), else POD_RATE_USD_PER_HOUR, else the 4xH200 list price.
RATE=${POD_RATE_USD_PER_HOUR:-}
if [ -z "$RATE" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
  RATE=$(python3 scripts/runpod_api.py status "$RUNPOD_POD_ID" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("costPerHr"); print(v if v else "")' || true)
fi
RATE=${RATE:-18.36}
echo "phase=$PHASE pod=${RUNPOD_POD_ID:-?} rate_usd_per_hour=$RATE gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"

case "$PHASE" in smoke|baseline) guard_phase=setup_smoke_baseline;; eval) guard_phase=eval;; defence-short|defence-main) guard_phase=defence;; *) guard_phase=$PHASE;; esac
python scripts/spend_guard.py watch --ledger "$DURABLE/spend.json" --phase "$guard_phase" --rate "$RATE" \
  --stop-file "$DURABLE/STOP" --stop-cmd "pkill -f harbor; pkill -f main_harbor; pkill -f vllm" --stop-pod self \
  > "$DURABLE/spend_guard.$PHASE.log" 2>&1 &
GUARD=$!
finish() {
  rc=$?
  kill "$GUARD" 2>/dev/null || true
  # Completion marker polled by scripts/run_phase.sh over ssh (the local SkyPilot API server is unreliable for long jobs).
  [ -n "${RUN_TAG:-}" ] && { mkdir -p "$DURABLE/phase_status"; echo "$rc" > "$DURABLE/phase_status/$RUN_TAG.exit"; }
  rsync -rlptD --no-owner --no-group "$REPO/reports/" "$DURABLE/reports/" 2>/dev/null || true
  if [ "${KEEP_POD:-0}" != 1 ]; then python scripts/runpod_api.py stop "${RUNPOD_POD_ID:-}" || true; fi
}
trap finish EXIT

vllm_up() {
  if pgrep -f "vllm.entrypoints.openai.api_server" >/dev/null; then
    curl -sf localhost:8000/v1/models >/dev/null && return
    echo "stale vLLM processes without a healthy endpoint; restarting"; pkill -f "vllm.entrypoints.openai.api_server" || true; sleep 5
  fi
  [ "$(nvidia-smi -L 2>/dev/null | wc -l)" -ge 4 ] || { echo "phase needs 4 visible GPUs (run via scripts/run_phase.sh, which passes --gpus)"; nvidia-smi -L; exit 1; }
  # EVAL_MODEL: serve a local HF export instead of the pinned base revision (same tokenizer/template; served name unchanged).
  if [ -n "${EVAL_MODEL:-}" ]; then MODEL_ARGS="--model $EVAL_MODEL --tokenizer Qwen/Qwen3-8B"; else MODEL_ARGS="--model Qwen/Qwen3-8B --revision b968826d9c46dd6066d109eabc6255188de91218"; fi
  nohup python -m vllm.entrypoints.openai.api_server $MODEL_ARGS \
    --served-model-name Qwen3-8B --tensor-parallel-size 1 --data-parallel-size 4 --max-model-len 32768 \
    --override-generation-config '{"max_new_tokens": 8192}' \
    --chat-template "$DURABLE/harbor-train/skyrl-train/skyrl_train/utils/templates/qwen3_acc_thinking.jinja2" \
    --port 8000 > "$DURABLE/vllm.log" 2>&1 &
  for _ in $(seq 1 120); do curl -sf localhost:8000/v1/models >/dev/null && return; sleep 5; done
  echo "vLLM did not come up"; tail -30 "$DURABLE/vllm.log"; exit 1
}

case "$PHASE" in
  smoke)
    # Fresh job names each run: Harbor resumes an existing job directory by name (and its saved config) instead of rerunning.
    STAMP=$(date -u +%Y%m%dT%H%M%S)
    harbor run -p tasks/dev --n-tasks 2 -a oracle --env "$AUDITBENCH_SANDBOX" --job-name "smoke-oracle-$STAMP" -n 2 -o "$DURABLE/jobs"
    python scripts/index_trajectories.py "$DURABLE/jobs/smoke-oracle-$STAMP" --name smoke-oracle --split dev
    vllm_up
    # Contract check: with max_tokens omitted, a short prompt must stop at 8,192 tokens (server default) and a 28k prompt must
    # succeed with the completion clipped to the remaining context (2026-10-07: a fixed max_tokens was rejected, not clipped).
    python - <<'PY' | tee "$DURABLE/reports/smoke_context_probe.json"
import json, urllib.request, urllib.error
def ask(n_words, content=None):
    body = {"model": "Qwen3-8B", "messages": [{"role": "user", "content": content or ("word " * n_words + "\nReply OK.")}]}
    req = urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=600))
        return {"ok": True, "prompt_tokens": r["usage"]["prompt_tokens"], "completion_tokens": r["usage"]["completion_tokens"],
                "finish_reason": r["choices"][0]["finish_reason"]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:500]}
res = {"max_model_len": 32768, "server_default_max_tokens": 8192, "request_max_tokens": None,
       "long_output": ask(0, "Count from 1 to 6000, one number per line, no other text."), "prompt_28k": ask(28000)}
print(json.dumps(res, indent=1))
lo, p28 = res["long_output"], res["prompt_28k"]
ok28 = p28.get("ok") and p28.get("prompt_tokens", 0) + p28.get("completion_tokens", 0) <= 32768
cap_ok = lo.get("ok") and lo.get("completion_tokens", 0) <= 8192
if not (ok28 and cap_ok):
    raise SystemExit("context contract check FAILED: 28k prompt ok=%s, long output ok=%s tokens=%s" % (p28.get("ok"), lo.get("ok"), lo.get("completion_tokens")))
if lo.get("finish_reason") != "length":
    print("note: long-output probe stopped before the cap (finish_reason=%s, %s tokens); cap not exercised" % (lo.get("finish_reason"), lo.get("completion_tokens")))
PY
    harbor run -c configs/harbor/smoke_job.yaml --job-name "smoke-qwen-$STAMP" -o "$DURABLE/jobs"
    python scripts/index_trajectories.py "$DURABLE/jobs/smoke-qwen-$STAMP" --name smoke-qwen ;;
  baseline)
    vllm_up
    AUDITBENCH_API_BASE=http://127.0.0.1:8000/v1 harbor run -c configs/harbor/baseline_job.yaml --job-name baseline -o "$DURABLE/jobs"
    python scripts/index_trajectories.py "$DURABLE/jobs/baseline" --name baseline --policy '{"arm":"base","step":0}'
    python scripts/score_job.py trajectories/baseline.jsonl --split dev --step 0 --arm base
    python scripts/score_job.py trajectories/baseline.jsonl --split train --step 0 --arm base ;;
  pilot|defence|control|defence-short|defence-main)
    pkill -f "^[^ ]*python[^ ]* -m vllm.entrypoints" || true   # the trainer owns the GPUs
    CFG=${TRAIN_CONFIG:-configs/training/$PHASE.yaml}
    mkdir -p ~/data/auditbench && ln -sfn "$REPO/tasks/dev" ~/data/auditbench/dev
    python scripts/make_sampling_manifest.py --config "$CFG" --materialise
    RUN_NAME=$(python -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))['run_name'])" "$CFG")
    # Convert fp32 HF exports to bf16 as they appear (31 GB -> 16 GB; the pilot filled the volume); runs on CPU alongside training.
    mkdir -p "$DURABLE/runs/$RUN_NAME/exports"
    nohup python scripts/export_bf16.py "$DURABLE/runs/$RUN_NAME/exports" > "$DURABLE/runs/$RUN_NAME/export_bf16.log" 2>&1 &
    BF16_WATCHER=$!
    bash scripts/launch_training.sh "$CFG" "$DURABLE"
    kill "$BF16_WATCHER" 2>/dev/null || true
    python scripts/export_bf16.py "$DURABLE/runs/$RUN_NAME/exports" --once --min-age 10 >> "$DURABLE/runs/$RUN_NAME/export_bf16.log" 2>&1 || true
    [ "$PHASE" = pilot ] && python scripts/spend_guard.py iteration-budget --ledger "$DURABLE/spend.json" | tee "$DURABLE/reports/iteration_budget.json"
    [ "$PHASE" = defence ] && python scripts/select_checkpoint.py --arm defence || true ;;
  rescore)
    # Re-run the step-0 scoring of an already indexed baseline (trajectories/baseline.jsonl) after a scoring-only failure.
    [ -f trajectories/baseline.jsonl ] || python scripts/index_trajectories.py "$DURABLE/jobs/baseline" --name baseline --policy '{"arm":"base","step":0}'
    python scripts/score_job.py trajectories/baseline.jsonl --split dev --step 0 --arm base
    python scripts/score_job.py trajectories/baseline.jsonl --split train --step 0 --arm base ;;
  eval)
    # Standalone evaluation of a model on dev or the (authorised) test split: EVAL_SPLIT, EVAL_ARM, EVAL_STEP, optional EVAL_MODEL.
    : "${EVAL_SPLIT:?}" "${EVAL_ARM:?}" "${EVAL_STEP:?}"
    pkill -f "^[^ ]*python[^ ]* -m vllm.entrypoints" || true   # the model may differ from the running server
    sleep 5; vllm_up
    if [ "$EVAL_SPLIT" = test ]; then DS="$DURABLE/test_tasks"; [ -d "$DS" ] || { echo "test tasks not synced to $DS"; exit 1; }; else DS="tasks/$EVAL_SPLIT"; fi
    JOB="eval-$EVAL_ARM-$EVAL_SPLIT-step$(printf %04d "$EVAL_STEP")-$(date -u +%Y%m%dT%H%M%S)"
    sed "s|__DATASET__|$DS|" configs/harbor/eval_job.yaml > "$DURABLE/reports/$JOB.job.yaml"
    harbor run -c "$DURABLE/reports/$JOB.job.yaml" --job-name "$JOB" -o "$DURABLE/jobs"
    python scripts/index_trajectories.py "$DURABLE/jobs/$JOB" --name "$JOB" --split "$EVAL_SPLIT" --policy "{\"arm\":\"$EVAL_ARM\",\"step\":$EVAL_STEP}"
    python scripts/score_job.py "trajectories/$JOB.jsonl" --split "$EVAL_SPLIT" --step "$EVAL_STEP" --arm "$EVAL_ARM" ;;
  *) echo "unknown phase $PHASE"; exit 1 ;;
esac
