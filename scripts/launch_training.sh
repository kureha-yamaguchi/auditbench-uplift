#!/usr/bin/env bash
# Launch one training arm with harbor-train/SkyRL from a configs/training/*.yaml file.
#   bash scripts/launch_training.sh configs/training/pilot.yaml /workspace/auditbench
# Requires: harbor-train checkout at $HARBOR_TRAIN_DIR (default /workspace/auditbench/harbor-train), its venv active, Ray started,
# sampling manifest materialised (scripts/make_sampling_manifest.py), dev tasks at data.dev_dir.
set -euo pipefail
CFG=${1:?config yaml}; DURABLE=${2:?durable root}
y() { python -c "import sys,yaml; c=yaml.safe_load(open('$CFG')); print(eval('c'+sys.argv[1]))" "$1"; }
RUN_NAME=$(y "['run_name']"); ITERS=$(y "['iterations']"); PROMPTS=$(y "['prompts_per_iteration']"); SAMPLES=$(y "['samples_per_prompt']")
TRAIN_DIR=$(eval echo "$(y "['data']['train_dir']")"); DEV_DIR=$(eval echo "$(y "['data']['dev_dir']")")
LR=$(y "['optimizer']['lr']"); MAXLEN=$(y "['model']['max_model_len']"); EVAL_INT=$(y "['eval_interval']"); CKPT_INT=$(y "['ckpt_interval']")
REWARD_MODE=$(y "['reward_mode']"); SEED=$(y "['seed']"); EVAL_BEFORE=$(y ".get('eval_before_train', True)" | tr A-Z a-z)
WD=$(y "['optimizer']['weight_decay']"); BETAS=$(y "['optimizer']['betas']"); GRAD_CLIP=$(y "['optimizer']['grad_clip']")
SCHED=$(y "['optimizer']['scheduler']"); CLIP_LO=$(y "['algorithm']['eps_clip_low']"); CLIP_HI=$(y "['algorithm']['eps_clip_high']")
MODEL_REV=$(y "['model']['revision']")
# skyrl_train has no model-revision option: pass the pinned local snapshot so HF `main` is never loaded.
MODEL_PATH=$(python -c "from huggingface_hub import snapshot_download as s; print(s('$(y "['model']['path']")', revision='$MODEL_REV', local_files_only=True))")
# HarborTaskDataset silently drops entries without instruction.md, so count only loadable tasks.
N_ENTRIES=$(find -L "$TRAIN_DIR" -mindepth 2 -maxdepth 2 -name instruction.md | wc -l | tr -d ' ')
[ "$N_ENTRIES" -eq $((ITERS * PROMPTS)) ] || { echo "train dir has $N_ENTRIES entries, expected $((ITERS*PROMPTS))"; exit 1; }
RUN_ROOT="$DURABLE/runs/$RUN_NAME"; [ -e "$RUN_ROOT/ckpts" ] && { echo "refusing to reuse $RUN_ROOT (no accidental resume)"; exit 1; }
mkdir -p "$RUN_ROOT"; cp "$CFG" "$RUN_ROOT/run_config.yaml"
# AUDITBENCH_REWARD reaches the separate verifier sandbox via verifier.env in the trial config.
export AUDITBENCH_REWARD="$REWARD_MODE" RUN_NAME AUDITBENCH_DURABLE="$DURABLE"
cd "${HARBOR_TRAIN_DIR:-/workspace/auditbench/harbor-train}/skyrl-train"
python -m examples.harbor.entrypoints.main_harbor \
  data.train_data="['$TRAIN_DIR']" data.val_data="['$DEV_DIR']" \
  trainer.policy.model.path="$MODEL_PATH" generator.served_model_name=Qwen3-8B \
  hydra.searchpath="['file://examples/harbor','file://$HOME/auditbench-uplift/configs/harbor']" \
  +harbor_trial_config=auditbench_trial_config \
  trainer.export_path="$RUN_ROOT/exports" trainer.ckpt_path="$RUN_ROOT/ckpts" trainer.log_path="$RUN_ROOT/logs" \
  trainer.algorithm.advantage_estimator=grpo trainer.algorithm.loss_reduction=seq_mean_token_sum_norm \
  trainer.algorithm.grpo_norm_by_std=false trainer.algorithm.use_kl_loss=false \
  trainer.placement.colocate_all=true trainer.strategy=fsdp2 \
  trainer.placement.policy_num_gpus_per_node=4 trainer.placement.ref_num_gpus_per_node=4 \
  generator.num_inference_engines=4 generator.inference_engine_tensor_parallel_size=1 \
  +generator.engine_init_kwargs.chat_template=skyrl_train/utils/templates/qwen3_acc_thinking.jinja2 \
  +generator.engine_init_kwargs.max_model_len=$MAXLEN \
  +generator.engine_init_kwargs.override_generation_config.max_new_tokens=8192 generator.sampling_params.max_generate_length=8192 \
  trainer.epochs=1 trainer.train_batch_size=$PROMPTS trainer.policy_mini_batch_size=$PROMPTS \
  trainer.update_epochs_per_batch=1 trainer.micro_forward_batch_size_per_gpu=1 trainer.micro_train_batch_size_per_gpu=1 \
  trainer.eval_before_train=$EVAL_BEFORE trainer.eval_interval=$EVAL_INT trainer.eval_batch_size=128 \
  trainer.ckpt_interval=$CKPT_INT trainer.hf_save_interval=$CKPT_INT trainer.algorithm.max_seq_len=$MAXLEN \
  trainer.policy.optimizer_config.lr=$LR trainer.policy.optimizer_config.weight_decay=$WD \
  trainer.policy.optimizer_config.adam_betas="$BETAS" trainer.policy.optimizer_config.max_grad_norm=$GRAD_CLIP \
  trainer.policy.optimizer_config.scheduler=$SCHED trainer.policy.optimizer_config.num_warmup_steps=0 \
  trainer.algorithm.eps_clip_low=$CLIP_LO trainer.algorithm.eps_clip_high=$CLIP_HI trainer.seed=$SEED \
  generator.n_samples_per_prompt=$SAMPLES generator.eval_n_samples_per_prompt=5 \
  generator.apply_overlong_filtering=true generator.gpu_memory_utilization=0.8 \
  trainer.logger=wandb trainer.project_name="${WANDB_PROJECT:-auditbench-uplift}" trainer.run_name="$RUN_NAME" \
  trainer.resume_mode=none \
  generator.backend=vllm generator.run_engines_locally=true generator.weight_sync_backend=nccl generator.async_engine=true \
  generator.batched=false generator.enforce_eager=false generator.enable_http_endpoint=true \
  generator.http_endpoint_host=127.0.0.1 generator.http_endpoint_port=8000 \
  +generator.rate_limit.enabled=true +generator.rate_limit.trajectories_per_second=5 +generator.rate_limit.max_concurrency=32 \
  2>&1 | tee -a "$RUN_ROOT/train.log"
