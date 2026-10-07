# Stage-1 status

Generated artefacts and checks run on 2026-10-03 (laptop, no sandbox provider, no model):

- `manifests/versions.json` — pinned commits, annotation hashes, package versions, model and control-pool revisions.
- `manifests/inventory.json` — 129 files; counts match PLAN.md §2 exactly; zero timestamp parse failures.
- `splits/` — 40 provenance groups, 183 edges with evidence, feasible 50/10/40-ladder allocation (18/7/15 groups), sealed test.
- `manifests/labels/` — 44 target units; all train/dev units `supported_positive`; 5 ambiguous OpTC hosts in test; 1 unplaced.
- `manifests/units/` — train 367 / dev 78 / test 325 canonical units (windows + whole-file classification); no quarantined train/dev units.
- `tasks/{train,dev}` — 445 Harbor tasks built; `reports/gate_b_checks.json`: 0 schema problems, 0 leakage problems, oracle 445/445.
- `reports/compat_differential.json` — compat scorer equals upstream counts on all 4 shipped v2 outputs.
- `manifests/sampling/` — pilot (320 draws) and defence-seed1 (3,200 draws) manifests with exposure reports; no group never drawn.
- `manifests/control_review.jsonl` — 70 control-pool tasks screened: 48 candidate, 14 review, 8 exclude (reviewer decisions pending).
- `tests/` — 53 passing tests.

Not run (requires the GPU pod): Docker isolation smoke, Qwen smoke, baselines, pilot, training, control baseline.

Infrastructure amendment 2026-10-05: SkyPilot + RunPod API key (`configs/skypilot/runpod-4xh200.yaml`, `scripts/phase.sh`), Modal sandboxes required, network volume adopted into SkyPilot, $1,500 total cap with per-phase pod self-stop. Spend so far: ~$175 of pod time on 2026-10-04 (bootstrap + idle), state preserved on the volume.

Local Modal checks 2026-10-06 (no model, artefacts in git-ignored `runs_local/jobs/`): oracle 8/8 on dev after normalising task file
modes (restrictive host umask broke the unprivileged agent) and making `/app` root-owned sticky; isolation probe
(`auditbench_harbor/probe_agent.py`) on 7 dev tasks: agent uid 1000, DNS/TCP/HTTPS blocked, no private files/label strings/secrets
visible, log immutable, reward spoof via `/logs/verifier` ineffective (separate verifier; reward 1 only on the two negative-window
tasks where `[]` is correct). Modal does not enforce the memory limit (3 GiB allocation succeeded; accepted by the user).

GPU smoke 2026-10-07 (RunPod CA-MTL-1, 4xH100-SXM $13.96/h after 4xH200 had no stock anywhere; pod rdmpf57wowh6n5, volume
`auditbench-uplift-ca-mtl-1`): oracle 2/2 on Modal from the node; the 4-task Qwen smoke fell back to the full `baseline_job.yaml` at
1 attempt, so all 445 train+dev tasks ran once (49 min, ~$12 pod): 401 graded, mean strict reward 0.571; 44 (10%) context exits;
141 (32%) invalid output, of which 105 never wrote /app/findings.json (80 ended early with task_complete after concluding
"benign", 25 hit 32 turns); positives detected 1/27 (train lm); classification 1/15 valid. p50 trial 84 s, p95 248 s; p50 4.1k
output tokens. vLLM rejects prompt+max_tokens>32768 (no clipping) => usable context ~24.5k with max_tokens=8192; decision
pending. Artefacts: `trajectories/smoke-qwen.jsonl` (node + local, git-ignored), `reports/runs/smoke/`. Fixes along the way:
Modal env/tokens, `run_phase.sh` (sky exec needs --workdir and --gpus), stale Harbor job dirs, Cloudflare UA, baseline_job literals.

Baseline 2026-10-07 (pod i1yzo7h5ladqey, 4xH100-SXM, CA-MTL-1): 2,225 trials (445 tasks x 5 attempts) in 2 h at concurrency 32;
step-0 scores: dev D = 0.367, false-alert rate 0.032, validity 0.744 (`reports/evaluations/base-{dev,train}-step0000.json`).
W&B: the API key has no writable entity ("entity not found" / "permission denied"), so all phases run with WANDB_MODE=offline
(recorded deviation; local run files on the node).

Pilot 2026-10-07 16:13-18:54 UTC (pod dh7q2j8xb1shpz, 4xH100-SXM): the harbor-train/SkyRL path works end to end on 80 GB GPUs —
5 GRPO iterations (32 prompts x 8), ~19-21 min each (rollouts ~14-16 min, logprob forward ~65 s, policy update ~4-5 min), 0 masked
prompt groups, 0 timeouts, 1 transient Modal ServiceError retried successfully. Batch mean strict reward 0.44, 0.37, 0.32, 0.33, 0.22;
mean response length 9.1k -> 11.2k tokens. Trainer-integrated dev evaluation (5 attempts, SkyRL's own per-task avg_score):
mean 0.615 -> 0.672 at step 5, pass@5 0.808 -> 0.821. The run's final save failed with the 280 GB volume full (two 92 GB resume
checkpoints + two 31 GB fp32 HF exports); the step-5 export was verified complete, then the pilot checkpoints/exports were deleted
to make room for the defence run (deviation from the §8.3 retention rule, forced by capacity). Pilot config: 5 of the permitted
<=10 iterations (unattended-session time limit). Defence-short: 10 iterations, no mid-run resume checkpoints, exports at 5/10,
selection from standalone dev evaluations of each export.
