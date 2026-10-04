#!/usr/bin/env python
"""Log the frozen data artifacts (versions, inventory, groups, splits, label summaries, gate reports)
to W&B as one versioned artifact. Set WANDB_MODE=offline to test without a key."""
from auditbench_harbor.paths import REPO_ROOT
from training.wandb_log import init_run, log_manifest_artifact


def main() -> None:
    run = init_run("data-manifests", "manifest", tags=["gate-a", "gate-b"])
    paths = [REPO_ROOT / p for p in ("manifests/versions.json", "manifests/inventory.json", "manifests/groups.json",
                                     "manifests/labels/summary.json", "manifests/units/summary.json", "manifests/control_review.jsonl",
                                     "manifests/control_rubric.md", "splits", "reports/gate_b_checks.json", "reports/compat_differential.json",
                                     "configs/inference_contract.yaml")]
    # test-split label/unit files are deliberately not uploaded
    log_manifest_artifact(run, "auditbench-agent-data", paths, REPO_ROOT, metadata={"schema": "auditbench-agent-v1"})
    run.finish()
    print("logged", run.url if hasattr(run, "url") else "(offline)")


if __name__ == "__main__":
    main()
