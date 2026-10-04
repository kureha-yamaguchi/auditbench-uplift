#!/usr/bin/env bash
# Step-1 baseline collection (PLAN.md §6.2): five attempts per canonical train and dev task against a
# vLLM endpoint serving Qwen/Qwen3-8B@b968826d with the frozen inference contract.
#   AUDITBENCH_API_BASE=http://<vllm-host>:8000/v1 bash scripts/run_baseline.sh [job-name]
# Afterwards: scripts/index_trajectories.py jobs/<job> --name baseline --split dev && scripts/score_job.py ...
set -euo pipefail
: "${AUDITBENCH_API_BASE:?set to the vLLM OpenAI-compatible base URL}"
JOB=${1:-baseline-$(date +%Y%m%d-%H%M%S)}
[ -d tasks/train ] && [ -d tasks/dev ] || { echo "build tasks first: auditbench-harbor build"; exit 1; }
harbor run -c configs/harbor/baseline_job.yaml --job-name "$JOB" --env-file .env
echo "job dir: jobs/$JOB"
