# PREREG.md (draft; freeze after the pilot, before main training)

Status: **not frozen**. Pilot-dependent fields are marked `TBD(pilot)`. See PLAN.md §9.

## Claims and unit
- Primary contrasts: `M(defence) − M(base)` and `M(defence) − M(control)` per Stage-2 metric; one training seed per arm (exploratory);
  three paired seeds are the recommended extension.
- Experimental unit for AuditBench-Agent: provenance group (`manifests/groups.json`); windows/attempts are not independent.
- Manipulation check: dev `D` improves by ≥ 0.10 with improved positive recall and both eligibility constraints (training/selection.py).

## Frozen artefacts
- AuditBench commit `369ad441f2876245d0db19990c77ccbcb74a0a3a`; annotation hashes in `manifests/versions.json`.
- Model `Qwen/Qwen3-8B` revision `b968826d9c46dd6066d109eabc6255188de91218`; inference contract `configs/inference_contract.yaml`.
- Grouping/split: seed 20261003, strong edges only, 50/10/40 ladder with the dev feasibility constraint (realised 18/7/15 groups).
- Label manifest: `manifests/labels/{train,dev}.jsonl` (human review sign-off: `TBD`), sealed test.
- Grader `auditbench-agent-grader-v1`: strict reward (PLAN.md §5.1); dense contingency only if the pilot sparse-reward rule fires.
- Sampler: hierarchy in `training/sampler.py`; manifests `manifests/sampling/*.jsonl`.

## Recipe (configs/training/*.yaml)
32 prompts × 8 samples, lr 1e-6, no KL, centred advantages, clip 0.2, one update epoch per batch, FSDP2 BF16, 32k context,
≤ 100 iterations, dev evaluation at step 0 and every 5 iterations with 5 attempts, checkpoint every 5.
Caps: `TBD(pilot)` rollouts / GPU-hours / USD (scripts/budget.py gives the sensitivity envelope).

## Selection and stopping
Eligibility `F ≤ F_base + 0.02`, `V ≥ V_base − 0.01`; greatest `D`, ties to the earlier step, step 0 eligible; early stop after
four consecutive evaluations without an eligible ≥ 0.01 improvement; export `defence-selected-S` and `defence-final-T`;
control trained to `T`, keep `control-S` and `control-T`.

## Control pool
`open-thoughts/OpenThoughts-TB-dev@0d54f719`; rubric `manifests/control_rubric.md`; screening `manifests/control_review.jsonl`
(reviewer decisions `TBD`); deduplicate families, reserve control dev, match declared iterations and budgets.

## Pilot decisions to record here
Reward variance rule outcome; 32k vs 64k; realised observation cap; logprob consistency tolerance; resource peaks; failure rates;
amendments with dates.
