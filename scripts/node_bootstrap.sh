#!/usr/bin/env bash
# Node setup, run by SkyPilot's `setup` block on every launch. Idempotent and fast when the network
# volume already holds the venv and model cache.
#   - copies the synced workdir (~/sky_workdir) to /workspace/auditbench/auditbench-uplift
#   - uv, harbor-train at the pinned commit with its venv, this repo installed into it
#   - Qwen3-8B cached under /workspace/auditbench/hf; environment record for the version manifest
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
HARBOR_TRAIN_REF=9310ef653ae6af33d1ec11d477fdc9689461ec41
DURABLE=/workspace/auditbench            # RunPod network volume mount; everything lives here so a stopped pod loses nothing
HT="$DURABLE/harbor-train"
export HF_HOME="$DURABLE/hf" UV_CACHE_DIR="$DURABLE/uv-cache"
mkdir -p "$DURABLE"/{runs,jobs,trajectories,manifests,data,hf,uv-cache,auditbench-uplift}
SRC="${SKY_WORKDIR:-$HOME/sky_workdir}"
[ -d "$SRC" ] && rsync -rlptD --no-owner --no-group --delete --exclude .venv --exclude .env --exclude 'tasks/test' --exclude jobs "$SRC/" "$DURABLE/auditbench-uplift/"
ln -sfn "$DURABLE/auditbench-uplift" ~/auditbench-uplift
[ -n "${WANDB_API_KEY:-}" ] || { echo "WANDB_API_KEY missing in session"; exit 1; }

command -v rsync >/dev/null && command -v tmux >/dev/null || { apt-get update -qq && apt-get install -y -qq git rsync tmux jq ripgrep >/dev/null; }
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

if [ ! -d "$HT" ]; then git clone https://github.com/fleet-ai/harbor-train.git "$HT"; fi
# Pinned commit plus our local patch only (Harbor 0.23 trial API, PLAN.md §6.4 timeout policy); -f drops stale edits.
git -C "$HT" fetch -q && git -C "$HT" checkout -q -f "$HARBOR_TRAIN_REF"
git -C "$HT" apply "$DURABLE/auditbench-uplift/patches/harbor-train-9310ef6.patch"
cd "$HT/skyrl-train"
[ -d .venv ] || uv venv --python 3.12 --seed
source .venv/bin/activate
uv sync --extra vllm --extra harbor
uv pip install -e "$DURABLE/auditbench-uplift"
python -c "import wandb,os; wandb.login(key=os.environ['WANDB_API_KEY'])"
python - <<'PY'
from huggingface_hub import snapshot_download
import os
snapshot_download("Qwen/Qwen3-8B", revision="b968826d9c46dd6066d109eabc6255188de91218", token=os.environ.get("HF_TOKEN"))
print("model cached")
PY
cd "$DURABLE/auditbench-uplift"
python scripts/record_environment.py --out "$DURABLE/manifests/environment-$(date +%Y%m%dT%H%M%S).json"
echo "bootstrap complete; durable root $DURABLE"
