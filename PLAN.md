# Defensive training on AuditBench — research plan for steps 1 and 2

**Research question.** Does additional training on defensive audit-log investigation improve
defensive performance, and does that training transfer to offensive capabilities?

**Scope.** Step 1 collects starting-model actions and rewards on AuditBench train tasks, plus a
separate dev baseline. Step 2 trains the same starting checkpoint with online GRPO on fresh
AuditBench train rollouts. Fresh rollouts were explicitly confirmed as intended during review.
Stage 1 also produces a generic terminal-training control and the artifacts needed for later
before/after evaluations on CyberGym, ExploitBench, AuditBench test, and ExCyTIn-Bench.
Implementing or running those Stage-2 evaluations is outside this document's scope.

**Status: reviewed research design, 2026-10-03; Stage-1 tooling implemented 2026-10-03/04.**

**Amendment 2026-10-04/05 (infrastructure).** Provisioning uses SkyPilot with the RunPod API key
(`sky launch` on `configs/skypilot/runpod-4xh200.yaml`), as originally planned; an interim SSH-driven route
was retired on 2026-10-05. The node attaches the RunPod network volume `auditbench-uplift-durable`
(adopted into SkyPilot with `sky volumes apply --use-existing`), which holds harbor-train, the venv, the
model cache and run state. RunPod pods cannot run nested containers, so sandboxes must be Modal
(`AUDITBENCH_SANDBOX=modal`); the RunPod MCP plugin remains for billing and inspection. Every phase
(`scripts/phase.sh`) runs under the spend guard and stops the pod when it ends. A user-set hard cap of
**$1,500 total** replaces the open-ended budget; `scripts/spend_guard.py` meters it and derives the
main-run iteration count from pilot timing. Affected text below is marked *(amended)*.
**Amendment 2026-10-07 (GPU ladder).** 4×H200 Secure Cloud had no stock in any region for several hours on
2026-10-06/07. The SkyPilot spec now carries an `ordered` ladder of 4-GPU, ≥80 GB alternatives in EU-FR-1
(H100-SXM, H100-NVL, H100, A100-80GB) tried after H200 on every retry; the realised GPU type and hourly rate are
recorded per phase and used by the spend guard. The inference contract and recipe are unchanged; on 80 GB GPUs
the pilot's memory gate (§7.2) decides whether 32k context is feasible, and a shorter declared context would
require rerunning baselines. Whichever type runs the baseline should run all arms; a mid-study change is a
recorded deviation.
This review inspected the local `../auditlogsbench` checkout at commit
`369ad441f2876245d0db19990c77ccbcb74a0a3a` and primary documentation linked below. No model runs,
cloud jobs, grader parity tests, or training pilots have been performed. Proposed settings must
pass the gates below before they become frozen experimental settings.

## 1. Design decisions and changes from the draft

This is feasible as an exploratory study, subject to label quality, useful reward variation,
and integration checks. The main validity threats are few independent scenarios, leakage across
representations/tasks, learning the grader instead of investigation, and confounding defensive
content with generic terminal training.

| Item | Revised decision |
|---|---|
| Starting checkpoint | `Qwen/Qwen3-8B`, exact revision pinned. This is already post-trained; “base” means the starting checkpoint, not `Qwen3-8B-Base`. |
| Learning method | Online GRPO, Harbor Terminus-2 and harbor-train/SkyRL, full BF16 fine-tuning with FSDP2. Step-1 traces are baseline/diagnostic data, not a replay buffer for ordinary GRPO. |
| Arms and seeds | Base, defence training, and non-security terminal-training control. One seed per trained arm is exploratory; three paired seeds are the recommended extension. |
| Split | Connected groups of related scenarios; initial target 50% train / 10% dev / 40% test. Sparse-cell feasibility takes priority over exact percentages (§3.2). |
| Distribution | Preserve canonical train/dev/test datasets. Apply an explicit balanced sampler during training; dev/test retain the benchmark's empirical prevalence. |
| Augmentation | Off initially. If pilot evidence warrants it, bounded train-only shifted windows with recomputed labels and fixed parent-group weights. |
| Task unit | Investigation: 400-line edge / 1,000-line raw canonical chunks. Classification: whole files. File access through an isolated terminal, not automatic prompt insertion. |
| Reward | Strict valid output, supported target coverage, and zero unmatched high-confidence findings for binary success. Original benchmark scoring is a separate compatibility metric (§5). |
| Context | Pilot 32k with bounded tool output first; test 64k/YaRN only if needed. Freeze one contract across baseline, training, and model comparisons. |
| Selection | Balanced dev detection/clean-negative score with false-alert and validity constraints; step 0 is eligible. Preserve the actual trained endpoint as well. |
| Control matching | Same declared training iterations and agent budgets; measure actual updates, tokens, rollouts, and time. Equal task counts or steps do not imply equal compute. |
| Infrastructure | *(amended)* RunPod 4×H200 via SkyPilot with the API key; Modal sandboxes (nested containers are impossible on RunPod pods); W&B; RunPod network volume plus independent backup. Quotas, memory feasibility, and compatibility must be measured. |

Whole-file classification and terminal-mediated log access change the original protocol. Call
this adaptation **AuditBench-Agent** and distinguish its scores from paper-reproduction scores.

### 1.1 Claims the design supports

For each later benchmark metric `M`, retain both contrasts:

- `M(defence) − M(base)`: total change after the selected defensive-training treatment.
- `M(defence) − M(control)`: change relative to the selected generic terminal-training treatment.

The latter controls some generic training effects; differences in difficulty, reward density,
and token use still limit causal attribution to defensive content. One paired run does not
estimate training-seed variation. A nonsignificant offence difference is not evidence of no
uplift without adequate precision and a predeclared equivalence margin.

Stage 1's manipulation check asks whether held-out defensive performance improved without more
false alerts. Training reward alone cannot answer this. Preserve checkpoints and proceed with
later outcome reporting even if training fails; describe the manipulation as unsuccessful rather
than interpreting it as a test of successful defensive improvement.

## 2. Verified inventory and version record

Counts from the local checkout during this review:

| Source | Investigation files | Nominal investigation chunks | Classification files |
|---|---:|---:|---:|
| Lab edge | 30 | 129 | 10 |
| Lab raw | 25 | 126 | 8 |
| OpTC edge | 41 | 482 | 15 |
| Total | 96 | 737 | 33 |

Nominal chunks use `ceil(lines / 400)` for edge and `ceil(lines / 1000)` for raw, including
partial final chunks. These are inventory counts, not validated training-task counts. Positive
counts cannot be inferred from these totals. There are 129 files, 51 dataset-qualified scenario
names, and 20 groups of byte-identical files. A preliminary grouping by names, exact hashes,
Lab filename-window overlap, and OpTC host/window overlap reduces the names to 49 components.
This is an upper bound before provenance/campaign review, not 49 independent attacks.
All 129 files match their copies under `inference/`.

The six shipped Lab edge Gemini outputs are useful regression fixtures but do not cover every
dataset, representation, task, or parser edge case. The source layout and original protocol are
documented in the [AuditBench repository](https://github.com/aanand300/auditlogsbench) and
[paper](https://arxiv.org/abs/2606.10281).

Create a machine-readable version manifest before generating tasks:

- Dataset SHA, dirty-state/diff hash, source-log and annotation hashes, provenance, applicable
  licenses. Use `data/` as canonical; do not double-count `inference/` copies.
- Model revision and weight hashes; tokenizer, special tokens, chat template, thinking behavior,
  RoPE configuration, dtype, and every generation parameter.
- Harbor, harbor-train/SkyRL, Transformers, vLLM, PyTorch, FlashAttention, CUDA/driver, Docker
  (and Modal if used) versions; dependency lockfile, image digests, and local patches.
- Grouping, split, label, grader, sampler, and config versions/hashes.
- Separate seeds for splits, sampling, evaluation attempts, training, and control selection;
  nondeterministic kernels and distributed execution settings.

Current upstream documentation is not a tested compatibility matrix. Pin installed revisions
and save fully resolved configs rather than launching from moving `main` branches or inheriting
unspecified recipe defaults.

## 3. Phase A — provenance, splits, and task construction

### 3.1 Build a provenance graph before splitting or augmenting

Files are nodes; shared provenance creates edges; transitive connected components are split
groups. Save the reason for every edge.

1. Link raw/edge views, copies across task folders, matching dataset-qualified scenario names,
   and exact duplicate contents. The same `scenario1` label across Lab and OpTC is not sufficient.
2. Parse both minute and second filename timestamps. Flag overlaps using dataset, collection
   session, and host identity where known. Matching time alone on unrelated hosts is insufficient.
3. Link classification and investigation views of the same event even with different names.
   Local examples: Lab `attack-windows-lmscenario1` / `lm-scenario1`, and OpTC
   `h501_attack-scenario3` / `h501_lm-scenario5`.
4. Inspect extraction scripts/provenance for events on different hosts or non-overlapping windows
   belonging to one attack run or campaign. Filename overlap alone misses these relationships.
5. Check normalized event IDs and substantial shared line sequences for near duplicates. Review
   uncertain links; common boilerplate alone should not merge the corpus. Record ambiguity.

All future views/windows inherit their parent group's split. Host-held-out and attack-template-
held-out generalization are stronger, different questions: report host/template overlap without
claiming that a scenario split establishes either.

### 3.2 Allocate and lock splits

Express the draft's intended allocation unambiguously as **50% train / 10% dev / 40% test** of
groups. Use deterministic constrained allocation with a fixed seed. Groups may carry multiple
tasks; use multilabel group stratification, not independent per-file splitting.

Balance coarse margins: dataset, task, attack/benign, OS where feasible. Raw/edge remain together.
Do not demand every dataset × task × representation × label cell in every split: OpTC has only
two exfiltration annotation records, for example. Publish absent cells and actual counts.

Before inspecting model outcomes, require both labels in dev for each pooled selection task;
aim for at least two independent positive and two benign groups per task. If the small dev
allocation cannot support this, choose a feasible larger dev split (for example 50/20/30) or
explicitly narrow the supported selection strata. Never split a provenance component to satisfy
a quota. If pooled coverage is infeasible, scope the study as a narrower feasibility experiment.

Write `splits/{train,dev,test}.json`, `group_edges.jsonl`, and a counts/limitations README, with
file hashes, parent groups, allocation deviations, and manifest SHA-256s. Seal test after structural
work. Stage 1 may perform metadata/integrity checks, but no test model runs, test oracle scoring,
or test-driven prompt/reward tuning. Keep test labels/tasks off training workers. Later labelled
test debugging requires a recorded deviation; a compromised test set is not untouched evidence.

### 3.3 Canonical investigation tasks and label quality

Preserve consecutive 400-line edge / 1,000-line raw windows, stable source-line references, and
partial final windows. A task supplies a searchable file; it does not place all log text in context.
Construct a private target-unit manifest per scenario before deriving labels:

- Preserve annotation structure. Several timestamps can describe one target; hostnames/IPs and
  basenames/full paths can be aliases. Cartesian products of aliases are not independent events.
  Record dataset-specific counting, including upstream OpTC LM's unique-host convention.
- Parse timestamps across available records, recording timezone, precision, parse failures,
  min/max, and non-monotonic ordering. First/last-line helpers do not prove interval coverage.
  Epoch conversion must use documented explicit timezones, independent of host `TZ`; some local
  helpers/parser methods currently depend on the machine timezone.
- Preserve precision: Lab LM uses seconds, Lab persistence/exfiltration minutes, OpTC seconds.
  A minute annotation gives a candidate interval `[minute, minute + 60s)`, not proof that every
  chunk intersecting the minute contains the event.
- Map each target to supporting records using timestamps and relevant entities/events. Review
  all prospective positive training windows and ambiguous boundaries without model predictions.
  Assign `supported_positive`, `no_annotated_target`, or `ambiguous/unsupported`, saving evidence
  references and rationale.
- Missing annotations, absent evidence, timestamp errors, or targets outside a view must not
  automatically become negative examples. Fix deterministic mapping errors or quarantine tasks
  with a reason; report counts before and after exclusion.

Under closed-world benchmark labels, unmatched findings count as false positives. A window
without an annotated target is not proof of benign activity. Audit a model-blind sample of both
negative attack-file windows and benign windows. Incomplete labels remain a limitation; do not
repair evaluation labels selectively after observing model answers.

For targets supported in multiple chunks, define eligible views and deduplication at scenario
aggregation. Do not enlarge only positive dev/test windows. Test minute/chunk boundaries,
multiple timestamps, timezones, out-of-order records, and multi-line audit events split by a boundary.

### 3.4 Classification

Use one complete scenario file per task; derive attack/benign privately from metadata. This
avoids labelling every chunk in an attack file as malicious without localized evidence. The
agent searches `/app/audit.log`; validate search/read behavior on the largest actual files.

This differs from upstream chunked classification and its aggregation. Keep any future
paper-compatible classification adapter separate; do not call whole-file results paper parity.

### 3.5 Sampler and optional augmentation

Keep `train-canonical` intact. Initial training draws use this explicit hierarchy:

1. Select one of four tasks uniformly.
2. Select positive/attack versus negative/benign with probability 1/2 within that task.
3. Select an eligible scenario group uniformly, then an available representation, then a
   canonical window/file within that group and class. Within the negative class, where both
   exist, balance negative attack-file windows and benign-file windows before group selection.

Resolve missing strata before freezing. Log realized frequencies and exposure per group.
Training distribution is intentionally balanced; dev/test preserve empirical benchmark prevalence,
which itself is not deployment prevalence. Long files, repeated benign views, or additional
representations must not dominate solely by creating more directories.

If pilot variation is inadequate, a documented alternative can add shifts of ±100/200/300 lines
from supported positive windows. Clip/deduplicate ranges and recompute evidence support and labels.
Choose parents before children so augmentation does not multiply a parent's probability. Leave
canonical negatives available and dev/test unchanged. Report distinct parents/events as well as
window counts: augmentation does not increase independent sample size.

If the loader cannot express this sampler, implement a seeded sampler or auditable sampling
manifests. Duplicating directories is not an implicit weighting policy.

### 3.6 Agent and verifier contract

```text
<opaque-task-id>/
  task.toml
  instruction.md
  environment/Dockerfile
  environment/audit.log
  solution/solve.sh            # oracle; excluded from the agent image
  tests/test.sh                # wrapper for isolated grading
  tests/ground_truth.json      # private target manifest
```

Use manifest-derived opaque IDs with collision checks. Requested task, format, and OS are
legitimate inputs. Answer label, source filename, scenario ID, split, and private target metadata
must not be exposed. Keep the source mapping outside sandbox mounts.

Generate instructions from complete v2 templates, including additional reference sections and
format/OS descriptions. Require a JSON array at `/app/findings.json`; investigation permits `[]`,
classification requires exactly one explicit verdict object. Specify fields, verdict enum,
timestamp formats, limits, and source-line references.

**Leakage checks must preserve legitimate evidence.** Keep hostnames, IPs, paths, attack commands,
and technique words already present in logs or public reference text. The draft's proposed ban
on ground-truth entity strings would remove the evidence needed to solve tasks. Instead require
the visible log to equal its designated source slice and check that labels, annotations, source
filenames, oracle files, and grader diagnostics are absent from accessible files, image layers,
environment variables, and mounts.

Use a pinned Linux image with Python, ripgrep, and jq preinstalled. Windows logs are data, not
a requirement for a Windows sandbox. Use an unprivileged agent, a read-only log, writable output
and scratch directories, and a fresh environment for every attempt.

Prefer a separate clean verifier: end the agent, copy only a bounded regular output file, then
grade against immutable data. Never execute output as code. Reject symlinks, oversized/invalid
files, NaN, and duplicate JSON keys. A shared verifier requires proof that agent changes cannot
alter its interpreter/imports, reward file, tests, or background process state. Uploading `tests/`
afterward is not by itself an integrity guarantee.

Set **environment-baseline no-network**, including the verifier, and test actual enforcement on
Modal. Phase-only overrides may require provider-specific dynamic switching. Current Harbor
docs show schema 1.4 and baseline network policy; validate the pinned schema rather than copying
the draft's schema 1.0 example. See [Harbor task and network configuration](https://github.com/harbor-framework/harbor/blob/main/docs/content/docs/tasks/index.mdx).
Model calls/controller run outside the sandbox. Cloud secrets, the source repo, training state,
and test tasks are never mounted. Build-time dependencies are separate from agent-time access.

## 4. Phase B — validate grading before model experiments

Separate strict parsing/schema validation, target matching, and metric/reward aggregation.
Keep a pinned upstream-compatibility scorer as well as the adapted training scorer.

Original matching uses timestamp/entity pairs for LM and timestamp plus substring matching for
persistence/exfiltration; only high-suspicion findings count by default. Original investigation
FPR is approximately `FP / log_lines`, not the probability of alerting on a benign task. Its
scenario/host counting cannot be reproduced by summing new chunk confusion matrices. See the
inspected [matching code](https://github.com/aanand300/auditlogsbench/blob/369ad441f2876245d0db19990c77ccbcb74a0a3a/inference/error_analysis/errorinvestigation_v2.py)
and [metric driver](https://github.com/aanand300/auditlogsbench/blob/369ad441f2876245d0db19990c77ccbcb74a0a3a/inference/metrics_comp/task_computemetrics.py).

The training scorer deliberately adds strict schema, explicit aliases, deduplicated target
coverage, and evidence grounding. Freeze case/path/timestamp/alias normalization; unrestricted
substring fields cannot collect every possible answer in one finding. Document every intentional
difference from legacy matching. Do not add arbitrary fuzzy matching after seeing model errors.

Required checks use synthetic fixtures and train/dev only:

- Oracle output passes every eligible train/dev task, including multi-target and benign cases.
  Independently check evidence support: an oracle passing its own answer key does not establish
  task solvability.
- Differential-test the compatibility scorer on the six shipped outputs at complete-scenario
  level, preserving chunk IDs, runs, empty outputs, and source rounding. Add fixtures for raw/OpTC
  and uncovered cases. Investigate mismatches; report upstream bugs instead of hiding them.
- Negative controls: invalid JSON, missing file, empty classification object, unknown verdict,
  wrong entity/time, duplicate findings, many candidates in one field, fake evidence references,
  and a response containing every permitted technique. None should gain accidental reward.
- Metamorphic checks: JSON key ordering does not matter, accepted aliases match, invalid times
  do not, duplicates cannot add recall, and host timezone does not change adapted scores.
- Integration checks: private files inaccessible, reward cannot be spoofed, state resets,
  network is blocked, and verifier failures are distinct from incorrect model answers.

Only `{"reward": <finite number>}` goes into the learner-facing reward file. Save counts,
assignments, parse errors, support flags, and termination status in separate diagnostics.
Verify that the pinned generator consumes the intended reward key; avoid diagnostic objects
or booleans in numeric reward maps.

## 5. Reward, metrics, and selection

### 5.1 Strict task reward

Let `G` be supported target units in the task, `TP` the number matched once, and `FP` unmatched
high-confidence findings. Require one entity/technique/path candidate per finding. Exact duplicate
reports are schema-invalid; distinct reports cannot add coverage for a target already matched.
Evidence references must exist and substantiate the timestamp/entity under frozen matching rules.

| Case | Binary success and reward `R=1` |
|---|---|
| Missing, malformed, schema-invalid, or oversized output | Never; `R=0`. |
| Classification | One valid object; `HIGH_SUSPICIOUS` iff attack, otherwise `LOW_SUSPICIOUS` or `MEDIUM_SUSPICIOUS`. Empty objects are invalid. |
| Investigation with supported targets | `TP = |G|` and `FP = 0`. |
| Investigation without annotated targets | No high-confidence finding; `[]` is valid. |

Otherwise `R=0`. Low/medium findings are not positives but still must validate. Propose limits
of 32 findings, 256 KiB total output, and bounded fields; confirm that legitimate train/dev targets
fit before freezing. Persistence technique fields use the public canonical list. Listing every
technique or several alternative paths is not a valid single prediction.

This replaces the draft's “any TP with one free FP” rule, which rewards partial detection and
tolerates false alerts. Retain original benchmark counts as separate metrics so the stricter
objective's effect is transparent.

**Pilot-only sparse-reward contingency.** If fewer than 10% of at least 50 sampled positive train
prompt-groups have nonzero reward variance, inspect labels, parsing, and context first. If partial
correct detections exist, try the single predefined alternative:

```text
Positive investigation: R_dense = (TP / |G|) / (1 + FP)
Classification and negative investigation: unchanged binary reward
Invalid output: 0
```

Report binary success separately. Neither this formula nor the draft's precision bonus helps
when no TP is ever found. Compare only the binary recipe and this contingency in the pilot,
disclose results, freeze one, then restart from original weights. If both lack signal, report
infeasibility or preregister a separate warm-start/SFT study. Do not silently add teacher/oracle
traces or change rewards during the main run.

### 5.2 Reported metrics

Report by task, dataset, representation, label category, and provenance group:

- Mean reward, strict success, schema validity, finding count, and no-report rate.
- Target recall, finding precision, unmatched findings/task, and fraction of negative tasks
  producing any high-confidence alert. Precision is undefined when no findings are emitted.
- Classification sensitivity, specificity, and balanced accuracy at the fixed verdict threshold.
- Scenario detection and benign-scenario false-alert probability after combining canonical chunks
  for a scenario/representation/attempt; OpTC LM unique-host recall separately. Include upstream
  TPR/FPR under its original conventions where the task unit is compatible.
- Turns, tool calls, observed/generated tokens, context exhaustion, policy/infra timeouts,
  inference/GPU/sandbox time, and cost. Distinguish refusal, malformed response, and incorrect answer.

For scenario metrics combine chunks with the same replication index. Do not assemble the best
chunks from different attempts. Five independent attempts give `pass@1 = successes/5` and binary
`pass@5 = 1` when any succeeds. Pass@5 assumes an oracle can identify a successful attempt; it is
not a deployable answer-selection procedure. Dense reward does not redefine binary success.

### 5.3 Dev score and manipulation check

Define for each pooled task `t`:

```text
P_t = mean per-positive-group false-positive-free target recall (classification: sensitivity)
N_t = mean per-negative-group valid clean-output rate (classification: specificity)
D   = mean over four tasks of (P_t + N_t) / 2
```

For investigation, false-positive-free recall equals target recall when output is valid and
`FP=0`, otherwise zero. Report ordinary recall separately; a checkpoint cannot increase its
selection score just by adding correct findings alongside many false ones.

Average attempts, canonical windows within each class/group, and representations before averaging
groups. Save the exact weighting implementation. Long logs or augmented windows must not multiply
group weight. Missing denominators are `NA`, not zero: resolve selection coverage at the split gate.
Also report natural task-weighted means.

Let `F` be the negative-task high-confidence alert rate with the same hierarchy, and `V` output
validity. Proposed checkpoint eligibility: `F <= F_base + 0.02` and `V >= V_base − 0.01`.
Freeze these practical thresholds; they are not statistical evidence of unchanged false-alert risk.
Show absolute counts/rates alongside them.

Select the eligible checkpoint with greatest `D`, breaking ties toward the earlier step, with
step 0 included. Proposed manipulation-check target is at least +0.10 in `D`, improved positive
detection/recall, and both eligibility constraints. Reward improvement from learning to say nothing
does not satisfy this. Dev gains are optimistically selected; later untouched evaluation is needed.

## 6. Step 1 — baseline collection and trajectory dataset

### 6.1 Validate and freeze the inference contract

First run a small train-only smoke test with the actual Qwen checkpoint and the trainer's execution
path. Another cheap API model cannot validate Qwen reasoning/template/parser behavior.

Candidate contract: Terminus-2, thinking on, temperature 1.0, top-p 1.0, top-k disabled, no added
repetition/presence penalty, at most 32 turns and 1,200 seconds per attempt. These sampling settings
are an experimental recipe choice, not Qwen's recommended inference defaults. Its model card
documents different thinking-mode sampling and native 32,768 context with optional YaRN extension.
See [Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B).

Start with 32,768 total context, an 8,192 per-completion cap clipped to remaining context, and a
2,048-token observation cap per tool call. Save full tool output outside the model transcript,
mark model-visible truncation, and keep full output retrievable in sandbox files. Do not silently
summarize history. Count prompts, prior thinking/actions, observations, and final output. Thirty-two
turns is a ceiling, not a guarantee they fit.

If needed, pilot 65,536 with YaRN factor 2 and original context 32,768 on both generator and
trainer. Four 141-GB GPUs alone do not establish memory feasibility. Freeze RoPE, template, and
budgets across base/defence/control comparisons; changes require rerunning affected baselines.

### 6.2 Baseline protocol

After smoke validation, collect **five attempts per canonical train and dev task**, with fixed
disjoint seed schedules and fresh environments. Do not filter tasks by base solve rate. Collect
control baselines too, and define a fixed canonical train diagnostic panel for later reevaluation.
If augmentation is enabled, collect its baseline separately from canonical summaries.

Trainer step-0 dev evaluation must agree with standalone evaluation under the same settings within
measured sampling variation. For pilot reward-variance estimates, collect fresh eight-sample groups
on train; five-attempt baseline statistics alone do not establish group-of-eight behavior. Dev
traces never enter gradients, replay, SFT, or preference pairs.

### 6.3 Required trajectory record

Save versioned structured records plus raw Harbor artifacts for every trial:

- Trial/attempt ID, split, task hash, parent group, window/view, schema, sampler probability,
  seed, policy revision/step, and resolved model/environment config.
- Every actual model request/rendered prompt/response and tool invocation, arguments, stdout,
  stderr, exit code, ordering, timing, terminal interactions, and model-visible truncation.
- Original generated token IDs, available sampling logprobs, tokenizer/template hashes, role
  boundaries, loss masks, reasoning tokens, token usage, and stop reason.
- Final output bytes/hash, grader version, raw reward, strict success, diagnostics, and policy
  versus infrastructure termination. Keep raw and trainer-adjusted rewards/masks distinct.
- During RL: prompt-group ID, behavior-policy snapshot, group rewards, advantages, old-policy
  logprobs, update ID, and every sample/group exclusion with a reason.

Train only on generated assistant tokens, including emitted reasoning and tool commands. Mask
system/user text, logs, tool output, grader content, and padding. Never put labels in actor context.

Validate exact request/token reconstruction, not merely saved chat JSON. Concatenated multi-turn
training requires prefix consistency, including retained historical thinking. If the pinned stack
uses step-wise training, pair each action with its actual context and mask previous actions so
they are not trained repeatedly. Missing token/logprob support is an integration gap, not a
reason to assume on-policy correctness.

The official [SkyRL–Harbor integration description](https://novasky-ai.notion.site/skyrl-harbor)
identifies history summarization and stripped thinking as training hazards. The draft's recipe
uses `qwen3_acc_thinking.jinja2`; standalone serving must not silently use a different template.

### 6.4 Reports and failure policy

Report §5 metrics, natural/balanced means, group solve distributions, independent positive groups
with any TP, and trivial policies such as always-no-finding/always-low-verdict. Successful traces
alone can conceal poor coverage.

Separate transport, container-start, and verifier failures from wrong answers. Permit at most two
transient-infrastructure retries and retain failed records; never retry wrong answers until success.
During RL, drop/recollect affected prompt-groups under the same policy snapshot to preserve group
comparability. During evaluation, report unresolved attempts and a count-as-failure sensitivity
analysis rather than silently reducing denominators.

Model-caused invalid output, command failure, and exhausted time/turn/token budgets are policy
outcomes under a frozen rule: default strict success zero. If an overlong trajectory cannot be
trained without corrupting its mask, exclude it from gradients but retain its evaluation failure
and exclusion statistics. Verify the pinned implementation: an upstream
[custom-generator issue](https://github.com/NovaSky-AI/SkyRL/issues/1156) documents ignored
overlong/termination settings in earlier Harbor paths. Configuration names are not proof of behavior.

## 7. Step 2 — online GRPO, pilot, and main training

### 7.1 Learning algorithm and data flow

For each iteration, sample 32 train tasks and generate eight independent trajectories per task
from a frozen current-policy snapshot. Grade terminal output. Initially use centered advantages
`A_i = R_i − mean(R_group)` without standard-deviation normalization, then a clipped policy-ratio
loss on assistant tokens. Synchronize updated weights before the next rollout batch.

Step-1 trajectories are diagnostic artifacts. Repeatedly replaying them is not ordinary online
GRPO, even with saved behavior logprobs. Concurrent inference requests are fine; stale-policy
asynchronous training is a different design requiring explicit corrections.

Initial recipe: 32 prompts × 8 samples; one update epoch per batch; learning rate 1e-6; full BF16
FSDP2 fine-tuning; no KL penalty; at most 100 trainer iterations. Pin optimizer betas/epsilon/weight
decay, gradient clipping, policy-ratio clipping, scheduler, loss reduction, microbatching, and
parallelism in the resolved config. Monitor entropy, policy-ratio/clip fraction, gradient norm,
and policy drift on a fixed diagnostic panel. No-KL is a choice, not a stability guarantee.

The [harbor-train Qwen recipe](https://github.com/fleet-ai/harbor-train/blob/main/skyrl-train/tasks/harbor-grpo-qwen3-8b.yaml)
is a starting point. Its setup downloads HF datasets; local data require changes to setup and
loader paths. Validate directory loading and the sampler. Enforce an exact native iteration cap;
epoch estimates and delayed W&B cancellation are insufficient. Record iterations, actual nonzero
updates, and rollouts separately. Skip optimization for an entirely zero-advantage batch while
still counting its rollout cost and attempted iteration.

**Dynamic sampling is off in the primary recipe.** Record all-equal/zero-advantage groups by
task/class. If piloted separately, a filtering variant needs a preregistered cap of at most 2×
nominal rollouts/iteration, acceptance statistics, and an insufficient-batch stop. The draft's
`max_sample_batches=30` does not justify assuming only 50% extra cost; it can substantially change
both cost and effective training distribution.

### 7.2 Compatibility and correctness pilot

Require one successful rollout batch, backward/update, evaluation, export/reload, and interruption/
resume test before the full pilot. Run at most ten iterations on train, with dev for monitoring
only. Archive pilot artifacts; reset weights, optimizer, sampler, and RNG for the main run.

| Gate | Required evidence |
|---|---|
| Configuration | Pinned schemas accept every field; resource/network limits enforced on Modal; no silently ignored settings. |
| Token/mask correctness | Actual contexts and exact masks; no loss on observations; valid reasoning retention or step-wise alignment. |
| Probability consistency | Before updates, compare sampler/trainer logprobs for identical tokens/prefixes. Record distributions and a tolerance justified by same-weight precision/backend checks; investigate systematic mismatch. |
| Reward/advantage | Synthetic groups give expected signs/magnitudes; equal rewards give zero advantage; diagnostic fields never become rewards. |
| Learnability | Positive detections across independent groups and useful reward variation, or explicit invocation of §5.1 and its stop rule. |
| Resources | Peak actor/optimizer/activation/KV memory, CPU RAM, disk, token rates, p50/p95 rollout and iteration time. |
| Failures | Proposed targets: <5% context/policy timeouts, <2% unresolved infrastructure failures; all exclusions categorized. |
| Resume/export | Restore optimizer/RNG/sampler/step; exported checkpoint reproduces the live policy within measured tolerance. |
| Control | Eligible tasks run offline within the declared tool/budget contract with nontrivial reward variation. |

Start concurrency at 16–32, then raise against quotas and inference capacity. A 256-rollout batch
does not require 256 simultaneous sandboxes. Keep queued work outside live sandboxes where possible;
waiting for inference can consume paid sandbox lifetime. Verify provider CPU, memory, and storage
semantics rather than assuming “1 CPU” is portable.

Prefer 32k if adequate. Diagnose excessive tool output before testing 64k. If the longer context
fails memory checks, select a declared shorter configuration and rerun baselines; do not alternate
32k/48k/64k mid-run. LoRA, another model, or teacher warm-starts define different treatments.

### 7.3 Main defence run and selection

Freeze the protocol after pilot (§9). Start from original weights in a new run directory; prevent
accidental `resume latest` from pilot state. Evaluate dev at step 0 and every five iterations with
the same five-attempt seed schedule. Save checkpoint/evaluation artifacts atomically before marking
a step selectable. Reevaluate the fixed canonical train panel with matching metrics.

Use trainer-integrated early stopping at evaluation boundaries. Enforce hard resource caps and
integrity stops immediately, saving a recoverable state even between scheduled evaluations:

- Hard cap: 100 iterations and preregistered total rollout/token/dollar caps, whichever first.
- Early stop: four consecutive scheduled evaluations without an eligible `D` improvement of at
  least 0.01 over the previous best, including step 0. This is a compute heuristic, not significance.
- Investigate immediately on invalid numerical state, reward-isolation failure, missing artifacts,
  or broken token/logprob alignment. Pause for inspection if policy exhaustion exceeds 20% for two
  consecutive batches, infrastructure errors exceed 5%, or three batches have no useful advantage
  variation. Record whether the issue invalidates the run.

Monitor length changes, false alerts, and task regressions. Shorter reasoning can be beneficial;
sampled train reward is not comparable with natural dev reward. Neither a raw length threshold
nor a train-minus-dev gap of 0.3 proves pathology/memorization. Compare the fixed canonical train
panel to dev under the same metric weights. Config changes require a new recorded run, not silent
restarts until the curve looks favorable.

Let `S` be the selected eligible checkpoint and `T` the actual terminal iteration. Export
`defence-selected-S`, `defence-final-T`, all evaluated weights, and the complete step-0 manifest.
If no checkpoint beats step 0, select step 0 and report failed manipulation. Preserve the trained
endpoint for Stage 2 so zero-step selection does not conceal training effects.

For paired model differences, use the same provenance-group bootstrap draws for both models,
resampling all a group's views/chunks/attempts together. A proposed reporting convention is 95%
intervals from 10,000 draws, with raw group counts and per-group differences shown alongside.
If a bootstrap draw lacks a required metric denominator, report the frequency and use a frozen
stratified procedure rather than silently dropping draws. Overlapping windows and repeated
attempts are not independent scenarios.
One-seed intervals are conditional on that training run; dev intervals after repeated selection
are descriptive, not unbiased evidence. With multiple seeds, report each and distinguish
seed-level variation from scenario sampling variation.

### 7.4 Generic terminal-training control

Treat `open-thoughts/OpenThoughts-TB-dev` as a candidate pool, not a guaranteed large enough
training set. Its authors describe it as a terminal-agent development benchmark, not a curated
non-security control. See [dataset card](https://huggingface.co/datasets/open-thoughts/OpenThoughts-TB-dev).

Before main training, inspect instructions, assets, solutions, tests, and environment requirements.
Exclude attack/defence, malware, vulnerability, exploitation, CTF, and security-forensics tasks.
Keyword screening is only a first pass: generic software logs are not necessarily cyber material,
and security tasks may lack obvious keywords. Prefer routine text/file transformations, data
manipulation, and shell tasks with comparable read/search/write behavior. Save the review rubric.

Deduplicate task families before splitting control train/dev. Reserve dev before matching train
size. If there are too few eligible independent tasks, select a documented alternative pool before
main runs; do not pad duplicates and call them distinct tasks. Check shared assets/solutions/
provenance with every Stage-2 benchmark, and review any replacement pool the same way.

Match original weights, agent/tools, optimizer, reward scale, generation settings, per-attempt
time/context/turn budgets, and iteration schedule. Prefer predeclared control strata comparable
in baseline difficulty/length without filtering defence tasks by solve rate. Preserve required
control resources or choose an appropriate subset; forcing unrelated tests into 1 GiB can create
artificial failures.

Train control to `T`, retaining both `control-S` and `control-T`. This enables selected-step and
matched terminal-step comparisons, including when `S=0`. Since early stopping can determine `T`,
the terminal comparison is not an independently fixed-budget experiment. Control-dev does not select
the control endpoint. Record incomplete matched runs rather than silently comparing unequal budgets.

For both arms log sampled/accepted trajectories, inference tokens, assistant loss tokens, nonzero
updates, GPU/sandbox hours, reward variance, and drift. Equal iterations is the primary convention;
a separately preregistered token-matched checkpoint can be a sensitivity analysis. It is not exact
compute matching. A stronger follow-up uses three paired seeds with the same split/protocol; this
estimates training-seed variation, not variation across alternative splits.

## 8. Infrastructure, budget, and artifact retention

### 8.1 Provisioning and secrets

*(amended)* RunPod Secure Cloud 4×H200 SXM via SkyPilot (`configs/skypilot/runpod-4xh200.yaml`, API key in
`.env` and `~/.runpod/config.toml`); setup is `scripts/node_bootstrap.sh`, phases run with `sky exec` through
`scripts/phase.sh`, and the pod stops itself at the end of every phase. Verify region/volume compatibility, host
RAM, interconnect, availability, and actual Secure Cloud selection. The RunPod network volume is attached at
`/workspace`; the container disk is not durable checkpoint storage.

`.env.template` includes names/comments only:

```dotenv
MODAL_TOKEN_ID=            # optional; Docker sandboxes on the node are the default
MODAL_TOKEN_SECRET=
WANDB_API_KEY=
WANDB_ENTITY=
WANDB_PROJECT=auditbench-uplift
HF_TOKEN=
```

Secrets reach the node only through SkyPilot's `--env-file .env` injection; git-ignore `.env`; prevent
values entering configs/logs/sandboxes.
Stage 1 needs no Stage-2 judge key. W&B holds metrics/artifact references; durable records remain
authoritative when telemetry is unavailable. The trainer enforces stops/saves; a watcher is a watchdog.

### 8.2 Budget from measured inputs

RunPod currently lists H200 Secure Cloud starting at $4.59/GPU-hour, or $18.36/hour for four.
Capture actual launch price and availability. See [RunPod H200 pricing](https://www.runpod.io/articles/guides/nvidia-h200-gpu).

Modal's listed sandbox rates are $0.00003942/physical-core-second and $0.00000667/GiB-second:
about **$0.1659/hour for one physical core + one GiB**, before multipliers/other charges. Billing
uses the greater of requested and actual resources. Listed Starter container concurrency is 100;
256 is not a safe default. See [Modal pricing](https://modal.com/pricing) and
[sandbox resource billing](https://modal.com/docs/guide/sandbox-resources).
*(amended)* Sandboxes are Modal; `C_sandbox` applies as listed. Idle node time proved to be the dominant
leak (≈$175 on 2026-10-04 before any job ran), hence the per-phase self-stop.

```text
R_baseline = 5 × (N_train_canonical + N_dev + N_control_baseline)
R_train    = 256 × (I_pilot + I_defence + I_control), before retries/resampling
R_eval     = 5 × N_dev × number_of_defence_evaluations
             + control monitoring + fixed train-panel evaluations
C_gpu      = GPU_count × GPU_hourly_rate × allocated_hours
C_sandbox  = sum of attempt billable CPU/GiB-seconds × rates
C_total    = C_gpu + C_sandbox + storage + egress + builds + subscriptions + contingency
```

*(amended)* Hard cap: **$1,500 total** across setup/smoke/baseline ($300), pilot ($250), defence
($475), control ($475). After the pilot, `T_max = min(100, floor(per-arm budget / measured cost per
iteration))`; control trains to the defence terminal step. Ten pilot + 100 defence + 100 control
iterations would mean 53,760 training rollouts alone, which the cap will not permit at plausible
iteration times. At average
sandbox lifetimes of 5 / 10 / 20 minutes, nominal one-core/one-GiB cost is approximately
**$743 / $1,487 / $2,973**, before evaluation, failures, and multipliers. If iterations take
15–35 minutes, 210 iterations occupy 52.5–122.5 node-hours, approximately **$964–$2,249** in GPU
cost before evaluation overhead. These are sensitivity calculations, not measured throughput or
a spending commitment.

For example, 100 dev tasks evaluated 20 times with five attempts add 10,000 rollouts. Include
baseline and step-0 evaluation separately if both are run. Filtering, retries, queues, and control
tasks can dominate the draft's estimate. Use pilot measurements to publish low/central/high forecasts
and freeze explicit spend/token/rollout caps before main training. Report each seed's cost.

### 8.3 Storage and recovery

An 8.2B BF16 weight export is about 16.4 GB (decimal); 21 checkpoints approach 344 GB per arm
before optimizer state, logs, or copies. Full resume checkpoints can be several times larger.
Measure actual size and capacity in the pilot rather than assuming everything fits on 500 GB.

Keep all evaluated weight checkpoints durably with checksums, plus selected/final exports. Keep
at least the two latest complete resume states and selected/final states. Remove older optimizer
states only under the frozen retention rule after verified backup. Compress/index trajectories
and back up independently; test restore before deleting a pod. Enforce disk-space guards and
explicitly terminate finished sandboxes/jobs while preserving partial-run artifacts.

## 9. Preregistration and execution gates

Before model pilots, date a protocol describing hypotheses, split policy, candidate recipes,
pilot decisions, and contingency triggers. After the pilot, freeze `PREREG.md` before main training,
linking all pilot findings/amendments. Disclose pilot-informed choices; do not present them as
fixed before any model evidence.

The frozen preregistration includes:

- Claims, experimental unit, one-seed versus replicated scope; exact model/data/version hashes.
- Split/group/label audit, exclusions, sealed-test policy, sampler and optional augmentation.
- Strict reward, original-score compatibility, metric weighting, false-alert constraints,
  manipulation-check margin, checkpoint/tie rules, and dev query budget.
- Every model/training/inference setting, token/mask contract, error/retry handling, numerical
  checks, stopping/pathology rules, rollout/token/dollar caps, and retention policy.
- Control rubric/families, leakage checks, budget matching, and seeds; uncertainty method and
  treatment of failures or step-0 selection.
- Later checkpoint contrasts and benchmark identities/revisions. Resolve the exact intended
  **ExploitBench** repository/release rather than substituting a similarly named benchmark.
  Check shared provenance against CyberGym, ExploitBench, AuditBench, and ExCyTIn-Bench. Never
  tune on offence outcomes. Stage 2 will specify benchmark-specific scoring, judges, multiplicity,
  and equivalence analysis before results are opened; do not impose binary pass@5 on nonbinary tasks.

Proposed repository layout (only this plan exists at review time):

```text
auditbench-uplift/
  PLAN.md
  PREREG.md
  pyproject.toml, uv.lock, .env.template, .gitignore
  auditbench_harbor/         # inventory, provenance graph, split, labels, task builder
  grader/                   # strict matching, reward, compatibility scorer, fixtures
  training/                 # sampler, trajectory conversion/masks, stop/selection hooks
  configs/                  # inference contract, Harbor trial/job configs, baseline, pilot, defence, control
  scripts/                  # validation, collection, budget, export, reporting
  manifests/                # versions, hashes, labels, control review, retention rules
  splits/                   # train/dev/test, grouping evidence
  tasks/                    # generated; ignored; test absent from training workers
  trajectories/             # indexed artifacts; durable volume + independent backup
  checkpoints/              # artifact index; weights/resume states in durable storage
  reports/                  # inventory, labels, adapter, baseline, pilot, training
```

| Gate | Deliverable | Proceed only when |
|---|---|---|
| A: data | Inventory, provenance graph, label audit, feasible locked splits | Leakage checks pass and independent target/dev coverage is adequate. |
| B: environment | Adapter, strict/compatibility scorers, synthetic/train/dev checks | Grader correctness, evidence support, and isolation pass; differences are documented. |
| C: step 1 | Actual-model smoke, canonical/control baseline, trajectory archive | Records reconstruct correctly and positive detections/reward variation exist. |
| D: pilot | Up to ten iterations, resume/export checks, resource report | Correct training path, feasible recipe, bounded budget, frozen preregistration. |
| E: step 2 | Defence/control runs, selected/final exports, training report | Runs/deviations recorded, exports load, backups verify; improvements or failures reported. |

Allow roughly 3–5 engineering days for provenance/labels, 3–5 for adapter/grading, 2–4 for
integration/baseline/pilot, then measured training/analysis time. These phases are gated; a fixed
three-week completion promise is premature. More seeds add compute and analysis time.

Stage 2 receives the exact base artifact, selected and terminal defence/control checkpoints per
seed, sealed AuditBench-Agent test manifest/builder, both scoring paths, trajectories, inference
contract, hashes, preregistration, and reports including failed runs and cost accounting. Carry
forward the limitations: small scenario population, imperfect annotations, adapted interface,
possible pretraining contamination of public benchmarks, and conditional one-seed uncertainty.
