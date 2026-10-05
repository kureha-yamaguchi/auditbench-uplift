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
