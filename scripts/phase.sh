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
RATE=${POD_RATE_USD_PER_HOUR:-18.36}
cd "$REPO"
mkdir -p "$DURABLE/reports"
source "$DURABLE/harbor-train/skyrl-train/.venv/bin/activate"
export HF_HOME="$DURABLE/hf" AUDITBENCH_SANDBOX=${AUDITBENCH_SANDBOX:-modal}

guard_phase=$([ "$PHASE" = smoke ] || [ "$PHASE" = baseline ] && echo setup_smoke_baseline || echo "$PHASE")
python scripts/spend_guard.py watch --ledger "$DURABLE/spend.json" --phase "$guard_phase" --rate "$RATE" \
  --stop-file "$DURABLE/STOP" --stop-cmd "pkill -f harbor; pkill -f main_harbor; pkill -f vllm" --stop-pod self \
  > "$DURABLE/spend_guard.$PHASE.log" 2>&1 &
GUARD=$!
finish() {
  kill "$GUARD" 2>/dev/null || true
  rsync -rlptD --no-owner --no-group "$REPO/reports/" "$DURABLE/reports/" 2>/dev/null || true
  if [ "${KEEP_POD:-0}" != 1 ]; then python scripts/runpod_api.py stop "${RUNPOD_POD_ID:-}" || true; fi
}
trap finish EXIT

vllm_up() {
  pgrep -f "vllm.entrypoints.openai.api_server" >/dev/null && return
  nohup python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-8B --revision b968826d9c46dd6066d109eabc6255188de91218 \
    --served-model-name Qwen3-8B --tensor-parallel-size 1 --data-parallel-size 4 --max-model-len 32768 \
    --chat-template "$DURABLE/harbor-train/skyrl-train/skyrl_train/utils/templates/qwen3_acc_thinking.jinja2" \
    --port 8000 > "$DURABLE/vllm.log" 2>&1 &
  for _ in $(seq 1 120); do curl -sf localhost:8000/v1/models >/dev/null && return; sleep 5; done
  echo "vLLM did not come up"; tail -30 "$DURABLE/vllm.log"; exit 1
}

case "$PHASE" in
  smoke)
    harbor run -p tasks/dev --n-tasks 2 -a oracle --env "$AUDITBENCH_SANDBOX" --job-name smoke-oracle -n 2 -o "$DURABLE/jobs"
    python scripts/index_trajectories.py "$DURABLE/jobs/smoke-oracle" --name smoke-oracle --split dev
    vllm_up
    # Does vLLM clip or reject prompt + max_tokens > max-model-len? Decides whether usable context is 32k or ~24.5k.
    python - <<'PY' | tee "$DURABLE/reports/smoke_context_probe.json"
import json, urllib.request, urllib.error
def ask(n_words):
    body = {"model": "Qwen3-8B", "max_tokens": 8192, "messages": [{"role": "user", "content": "word " * n_words + "\nReply OK."}]}
    req = urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=600))
        return {"ok": True, "prompt_tokens": r["usage"]["prompt_tokens"], "completion_tokens": r["usage"]["completion_tokens"],
                "finish_reason": r["choices"][0]["finish_reason"]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:500]}
print(json.dumps({"max_model_len": 32768, "max_tokens": 8192, "prompt_20k": ask(20000), "prompt_28k": ask(28000)}, indent=1))
PY
    AUDITBENCH_API_BASE=http://127.0.0.1:8000/v1 harbor run -c configs/harbor/baseline_job.yaml --job-name smoke-qwen --n-attempts 1 -o "$DURABLE/jobs" \
      --dataset-path tasks/dev --n-tasks 4 2>/dev/null || AUDITBENCH_API_BASE=http://127.0.0.1:8000/v1 harbor run -c configs/harbor/baseline_job.yaml --job-name smoke-qwen --n-attempts 1 -o "$DURABLE/jobs"
    python scripts/index_trajectories.py "$DURABLE/jobs/smoke-qwen" --name smoke-qwen --split dev ;;
  baseline)
    vllm_up
    AUDITBENCH_API_BASE=http://127.0.0.1:8000/v1 harbor run -c configs/harbor/baseline_job.yaml --job-name baseline -o "$DURABLE/jobs"
    python scripts/index_trajectories.py "$DURABLE/jobs/baseline" --name baseline --policy '{"arm":"base","step":0}'
    python scripts/score_job.py trajectories/baseline.jsonl --split dev --step 0 --arm base
    python scripts/score_job.py trajectories/baseline.jsonl --split train --step 0 --arm base ;;
  pilot|defence|control)
    pkill -f "vllm.entrypoints.openai.api_server" || true   # the trainer owns the GPUs
    python scripts/make_sampling_manifest.py --config "configs/training/$PHASE.yaml" --materialise
    bash scripts/launch_training.sh "configs/training/$PHASE.yaml" "$DURABLE"
    [ "$PHASE" = pilot ] && python scripts/spend_guard.py iteration-budget --ledger "$DURABLE/spend.json" | tee "$DURABLE/reports/iteration_budget.json"
    [ "$PHASE" = defence ] && python scripts/select_checkpoint.py --arm defence || true ;;
  *) echo "unknown phase $PHASE"; exit 1 ;;
esac
