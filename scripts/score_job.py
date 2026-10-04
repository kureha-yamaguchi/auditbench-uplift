#!/usr/bin/env python
"""Compute §5.2 metrics and the §5.3 dev score for an indexed trajectory file, and log to W&B.

    python scripts/score_job.py trajectories/dev-step-0000.jsonl --split dev --step 0 --arm base
"""
import argparse
import json
from pathlib import Path

from auditbench_harbor.cli import UNITS_DIR
from auditbench_harbor.paths import REPO_ROOT
from auditbench_harbor.windows import load_units
from training.metrics import dev_score, trivial_policies
from training.wandb_log import init_run, log_table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--split", required=True, choices=["train", "dev"])
    ap.add_argument("--step", type=int, required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--no-wandb", action="store_true")
    args = ap.parse_args()
    units = [u.__dict__ for u in load_units(UNITS_DIR / f"{args.split}.jsonl")]
    records = [json.loads(line) for line in Path(args.records).read_text().splitlines() if line.strip()]
    score = dev_score(records, {u["task_id"]: u for u in units})
    score["trivial_policy"] = trivial_policies(units)
    out = REPO_ROOT / "reports" / "evaluations" / f"{args.arm}-{args.split}-step{args.step:04d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(score, indent=1) + "\n")
    print(json.dumps({k: score[k] for k in ("D", "false_alert_rate", "validity", "termination")}, indent=1))
    if not args.no_wandb:
        run = init_run(f"{args.arm}-{args.split}-eval", "evaluation", {"arm": args.arm, "split": args.split, "step": args.step})
        flat = {f"{args.split}/D": score["D"], f"{args.split}/false_alert_rate": score["false_alert_rate"], f"{args.split}/validity": score["validity"]}
        for task, m in score["per_task"].items():
            for k, v in m.items():
                if isinstance(v, (int, float)) or v is None:
                    flat[f"{args.split}/{task}/{k}"] = v
        run.log(flat, step=args.step)
        log_table(run, f"{args.split}/per_task", [dict(task=t, **m) for t, m in score["per_task"].items()])
        run.finish()


if __name__ == "__main__":
    main()
