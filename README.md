# auditbench-uplift

Does defensive RL on audit-log investigation improve defensive performance, and does it transfer to
offensive capability? This repository implements Stage 1 of [PLAN.md](PLAN.md): the AuditBench-Agent
adaptation of [AuditBench](https://github.com/aanand300/auditlogsbench) (provenance-aware splits,
Harbor tasks, a strict evidence-grounded grader) and the configs and tooling for baseline collection
and online GRPO with harbor-train/SkyRL, tracked in Weights & Biases.

## Status (2026-10-03)

| Gate | State | Evidence |
|---|---|---|
| A: data | **done, pending human label review** | `reports/gate_a_data.md`, `splits/README.md`, `manifests/` |
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
configs/             inference contract, Harbor trial/job configs, training run configs
scripts/             pipeline, pod (SSH) and run tooling (see below)
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

## Runs (Gates C–E, need a GPU pod)

Infrastructure route (amended 2026-10-04): the RunPod account is connected through the RunPod MCP
plugin (browser sign-in, no API key stored); the pod is driven over SSH; sandboxes are Harbor Docker
environments on the node (`AUDITBENCH_SANDBOX=docker`, Modal optional); a $1,500 total cap is
metered by `scripts/spend_guard.py`.

```bash
# pod: create a 4xH200 Secure Cloud pod with your SSH public key via the RunPod plugin, mount a network
# volume at /workspace, then record its SSH endpoint in .env (POD_SSH_HOST/PORT/KEY)
scripts/pod.sh bootstrap                 # rsync repo, install Docker/uv/harbor-train@pinned, cache Qwen3-8B, record environment
scripts/pod.sh env "cd ~/auditbench-uplift && python scripts/spend_guard.py watch --ledger /workspace/auditbench/spend.json --phase setup_smoke_baseline --rate <pod $/h> --stop-file /workspace/auditbench/STOP --stop-cmd 'pkill -f harbor' &"

# step 1: smoke, then baseline (five attempts per train and dev task) against vLLM on the pod
scripts/pod.sh env "cd ~/auditbench-uplift && bash scripts/smoke_test.sh docker"
scripts/pod.sh env "cd ~/auditbench-uplift && AUDITBENCH_API_BASE=http://127.0.0.1:8000/v1 bash scripts/run_baseline.sh baseline"
scripts/pod.sh pull '~/auditbench-uplift/jobs/baseline' jobs/
python scripts/index_trajectories.py jobs/baseline --name baseline-dev --split dev
python scripts/score_job.py trajectories/baseline-dev.jsonl --split dev --step 0 --arm base   # logs to W&B

# step 2: sampling manifest, pilot, then defence and control with the budget-derived iteration count
scripts/pod.sh env "cd ~/auditbench-uplift && python scripts/make_sampling_manifest.py --config configs/training/pilot.yaml --materialise"
scripts/pod.sh env "cd ~/auditbench-uplift && source /workspace/auditbench/harbor-train/skyrl-train/.venv/bin/activate && bash scripts/launch_training.sh configs/training/pilot.yaml /workspace/auditbench"
scripts/pod.sh env "cd ~/auditbench-uplift && python scripts/spend_guard.py iteration-budget --ledger /workspace/auditbench/spend.json"   # -> T_max
python scripts/select_checkpoint.py --arm defence     # eligibility, D, tie rules, manipulation check
python scripts/watchdog.py --arm defence --stop-file /workspace/auditbench/STOP --stop-cmd "scripts/pod.sh ssh pkill -f main_harbor"
python scripts/export_stage2.py --checkpoint defence-selected-S=/workspace/auditbench/runs/defence-seed1/exports/global_step_10
```

W&B: `WANDB_PROJECT` (default `auditbench-uplift`) receives trainer metrics (`trainer.logger=wandb`),
per-evaluation dev scores and tables from `score_job.py`, and the data-manifest artifact.

## Known integration gaps (verify on the pilot)

- Terminus-2 caps each tool output at 10,000 bytes (not a token count); the realised token cap must be measured.
- Token ids / logprobs require `collect_rollout_details=true` (set in the configs); the trajectory indexer records their absence as a gap.
- harbor-train's generator masks a whole prompt-group on any infrastructure failure; drop/recollect accounting must be read from its metrics.
- Early stopping is a watchdog, not a trainer hook; the hard iteration cap is enforced by the sampling manifest length with `epochs=1`.
- `generator.sampling_params.*` override names must be confirmed against the pinned harbor-train commit before the pilot.
