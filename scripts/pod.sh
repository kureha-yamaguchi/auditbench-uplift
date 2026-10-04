#!/usr/bin/env bash
# SSH glue for the RunPod pod (replaces SkyPilot). Reads POD_SSH_HOST/PORT/KEY and secrets from .env.
#   scripts/pod.sh ssh [cmd...]      interactive shell or one command on the pod
#   scripts/pod.sh env cmd...        run cmd with WANDB_*/HF_TOKEN/MODAL_* exported in the remote session
#   scripts/pod.sh push              rsync this repo (minus .venv, tasks/test, .env) to /workspace/auditbench/auditbench-uplift (~/auditbench-uplift symlinks there)
#   scripts/pod.sh pull <remote> <local>   rsync results back (jobs, trajectories, reports)
#   scripts/pod.sh bootstrap         push, then run scripts/pod_bootstrap.sh remotely
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
: "${POD_SSH_HOST:?set POD_SSH_HOST in .env}"; : "${POD_SSH_PORT:=22}"; : "${POD_SSH_KEY:=~/.ssh/auditbench_runpod}"; : "${POD_SSH_USER:=root}"
SSH=(ssh -i "${POD_SSH_KEY/#\~/$HOME}" -p "$POD_SSH_PORT" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 "$POD_SSH_USER@$POD_SSH_HOST")
RSYNC_SSH="ssh -i ${POD_SSH_KEY/#\~/$HOME} -p $POD_SSH_PORT -o StrictHostKeyChecking=accept-new"
case "${1:-}" in
  ssh)   shift; "${SSH[@]}" "$@" ;;
  env)   shift
         # secrets travel on stdin to a remote `bash -s`, never on the remote command line (ps/pgrep-safe)
         vars=(WANDB_API_KEY WANDB_ENTITY WANDB_PROJECT HF_TOKEN MODAL_TOKEN_ID MODAL_TOKEN_SECRET AUDITBENCH_SANDBOX)
         exports=""; for v in "${vars[@]}"; do [ -n "${!v:-}" ] && exports+="export $v=$(printf %q "${!v}")"$'\n'; done
         printf '%s%s\n' "$exports" "$*" | "${SSH[@]}" bash -s ;;
  push)  "${SSH[@]}" "mkdir -p /workspace/auditbench/auditbench-uplift"; rsync -rlptDz --no-owner --no-group --delete -e "$RSYNC_SSH" --exclude .venv --exclude .env --exclude 'tasks/test' --exclude jobs --exclude wandb \
           --exclude __pycache__ --exclude .pytest_cache ./ "$POD_SSH_USER@$POD_SSH_HOST:/workspace/auditbench/auditbench-uplift/" ;;
  pull)  rsync -rlptDz --no-owner --no-group -e "$RSYNC_SSH" "$POD_SSH_USER@$POD_SSH_HOST:$2" "$3" ;;
  bootstrap) "$0" push; "$0" env "bash ~/auditbench-uplift/scripts/pod_bootstrap.sh" ;;
  *) sed -n 2,8p "$0"; exit 1 ;;
esac
