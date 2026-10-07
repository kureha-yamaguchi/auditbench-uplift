# auditbench-uplift

Does defensive RL on audit-log investigation improve defensive performance, and does it transfer to
offensive capability? This repository implements Stage 1 of [PLAN.md](PLAN.md): the AuditBench-Agent
adaptation of [AuditBench](https://github.com/aanand300/auditlogsbench) (provenance-aware splits,
Harbor tasks, a strict evidence-grounded grader) and the configs and tooling for baseline collection
and online GRPO with harbor-train/SkyRL, tracked in Weights & Biases.

## Status (2026-10-03)

| Gate | State | Evidence |
|---|---|---|
| A: data | **done**; labels signed off 2026-10-06 (blanket accept) | `reports/gate_a_data.md`, `splits/README.md`, `manifests/` |
| B: environment | **done locally**; sandbox checks pending | `reports/gate_b_checks.json` (445/445 tasks: schema ok, no leakage, oracle passes), `reports/compat_differential.json` (4/4 upstream matches), 53 tests |
| C: step 1 baseline | tooling ready, **not run** (needs the GPU pod) | `scripts/run_baseline.sh`, `configs/harbor/baseline_job.yaml` |
| D: pilot | tooling ready, **not run** | `configs/training/pilot.yaml`, `scripts/launch_training.sh` |
| E: step 2 | tooling ready, **not run** | `configs/training/{defence,control}.yaml`, `scripts/select_checkpoint.py` |

Nothing here has touched a model. Test-split tasks are sealed (never built without an explicit override).

## Layout

```
auditbench_harbor/   inventory, provenance graph, split allocation, label manifest, windows, Harbor task builder, CLI
grader/              stdlib-only strict grader (copied into every task's tests/): schema, matching, reward, compat scorer, verifier
training/            balanced sampler, trajectory indexing, §5.2 metrics, §5.3 selection, W&B helpers
configs/             inference contract, Harbor trial/job configs, training run configs, SkyPilot cluster spec
scripts/             pipeline and run tooling (see below)
manifests/           generated: versions, inventory, groups, labels (per split), units, sampling manifests, control screening
splits/              generated: train/dev/test group files, edge list with evidence, allocation record, README
tasks/               generated Harbor tasks (git-ignored); tasks/<split>/<opaque id>/
reports/             generated gate reports and evaluation outputs
tests/               pytest suite (grader negative controls, metamorphic checks, pipeline structure)
```

## Setup

```bash
uv sync --extra dev --python 3.12        # Harbor 0.23.0, W&B, pytest
cp .env.template .env                    # fill keys; never committed
export AUDITBENCH_DIR=../auditlogsbench  # checkout at 369ad441 (data/ is canonical)
```

## Data pipeline (Gate A/B, runs on a laptop)

```bash
auditbench-harbor inventory     # manifests/inventory.json, versions.json
auditbench-harbor provenance    # splits/group_edges.jsonl, manifests/groups.json
auditbench-harbor split         # splits/{train,dev,test}.json, allocation.json (seeded, constrained)
auditbench-harbor labels        # manifests/labels/{train,dev,test}.jsonl + summary (evidence-mapped targets)
auditbench-harbor units         # manifests/units/*.jsonl (400-line edge / 1,000-line raw windows, whole-file classification)
auditbench-harbor build         # tasks/{train,dev}/<id>/ (test needs --allow-test + AUDITBENCH_ALLOW_TEST=1)
auditbench-harbor check         # Harbor schema, leakage, oracle grading -> reports/gate_b_checks.json
python scripts/report_data.py   # splits/README.md, reports/gate_a_data.md
python scripts/compat_differential.py   # grader.compat vs upstream metric code on shipped outputs
python scripts/control_screen.py        # OpenThoughts-TB-dev first-pass screen -> manifests/control_review.jsonl
python scripts/log_manifests_wandb.py   # one versioned W&B artifact with the frozen data manifests
pytest
```

## Task contract

Each task is a Harbor 1.4 task: `environment/` holds a pinned `python:3.12-slim` image with `rg`, `jq`,
Python and a read-only `/app/audit.log`; `network_mode = "no-network"`; the agent runs as an
unprivileged user; the verifier runs in a **separate** container built from `tests/` that receives only
the declared artifact `/app/findings.json`. The agent writes a JSON array of findings (`timestamp` as in
the log, one entity, `source_lines`, `verdict`); see any `instruction.md`. Reward is binary strict
success (all supported targets matched, zero unmatched high-confidence findings, grounded evidence);
diagnostics are separate from `reward.json`. Upstream-convention counts come from `grader/compat.py`.

## Runs (Gates C–E, SkyPilot on RunPod, Modal sandboxes)

Infrastructure (amended 2026-10-05, GPU ladder 2026-10-07): SkyPilot launches a 4-GPU Secure Cloud node in EU-FR-1 with the RunPod
API key and attaches the persistent network volume (`ordered` ladder 4×H200 → H100-SXM → H100-NVL → H100 → A100-80GB because
4×H200 had no stock; the realised GPU and hourly rate are recorded per phase); Modal provides the sandboxes (RunPod pods cannot run nested
containers); every phase runs under `scripts/spend_guard.py` against the $1,500 cap and stops the pod when it ends.

```bash
# one-time: credentials for SkyPilot, adopt the existing volume
printf '[default]\napi_key = "%s"\n' "$RUNPOD_API_KEY" > ~/.runpod/config.toml && sky check runpod
sky volumes apply --name auditbench-uplift-durable --infra runpod/FR/EU-FR-1 --type runpod-network-volume --size 300 --use-existing -y

# provision + setup (idempotent; state lives on /workspace)
sky launch -c auditbench configs/skypilot/runpod-4xh200.yaml --env-file .env -y --retry-until-up

# phases, each self-stopping the pod at the end (sky start auditbench before the next one)
sky exec -c auditbench --env-file .env -- bash scripts/phase.sh smoke
sky exec -c auditbench --env-file .env -- bash scripts/phase.sh baseline
sky exec -c auditbench --env-file .env -- bash scripts/phase.sh pilot      # writes /workspace/auditbench/reports/iteration_budget.json
sky exec -c auditbench --env-file .env -- bash scripts/phase.sh defence
sky exec -c auditbench --env-file .env -- bash scripts/phase.sh control

# results back, selection and export (local)
rsync -az "$(sky status --ip auditbench)":/workspace/auditbench/reports/ reports/runs/
python scripts/select_checkpoint.py --arm defence
python scripts/export_stage2.py --checkpoint defence-selected-S=/workspace/auditbench/runs/defence-seed1/exports/global_step_10
sky down auditbench   # when finished; the volume persists
```

W&B: `WANDB_PROJECT` (default `auditbench-uplift`) receives trainer metrics (`trainer.logger=wandb`),
per-evaluation dev scores and tables from `score_job.py`, and the data-manifest artifact.

## Known integration gaps (verify on the pilot)

- harbor-train 9310ef6 targets an older Harbor; our tasks need Harbor 0.23 (no-network, separate verifier, agent user).
  `patches/harbor-train-9310ef6.patch` (applied by `node_bootstrap.sh`, tested in `tests/test_harbor_train_patch.py`) switches
  to `await Trial.create(...)` and makes agent timeouts reward-0 policy outcomes trained on the saved transcript (per-trajectory
  mask if none); only infrastructure errors mask the whole prompt group.
- harbor-train re-tokenises the chat transcript (no rollout logprobs); exact token reconstruction must be measured in the pilot.
- `max_tokens=8192` per request: if vLLM rejects prompt + 8,192 > 32,768 instead of clipping, usable context is ~24.5k (smoke).
- Terminus-2 caps each tool output at 10,000 bytes (not a token count); the realised token cap must be measured.
- Token ids / logprobs require `collect_rollout_details=true` (set in the configs); the trajectory indexer records their absence as a gap.
- harbor-train's generator masks a whole prompt-group on any infrastructure failure; drop/recollect accounting must be read from its metrics.
- Early stopping is a watchdog, not a trainer hook; the hard iteration cap is enforced by the sampling manifest length with `epochs=1`.
- Sampling settings for Harbor rollouts live in the trial config's `agent.kwargs` (Terminus-2/LiteLLM), not `generator.sampling_params`.
