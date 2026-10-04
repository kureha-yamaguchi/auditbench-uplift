#!/usr/bin/env python
"""Apply §5.3/§7.3 selection to the evaluation files written by score_job.py for one arm."""
import argparse
import json

from auditbench_harbor.paths import REPO_ROOT
from training.selection import Evaluation, select, should_stop_early


def load_evals(arm: str) -> list[Evaluation]:
    evals = []
    for p in sorted((REPO_ROOT / "reports" / "evaluations").glob(f"{arm}-dev-step*.json")):
        d = json.loads(p.read_text())
        step = int(p.stem.rsplit("step", 1)[1])
        recall = [m["ordinary_recall"] for m in d["per_task"].values() if m.get("ordinary_recall") is not None]
        evals.append(Evaluation(step, d["D"], d["false_alert_rate"], d["validity"], sum(recall) / len(recall) if recall else None))
    return evals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    args = ap.parse_args()
    evals = load_evals(args.arm)
    if not any(e.step == 0 for e in evals):
        raise SystemExit("step-0 evaluation is required")
    result = select(evals)
    result["early_stop_triggered"] = should_stop_early(evals)
    out = REPO_ROOT / "reports" / f"selection-{args.arm}.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
