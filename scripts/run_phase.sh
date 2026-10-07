#!/usr/bin/env bash
# Run one phase on the auditbench cluster from the laptop (PLAN.md §8.1). Wraps `sky exec` with everything a phase needs:
#   --workdir .      re-syncs the repo (a bare `sky exec` command syncs nothing, so edits never reach the node)
#   --gpus <type>:N  the cluster's GPUs; without it SkyPilot schedules the job as CPU-only and hides the GPUs from it
#   Modal env        MODAL_TOKEN_ID/SECRET and MODAL_ENVIRONMENT from .env, else from ~/.modal.toml's active profile
#   bash scripts/run_phase.sh smoke            # KEEP_POD=1 bash scripts/run_phase.sh baseline  (keep the pod between phases)
set -euo pipefail
PHASE=${1:?phase}
REPO=$(cd "$(dirname "$0")/.." && pwd)
CLUSTER=${CLUSTER:-auditbench}
cd "$REPO"

gpus=$(sky status "$CLUSTER" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -oE "gpus=[A-Za-z0-9-]+:[0-9]+" | head -1 | cut -d= -f2)
[ -n "$gpus" ] || { echo "run_phase: cluster $CLUSTER is not up (sky status)"; exit 1; }

envs=(--env "KEEP_POD=${KEEP_POD:-0}")
for v in TRAIN_CONFIG EVAL_SPLIT EVAL_MODEL EVAL_ARM EVAL_STEP AUDITBENCH_SESSION_CAP_USD; do [ -n "${!v:-}" ] && envs+=(--env "$v=${!v}"); done
toml="$HOME/.modal.toml"
val() { grep -E "^$1=" .env | cut -d= -f2- | sed 's/[[:space:]]*#.*//; s/^"//; s/"$//'; }
if [ -z "$(val MODAL_TOKEN_ID)" ] && [ -f "$toml" ]; then
  # Use the profile marked active (or the only one); SkyPilot forwards these only as process environment.
  prof=$(awk '/^\[/{p=$0} /^active *= *true/{print p}' "$toml" | head -1); [ -n "$prof" ] || prof=$(grep -m1 '^\[' "$toml")
  section=$(awk -v s="$prof" '$0==s{f=1;next} /^\[/{f=0} f' "$toml")
  for k in token_id token_secret environment; do
    v=$(printf '%s\n' "$section" | sed -nE "s/^$k *= *\"?([^\"]*)\"?.*/\1/p" | head -1)
    [ -n "$v" ] && envs+=(--env "MODAL_$(echo "$k" | tr '[:lower:]' '[:upper:]')=$v")
  done
fi
echo "run_phase: $PHASE on $CLUSTER (--gpus $gpus, KEEP_POD=${KEEP_POD:-0})"
# Submit detached and poll the job status: a `sky exec` that streams logs dies with the local API server (2026-10-07) even
# though the job keeps running on the node. The job log is fetched at the end so the phase log stays complete.
api_ok() { sky api status >/dev/null 2>&1; }
ensure_api() { api_ok || { echo "run_phase: local SkyPilot API server down; restarting"; sky api start >/dev/null 2>&1 || true; sleep 5; }; }
ensure_api
out=$(sky exec -c "$CLUSTER" --workdir . --gpus "$gpus" --env-file .env "${envs[@]}" --detach-run -- bash scripts/phase.sh "$PHASE" 2>&1) || { echo "$out" | tail -20; echo "run_phase: submission failed"; exit 1; }
job=$(echo "$out" | sed 's/\x1b\[[0-9;]*m//g' | grep -oE "Job submitted, ID: [0-9]+" | grep -oE "[0-9]+$" | tail -1)
[ -n "$job" ] || { echo "$out" | tail -20; echo "run_phase: could not determine the job id"; exit 1; }
echo "run_phase: job $job submitted $(date -u +%FT%TZ)"
status=""
while :; do
  sleep 60
  ensure_api
  status=$(sky queue "$CLUSTER" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk -v j="$job" '$1==j {print $(NF-1)}' | head -1)
  case "$status" in SUCCEEDED|FAILED|FAILED_SETUP|FAILED_DRIVER|CANCELLED) break;; esac
done
echo "run_phase: job $job finished with status $status $(date -u +%FT%TZ)"
sky logs "$CLUSTER" "$job" --no-follow 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | tail -400
[ "$status" = SUCCEEDED ]
